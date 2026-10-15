"""The legacy SSE transport answers its routes without raising.

SseServerTransport's handlers send their own responses and return None. Routed
as request -> response endpoints, Starlette called that None, so every POST to
/messages (in production, a stale client posting to a dead session about once a
second) and every SSE disconnect logged a TypeError traceback.
"""

import asyncio
import re
import uuid

import anyio
import httpx
import pytest
from mcp.types import LATEST_PROTOCOL_VERSION

from study_bible_mcp import server

PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def _client(app):
    # ASGITransport re-raises exceptions from the app, so a TypeError fails the test.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.parametrize("build_app", [server.build_http_app, server.build_sse_app])
@pytest.mark.parametrize(
    ("query", "status", "text"),
    [
        (f"session_id={uuid.uuid4().hex}", 404, "Could not find session"),
        ("session_id=not-a-session", 400, "Invalid session ID"),
        ("", 400, "session_id is required"),
    ],
    ids=["unknown-session", "malformed-session", "missing-session"],
)
async def test_message_post_without_a_live_session_gets_a_client_error(
    build_app, query, status, text
):
    async with _client(build_app()) as client:
        response = await client.post(f"/messages?{query}", json=PING)

    assert response.status_code == status
    assert response.text == text


async def test_message_endpoint_is_still_rate_limited():
    async with _client(server.build_http_app()) as client:
        statuses = [
            (await client.post("/messages?session_id=x", json=PING)).status_code
            for _ in range(101)
        ]

    assert statuses == [400] * 100 + [429]


async def test_sse_session_takes_messages_at_its_advertised_endpoint_and_closes_cleanly():
    app = server.build_http_app()
    chunks: list[str] = []
    new_chunk = anyio.Event()
    client_gone = anyio.Event()

    async def receive():
        await client_gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal new_chunk
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append(message["body"].decode())
            new_chunk.set()
            new_chunk = anyio.Event()

    async def wait_for(pattern):
        with anyio.fail_after(5):
            while not (match := re.search(pattern, "".join(chunks))):
                await new_chunk.wait()
        return match

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": "/sse", "raw_path": b"/sse",
        "root_path": "", "query_string": b"", "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }

    # An exception from the SSE route (as on disconnect before the fix) fails the task group.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(app, scope, receive, send)
        endpoint = (await wait_for(r"event: endpoint\r?\ndata: (\S+)")).group(1)
        assert re.fullmatch(r"/messages\?session_id=[0-9a-f]{32}", endpoint)

        async with _client(app) as client:
            response = await client.post(endpoint, json=initialize)
        assert response.status_code == 202

        await wait_for(r"event: message\r?\ndata: .*\"serverInfo\"")
        client_gone.set()


async def test_mcp_without_a_trailing_slash_is_served_not_redirected():
    app = server.build_http_app()
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}
    headers = {"accept": "application/json, text/event-stream"}
    async with app.app.router.lifespan_context(app.app), _client(app) as client:
        for path in ("/mcp", "/mcp/"):
            response = await client.post(path, json=body, headers=headers)
            assert response.status_code == 200, (path, response.status_code)
            assert '"serverInfo"' in response.text


# --- SSE sessions: keepalive, closed sessions, logging ------------------------

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


class _SseStream:
    """One GET /sse driven by hand: its body chunks, and a way to hang up."""

    def __init__(self, app, headers=()):
        self.app = app
        self.chunks: list[str] = []
        self._new_chunk = anyio.Event()
        self._gone = anyio.Event()
        self.scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/sse", "raw_path": b"/sse",
            "root_path": "", "query_string": b"",
            "headers": [(b"host", b"testserver"), *headers],
            "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        }

    async def receive(self):
        await self._gone.wait()
        return {"type": "http.disconnect"}

    async def send(self, message):
        if message["type"] == "http.response.body" and message.get("body"):
            self.chunks.append(message["body"].decode())
            self._new_chunk.set()
            self._new_chunk = anyio.Event()

    async def wait_for(self, pattern, timeout=5):
        with anyio.fail_after(timeout):
            while not (match := re.search(pattern, "".join(self.chunks))):
                await self._new_chunk.wait()
        return match

    async def run(self):
        await self.app(self.scope, self.receive, self.send)

    def hang_up(self):
        self._gone.set()


async def test_sse_stream_sends_keepalive_pings(monkeypatch):
    from sse_starlette import EventSourceResponse

    monkeypatch.setattr(EventSourceResponse, "DEFAULT_PING_INTERVAL", 60)
    app = server.build_http_app()
    # Building the routes pins the interval (sse-starlette's own default today).
    assert EventSourceResponse.DEFAULT_PING_INTERVAL == server.SSE_PING_SECONDS == 15

    monkeypatch.setattr(EventSourceResponse, "DEFAULT_PING_INTERVAL", 1)
    stream = _SseStream(app)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(stream.run)
        await stream.wait_for(r"event: endpoint")
        await stream.wait_for(r": ping", timeout=3)
        stream.hang_up()


async def test_a_closed_sse_session_answers_404_not_202():
    """The SDK kept a session's writer after its stream closed, so a POST to it
    got 202 Accepted and the message was dropped: the client's call hung."""
    app = server.build_http_app()
    stream = _SseStream(app)
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(stream.run)
        endpoint = (await stream.wait_for(r"event: endpoint\r?\ndata: (\S+)")).group(1)
        async with _client(app) as client:
            assert (await client.post(endpoint, json=INITIALIZE)).status_code == 202
        await stream.wait_for(r"\"serverInfo\"")
        stream.hang_up()

    async with _client(app) as client:
        response = await client.post(endpoint, json=PING)
    assert (response.status_code, response.text) == (404, "Could not find session")


async def test_sse_sessions_and_stale_posts_are_logged_compactly(caplog):
    caplog.set_level("INFO")
    app = server.build_http_app()
    stream = _SseStream(app, headers=[(b"fly-client-ip", b"203.0.113.77"),
                                      (b"user-agent", b"sse-test/1")])
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(stream.run)
        endpoint = (await stream.wait_for(r"event: endpoint\r?\ndata: (\S+)")).group(1)
        session = endpoint.rsplit("=", 1)[1]
        async with _client(app) as client:
            await client.post(endpoint, json=INITIALIZE)
        await stream.wait_for(r"\"serverInfo\"")
        stream.hang_up()

    stale = uuid.uuid4().hex
    async with _client(app) as client:
        for _ in range(5):  # a stale poller
            assert (await client.post(f"/messages?session_id={stale}", json=PING)).status_code == 404
        await client.post(f"/messages?session_id={uuid.uuid4().hex}", json=PING)

    lines = [r.getMessage() for r in caplog.records if r.name == "sse"]
    assert re.fullmatch(rf"open sid={session[:8]} client=203\.0\.113\.\*~\w{{6}} ua=sse-test/1",
                        lines[0])
    assert re.fullmatch(rf"close sid={session[:8]} \d+s posts=1 client=203\.0\.113\.\*~\w{{6}}",
                        lines[1])
    stale_lines = [line for line in lines if line.startswith("stale ")]
    assert len(stale_lines) == 2  # one per distinct session id, not one per POST
    assert stale_lines[0].startswith(f"stale sid={stale[:8]} status=404 client=")
    assert not any("203.0.113.77" in r.getMessage() for r in caplog.records)


async def test_redirects_point_at_https_behind_the_proxy():
    """Through uvicorn as deployed: Fly's X-Forwarded-Proto makes any redirect https."""
    import uvicorn

    app = server.build_http_app()
    runner = uvicorn.Server(server.uvicorn_config(app, "127.0.0.1", 0))
    task = asyncio.create_task(runner.serve())
    try:
        with anyio.fail_after(10):
            while not runner.started:
                await asyncio.sleep(0.01)
        port = runner.servers[0].sockets[0].getsockname()[1]
        proxied = {"x-forwarded-proto": "https", "x-forwarded-for": "203.0.113.77",
                   "host": "studybible-mcp.fly.dev"}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            for method, path in [("GET", "/health/"), ("GET", "/sse/"), ("POST", "/messages/")]:
                response = await client.request(method, path, headers=proxied)
                assert response.status_code == 307, path
                assert response.headers["location"].startswith("https://studybible-mcp.fly.dev/")
            mcp = {**proxied, "accept": "application/json, text/event-stream"}
            bare = await client.post("/mcp", json=INITIALIZE, headers=mcp)
            slash = await client.post("/mcp/", json=INITIALIZE, headers=mcp)
        assert bare.status_code == slash.status_code == 200
        assert bare.text == slash.text
    finally:
        runner.should_exit = True
        await task


async def test_mcp_refuses_get_streams_so_idle_clients_hold_no_connection():
    app = server.build_http_app()
    async with app.app.router.lifespan_context(app.app), _client(app) as client:
        for path in ("/mcp", "/mcp/"):
            response = await client.get(path, headers={"accept": "text/event-stream"})
            assert response.status_code == 405, path
            assert response.headers["allow"] == "POST, DELETE"
