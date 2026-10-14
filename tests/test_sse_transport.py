"""The legacy SSE transport answers its routes without raising.

SseServerTransport's handlers send their own responses and return None. Routed
as request -> response endpoints, Starlette called that None, so every POST to
/messages (in production, a stale client posting to a dead session about once a
second) and every SSE disconnect logged a TypeError traceback.
"""

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
