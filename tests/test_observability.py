"""Operational logging: the rotating log file, tool-call lines, request lines.

Fly keeps minutes of logs, so a 38 s hang of six parallel calls could not be
reconstructed. The server now logs every tool call and request compactly to a
file on its volume, without full client IP addresses.
"""

import logging
import re

import httpx
import pytest

from study_bible_mcp import observability, server
from study_bible_mcp.observability import client_tag, configure_logging, summarize_arguments


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    observability.stop_logging()
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def no_database_needed(monkeypatch):
    # list_research_sources reads no database; call_tool only checks one is open.
    monkeypatch.setattr(server, "db", object())


async def test_log_file_records_tool_calls_and_warns_on_slow_ones(
    tmp_path, monkeypatch, restore_logging, no_database_needed
):
    log_path = configure_logging(tmp_path / "logs")
    assert log_path == tmp_path / "logs" / "server.log"

    await server.call_tool("list_research_sources", {"topic": "rabbinic"})
    monkeypatch.setattr(observability, "SLOW_CALL_SECONDS", 0.0)
    await server.call_tool("list_research_sources", {"topic": "jewish\nlines", "limit": 2})
    await server.call_tool("no_such_tool", {})
    observability.stop_logging()  # flush the queue to the file

    lines = log_path.read_text().splitlines()
    timestamp = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
    assert any(re.fullmatch(
        rf'{timestamp} INFO tool: list_research_sources ok \d+ms out=\d+ topic="rabbinic"', line
    ) for line in lines), lines
    assert any(re.fullmatch(
        rf'{timestamp} WARNING tool: list_research_sources ok \d+ms out=\d+ '
        r'topic="jewish lines" limit=2 SLOW', line
    ) for line in lines), lines
    assert any("WARNING tool: no_such_tool unknown-tool" in line for line in lines), lines


async def test_tool_errors_are_logged_with_their_traceback(
    tmp_path, monkeypatch, restore_logging, no_database_needed
):
    async def broken(args):
        raise RuntimeError("boom")

    monkeypatch.setitem(server._TOOL_HANDLERS, "list_research_sources", broken)
    log_path = configure_logging(tmp_path)
    result = await server.call_tool("list_research_sources", {})
    observability.stop_logging()

    assert result[0].text == "Error: boom"
    text = log_path.read_text()
    assert re.search(r"ERROR tool: list_research_sources error \d+ms out=11\n"
                     r"Traceback \(most recent call last\):", text), text
    assert "RuntimeError: boom" in text


def test_an_unusable_log_directory_never_stops_the_server(tmp_path, restore_logging, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    assert configure_logging(blocker / "logs") is None
    logging.getLogger("tool").info("still logging")  # no exception


def test_client_tag_keeps_the_network_and_hashes_the_address():
    tag = client_tag("160.79.104.12")
    assert re.fullmatch(r"160\.79\.104\.\*~[0-9a-f]{6}", tag)
    assert client_tag("160.79.104.12") == tag
    assert client_tag("160.79.104.13") != tag
    assert re.fullmatch(r"2001:db8:abcd:\*~[0-9a-f]{6}", client_tag("2001:0db8:abcd:0012::1"))
    assert client_tag("::ffff:160.79.104.12") == tag
    assert client_tag("not an address") == "?"
    assert client_tag(None) == "-"


def test_argument_summary_is_short_and_on_one_line():
    summary = summarize_arguments({
        "reference": "John 3:16",
        "query": "x" * 100,
        "versions": ["bsb", "lxx"],
        "include_original": True,
        "theme": None,
        "note": "two\nlines\t here",
    })
    assert summary == (
        'reference="John 3:16" query="' + "x" * 39 + '…" versions=bsb,lxx '
        'include_original=True note="two lines here"'
    )
    assert len(summarize_arguments({f"k{i}": "y" * 40 for i in range(10)})) == 160


async def test_requests_are_logged_with_timing_and_without_full_ip(caplog, no_database_needed):
    caplog.set_level(logging.INFO)
    app = server.build_http_app()
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "list_research_sources", "arguments": {"topic": "rabbinic"}}}
    headers = {"accept": "application/json, text/event-stream",
               "fly-client-ip": "203.0.113.77", "user-agent": "test-client/1.0"}
    transport = httpx.ASGITransport(app=app)
    async with app.app.router.lifespan_context(app.app), httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        assert (await client.post("/mcp/", json=call, headers=headers)).status_code == 200
        assert (await client.get("/health")).status_code == 200
        for _ in range(3):
            assert (await client.get("/no-such-page", headers=headers)).status_code == 404

    messages = [(r.name, r.levelname, r.getMessage()) for r in caplog.records]
    http = [m for name, _, m in messages if name == "http"]
    tool = [m for name, _, m in messages if name == "tool"]
    assert re.fullmatch(
        r"POST /mcp/ 200 \d+ms rpc=tools/call client=203\.0\.113\.\*~[0-9a-f]{6} ua=test-client/1\.0",
        http[0],
    ), http
    client = http[0].split("client=")[1].split()[0]
    assert re.fullmatch(
        rf'list_research_sources ok \d+ms out=\d+ topic="rabbinic" client={re.escape(client)}',
        tool[0],
    ), tool
    # /health is not logged; a repeated 404 is logged once.
    assert not any("/health" in m for m in http)
    assert [m for m in http if "/no-such-page" in m] == [
        f"refused GET /no-such-page status=404 client={client} ua=test-client/1.0"
    ]
    assert not any("203.0.113.77" in m for _, _, m in messages)


async def test_rate_limited_clients_are_logged_once_per_window(caplog):
    caplog.set_level(logging.INFO)
    app = server.build_http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        for _ in range(105):
            await client.post("/messages?session_id=x", json={}, headers={"fly-client-ip": "198.51.100.9"})
    limited = [r.getMessage() for r in caplog.records if "rate limited" in r.getMessage()]
    assert len(limited) == 1
    assert limited[0].startswith("rate limited: client=198.51.100.*~")


def test_a_failing_log_file_pauses_instead_of_spamming(tmp_path, restore_logging, capsys):
    configure_logging(tmp_path)
    file_handler = next(h for h in observability._listener.handlers
                        if isinstance(h, observability._PausingFileHandler))

    def full_disk(record):
        raise OSError(28, "No space left on device")

    file_handler.shouldRollover = full_disk
    for n in range(5):
        logging.getLogger("tool").info(f"line {n}")
    observability.stop_logging()
    errors = capsys.readouterr().err
    assert errors.count("log file write failed") == 1
    assert "Traceback" not in errors
