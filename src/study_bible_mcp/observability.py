"""Operational logging for the HTTP server.

Fly keeps only minutes of `fly logs`, so the server also writes a small
rotating file on its volume (``/data/logs/server.log``, 5 MB x 4 files). Lines
are compact, one per event:

    2026-10-15T09:12:03Z INFO tool: word_study ok 312ms out=2856 strongs="H2617" client=160.79.104.*~3fa1c2
    2026-10-15T09:12:03Z WARNING tool: find_similar_passages ok 2290ms out=2197 reference="Isaiah 53:5" client=... SLOW
    2026-10-15T09:12:03Z INFO http: POST /mcp/ 200 318ms rpc=tools/call client=160.79.104.*~3fa1c2 ua=claude-code/2.0.14
    2026-10-15T09:12:03Z INFO sse: open sid=1a2b3c4d client=... ua=...
    2026-10-15T09:12:03Z WARNING sse: stale sid=deadbeef status=404 client=... ua=...

A client is never logged by full IP address: ``client_tag`` keeps the IPv4
/24 (IPv6 /48) and adds a keyed hash of the full address that changes each UTC
day, so one day's lines can be counted per client but not traced back.

Records go through a queue to a listener thread, which does the console and
file I/O, so logging never waits on a disk or pipe in the event loop.
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import hmac
import ipaddress
import json
import logging
import logging.handlers
import os
import queue
import re
import secrets
import sys
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

LOG_FILE_NAME = "server.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# A tool call at least this slow is logged at WARNING.
SLOW_CALL_SECONDS = 2.0
# An argument value is cut to this many characters, the whole summary to TOTAL.
ARGUMENT_CHARS = 40
ARGUMENT_TOTAL_CHARS = 160
USER_AGENT_CHARS = 48

logger = logging.getLogger("study-bible-mcp")
tool_log = logging.getLogger("tool")
http_log = logging.getLogger("http")
sse_log = logging.getLogger("sse")

# The client of the request being served, set by RequestLogMiddleware, so a
# tool call's line names who made it.
current_client: ContextVar[str | None] = ContextVar("current_client", default=None)

# Totals for the shutdown line.
stats = {"calls": 0, "errors": 0, "slow": 0}

_listener: logging.handlers.QueueListener | None = None
_queue_handler: logging.handlers.QueueHandler | None = None
_log_file: Path | None = None
_client_key: bytes = secrets.token_bytes(32)


class _PausingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating file that, when a write fails (a full volume), pauses for a
    while after one console line, instead of a traceback on every record."""

    PAUSE_SECONDS = 300.0
    _paused_until = 0.0

    def emit(self, record):
        if time.monotonic() >= self._paused_until:
            super().emit(record)

    def handleError(self, record):  # noqa: N802 (logging API name)
        self._paused_until = time.monotonic() + self.PAUSE_SECONDS
        sys.stderr.write(
            f"log file write failed ({sys.exc_info()[1]}); "
            f"file logging paused for {self.PAUSE_SECONDS:.0f}s\n"
        )


class _UTCFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 (logging API name)
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))


def _load_client_key(log_dir: Path | None) -> bytes:
    """The key client tags are hashed with: STUDY_BIBLE_LOG_KEY, else a random
    key kept beside the log (so tags survive restarts), else a per-process one."""
    if env := os.environ.get("STUDY_BIBLE_LOG_KEY"):
        return env.encode()
    if log_dir is not None:
        path = log_dir / ".client-key"
        try:
            if path.exists():
                key = path.read_bytes()
                if len(key) >= 16:
                    return key
            key = secrets.token_bytes(32)
            path.write_bytes(key)
            path.chmod(0o600)
            return key
        except OSError:
            pass
    return secrets.token_bytes(32)


def configure_logging(log_dir: Path | None, level: int = logging.INFO) -> Path | None:
    """Log to stderr and, when ``log_dir`` is writable, a rotating file there.

    Returns the log file's path, or None when there is none. Never raises for
    an unusable directory: the server runs on with console logging only.
    """
    global _listener, _queue_handler, _log_file, _client_key
    stop_logging()
    formatter = _UTCFormatter(LOG_FORMAT)
    console = logging.StreamHandler(sys.stderr)  # stdout is the stdio transport's channel
    handlers: list[logging.Handler] = [console]
    file_error = None
    _log_file = None
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = _PausingFileHandler(
                log_dir / LOG_FILE_NAME, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                encoding="utf-8",
            )
            handlers.append(file_handler)
            _log_file = log_dir / LOG_FILE_NAME
        except OSError as e:
            file_error = e
    for handler in handlers:
        handler.setFormatter(formatter)
    _client_key = _load_client_key(log_dir if _log_file else None)

    root = logging.getLogger()
    # Replace basicConfig's console handler (other handlers, such as pytest's, stay).
    for handler in list(root.handlers):
        if type(handler) is logging.StreamHandler:
            root.removeHandler(handler)
    records: queue.SimpleQueue = queue.SimpleQueue()
    _queue_handler = logging.handlers.QueueHandler(records)
    root.addHandler(_queue_handler)
    root.setLevel(level)
    _listener = logging.handlers.QueueListener(records, *handlers, respect_handler_level=True)
    _listener.start()

    # The SDK logs every request at INFO, and every refused one (unknown SSE
    # session, bad Content-Type) at WARNING; RequestLogMiddleware logs those
    # responses itself, compactly and rate-limited.
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger("mcp.server.sse").setLevel(logging.ERROR)
    logging.getLogger("mcp.server.transport_security").setLevel(logging.ERROR)
    _install_exception_hooks()
    if file_error is not None:
        logger.warning(f"log file unavailable in {log_dir} ({file_error}); logging to console only")
    return _log_file


def stop_logging() -> None:
    """Flush queued records to their handlers and detach the queue."""
    global _listener, _queue_handler
    if _listener is not None:
        _listener.stop()  # handles every record queued so far
        for handler in _listener.handlers:
            handler.close()
        _listener = None
    if _queue_handler is not None:
        logging.getLogger().removeHandler(_queue_handler)
        _queue_handler = None


atexit.register(stop_logging)


def log_file() -> Path | None:
    return _log_file


_hooks_installed = False


def _install_exception_hooks() -> None:
    """Log uncaught exceptions (main and other threads) with their tracebacks."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    previous = sys.excepthook

    def excepthook(kind, value, traceback):
        if not issubclass(kind, KeyboardInterrupt):
            logger.critical("unhandled exception", exc_info=(kind, value, traceback))
            stop_logging()
        previous(kind, value, traceback)

    def thread_excepthook(args):
        logger.error(
            f"unhandled exception in thread {args.thread.name if args.thread else '?'}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook


# =========================================================================
# Clients and arguments
# =========================================================================

def client_tag(ip: str | None) -> str:
    """A client's network, truncated, plus a daily keyed hash of its full address.

    '160.79.104.12' -> '160.79.104.*~3fa1c2'; IPv6 keeps its /48.
    """
    if not ip:
        return "-"
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return "?"
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.version == 4:
        network = ".".join(str(address).split(".")[:3]) + ".*"
    else:
        network = ":".join(group.lstrip("0") or "0" for group in address.exploded.split(":")[:3]) + ":*"
    day = time.strftime("%Y-%m-%d", time.gmtime())
    digest = hmac.new(_client_key, f"{day}|{address}".encode(), hashlib.sha256).hexdigest()
    return f"{network}~{digest[:6]}"


# The header in which the proxy in front of the server passes the client's
# address: Fly-Client-IP on Fly. A deployment behind another proxy names that
# proxy's header instead. It must be one the proxy always sets, replacing any
# value the client sent; otherwise a client can choose its own address.
CLIENT_IP_HEADER = os.environ.get("STUDY_BIBLE_CLIENT_IP_HEADER", "Fly-Client-IP").lower()


def request_ip(scope: dict, headers: dict[str, str]) -> str | None:
    """The real client address behind the proxy (see CLIENT_IP_HEADER)."""
    client = scope.get("client")
    return (headers.get(CLIENT_IP_HEADER)
            or (headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (client[0] if client else None))


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _printable(value: str) -> str:
    """One line of text: whitespace runs and control characters become spaces."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())


def summarize_arguments(arguments: dict[str, Any] | None) -> str:
    """Tool arguments as a short ``key=value`` list for a log line.

    Values are cut to ARGUMENT_CHARS, the list to ARGUMENT_TOTAL_CHARS; empty
    values are left out.
    """
    parts = []
    for key, value in (arguments or {}).items():
        if value is None or value == "" or value == []:
            continue
        name = _clip(re.sub(r"\W", "_", str(key)), 24)
        if isinstance(value, str):
            shown = json.dumps(_clip(_printable(value), ARGUMENT_CHARS), ensure_ascii=False)
        elif isinstance(value, (list, tuple)):
            shown = _clip(_printable(",".join(str(item) for item in value)), ARGUMENT_CHARS)
        else:
            shown = _clip(_printable(str(value)), ARGUMENT_CHARS)
        parts.append(f"{name}={shown}")
    return _clip(" ".join(parts), ARGUMENT_TOTAL_CHARS)


def log_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    seconds: float,
    out_chars: int,
    outcome: str,
    wait: float = 0.0,
    exc_info: BaseException | None = None,
) -> None:
    """One line per tool call: outcome, duration, output size, arguments, client."""
    stats["calls"] += 1
    slow = seconds >= SLOW_CALL_SECONDS
    if outcome == "error":
        stats["errors"] += 1
        level = logging.ERROR
    elif slow:
        stats["slow"] += 1
        level = logging.WARNING
    else:
        level = logging.INFO
    parts = [_clip(_printable(name), 40), outcome, f"{seconds * 1000:.0f}ms", f"out={out_chars}"]
    if wait >= 0.05:
        parts.append(f"wait={wait * 1000:.0f}ms")
    if summary := summarize_arguments(arguments):
        parts.append(summary)
    if client := current_client.get():
        parts.append(f"client={client}")
    if slow:
        parts.append("SLOW")
    tool_log.log(level, " ".join(parts), exc_info=exc_info)


# =========================================================================
# Requests
# =========================================================================

_RPC_METHOD = re.compile(rb'"method"\s*:\s*"([^"]{1,64})"')
_SESSION_ID = re.compile(rb"session_id=([0-9a-f]{32})")


class _Repeats:
    """Rate-limits a repeated event: the first is logged, then one count per period."""

    PERIOD = 600.0
    MAX_KEYS = 1024

    def __init__(self):
        self._seen: dict[Any, list[float]] = {}  # key -> [unlogged count, last log, last seen]

    def hit(self, key) -> tuple[bool, int, float]:
        """(log now?, repeats since the last line, seconds since it) for one occurrence."""
        now = time.monotonic()
        entry = self._seen.get(key)
        if entry is None:
            if len(self._seen) >= self.MAX_KEYS:
                self._prune(now)
            self._seen[key] = [0, now, now]
            return True, 0, 0.0
        entry[2] = now
        entry[0] += 1
        if now - entry[1] >= self.PERIOD:
            count, since = int(entry[0]), now - entry[1]
            entry[0], entry[1] = 0, now
            return True, count, since
        return False, 0, 0.0

    def _prune(self, now: float) -> None:
        for key in [k for k, (_, _, seen) in self._seen.items() if now - seen > 3600]:
            del self._seen[key]
        while len(self._seen) >= self.MAX_KEYS:
            del self._seen[next(iter(self._seen))]


class RequestLogMiddleware:
    """ASGI middleware logging each request in one compact line.

    - /health and /static/ are not logged (health checks every 30 s; the
      rate limiter already counts icon requests).
    - GET /sse logs ``sse: open sid=...`` once the stream names its session
      and ``sse: close sid=...`` (duration, POSTs taken) when it ends.
    - POST /messages is logged only when refused: a POST to an unknown
      session logs ``sse: stale sid=...`` the first time per session id, then
      at most one count per 10 minutes, so a stale poller cannot flood the log.
    - Other 4xx responses are rate-limited the same way per client and path.
    - Everything else logs ``http: METHOD path status duration`` with the
      JSON-RPC method of a POST body, the client tag and user agent, and
      ``idle=`` when the server had no request for 5 minutes (a resume).
    """

    IDLE_NOTE_SECONDS = 300

    def __init__(self, app):
        self.app = app
        self._sessions: dict[str, dict] = {}  # SSE session id -> {"opened", "posts"}
        self._repeats = _Repeats()
        self._last_request: float | None = None

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or path == "/health" or path.startswith("/static/"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        client = client_tag(request_ip(scope, headers))
        user_agent = _clip(_printable(headers.get("user-agent", "-")), USER_AGENT_CHARS)
        method = scope.get("method", "?")
        start = time.monotonic()
        wall = time.time()
        idle = wall - self._last_request if self._last_request is not None else None
        self._last_request = wall
        status: int | None = None
        rpc: str | None = None
        stream_id: str | None = None

        async def logged_receive():
            nonlocal rpc
            message = await receive()
            if rpc is None and message["type"] == "http.request":
                found = _RPC_METHOD.search(message.get("body", b"")[:4096])
                rpc = found.group(1).decode("utf-8", "replace") if found else ""
            return message

        async def logged_send(message):
            nonlocal status, stream_id
            if message["type"] == "http.response.start":
                status = message["status"]
            elif path == "/sse" and stream_id is None and message["type"] == "http.response.body":
                found = _SESSION_ID.search(message.get("body", b""))
                if found:
                    stream_id = found.group(1).decode()
                    self._sessions[stream_id] = {"opened": time.monotonic(), "posts": 0}
                    sse_log.info(f"open sid={stream_id[:8]} client={client} ua={user_agent}")
            await send(message)

        token = current_client.set(client)
        failure: BaseException | None = None
        try:
            await self.app(scope, logged_receive, logged_send)
        except BaseException as e:
            failure = e
            raise
        finally:
            current_client.reset(token)
            elapsed = time.monotonic() - start
            try:
                self._log(scope, method, path, status, elapsed, rpc, stream_id, client,
                          user_agent, idle, failure)
            except Exception:  # never let logging break a response
                logger.exception("request logging failed")

    def _log(self, scope, method, path, status, elapsed, rpc, stream_id, client,
             user_agent, idle, failure) -> None:
        if stream_id is not None:
            session = self._sessions.pop(stream_id, {})
            sse_log.info(
                f"close sid={stream_id[:8]} {elapsed:.0f}s posts={session.get('posts', 0)} "
                f"client={client}"
            )
            return
        if path == "/messages" and failure is None and status is not None and status < 500:
            session_id = (parse_qs(scope.get("query_string", b"").decode("latin-1"))
                          .get("session_id", [""])[0])
            if 200 <= status < 300:
                if session_id in self._sessions:
                    self._sessions[session_id]["posts"] += 1
                return
            if status == 404:
                self._repeated(("stale", session_id), "stale", f"sid={session_id[:8]}",
                               status, client, user_agent, sse_log)
                return
            if status != 429:
                self._repeated(("bad", status, client), "bad-session", f"sid={session_id[:8] or '-'}",
                               status, client, user_agent, sse_log)
                return
        shown_path = _clip(_printable(path), 80)
        if failure is None and status is not None and 400 <= status < 500 and status != 429:
            self._repeated(("4xx", method, shown_path, status, client), "refused",
                           f"{method} {shown_path}", status, client, user_agent, http_log)
            return
        parts = [method, shown_path,
                 str(status) if status is not None else "-", f"{elapsed * 1000:.0f}ms"]
        if rpc:
            parts.append(f"rpc={_clip(_printable(rpc), 40)}")
        if idle is not None and idle >= self.IDLE_NOTE_SECONDS:
            parts.append(f"idle={idle:.0f}s")
        parts += [f"client={client}", f"ua={user_agent}"]
        if failure is not None:
            kind = type(failure).__name__
            if isinstance(failure, Exception):
                parts.append(f"FAILED {kind}: {_clip(_printable(str(failure)), 120)}")
                http_log.error(" ".join(parts))
            else:  # cancelled: the client went away or the server is stopping
                parts.append(f"ended by {kind}")
                http_log.info(" ".join(parts))
        elif status is not None and status >= 500:
            http_log.warning(" ".join(parts))
        else:
            http_log.info(" ".join(parts))

    def _repeated(self, key, label, subject, status, client, user_agent, log) -> None:
        first, count, since = self._repeats.hit(key)
        if not first:
            return
        if count:
            log.info(f"{label} {subject} status={status} repeated {count}x in {since:.0f}s")
        else:
            log.warning(f"{label} {subject} status={status} client={client} ua={user_agent}")


# =========================================================================
# Process
# =========================================================================

async def watch_event_loop(interval: float = 5.0, stall: float = 1.0, jump: float = 30.0) -> None:
    """Log when a timer fires late (a blocked event loop, or a machine that was
    suspended and resumed) and when the wall clock jumps against the monotonic one."""
    mono, wall = time.monotonic(), time.time()
    while True:
        await asyncio.sleep(interval)
        now_mono, now_wall = time.monotonic(), time.time()
        late = (now_mono - mono) - interval
        drift = (now_wall - wall) - (now_mono - mono)
        if abs(drift) >= jump:
            logger.warning(
                f"clock jump: wall clock moved {now_wall - wall:+.0f}s in {now_mono - mono:.0f}s "
                "of monotonic time (machine suspended and resumed?)"
            )
        elif late >= jump:
            logger.warning(
                f"timer fired {late:.0f}s late (machine suspended and resumed, or loop blocked)"
            )
        elif late >= stall:
            logger.warning(f"event loop stalled: a {interval:.0f}s timer fired {late:.1f}s late")
        mono, wall = now_mono, now_wall
