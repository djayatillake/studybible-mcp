#!/usr/bin/env python3
"""Check the external links this server hands to agents.

Checks every research-source URL, every research-source search template filled
with a sample query, and, when the database is present, every distinct
theology_content.url. A link is broken when it answers with status >= 400 or a
network error. HEAD is tried first and GET is used when HEAD fails, because some
sites reject HEAD. A timeout is retried once with a longer limit (slow hosts are
not dead ones); a link that still times out is reported as TIMEOUT and fails the
run like a broken link, except on a host in LINK_CHECK_SLOW_HOSTS, which gets an
even longer retry and is only reported as SLOW. A catalogue entry marked
"link_check": "skip" (with a "link_check_reason") is reported as skipped; use it
only for sites that block automated clients.

This makes ~100 requests to third-party sites; run it occasionally, not in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from study_bible_mcp.tools import load_research_sources, research_search_url


LINK_CHECK_SAMPLE_QUERY = "Psalm 82"
LINK_CHECK_CONCURRENCY = 8
LINK_CHECK_TIMEOUT = 20.0
# Some hosts answer in 20-30 s; a timed-out link is retried once with this
# longer limit before it is reported.
LINK_CHECK_RETRY_TIMEOUT = 60.0
# Hosts known to be slow but working (drmsh.com has answered in 31-57 s): their
# retry gets a longer limit, and a timeout that still persists is reported as
# SLOW, a warning that does not fail the run. Matched on the host or a parent.
LINK_CHECK_SLOW_HOSTS = {"drmsh.com": 180.0}
_USER_AGENT = "Mozilla/5.0 (compatible; studybible-mcp link checker; +https://github.com/djayatillake/studybible-mcp)"

# Returns the final HTTP status for a URL; raises httpx.HTTPError on network failure.
Fetcher = Callable[[str], Awaitable[int]]


def _slow_host_limit(url: str) -> float | None:
    """The retry limit for a known-slow host, or None for any other host."""
    host = (httpx.URL(url).host or "").lower()
    for slow, limit in LINK_CHECK_SLOW_HOSTS.items():
        if host == slow or host.endswith(f".{slow}"):
            return limit
    return None


def retry_timeout(url: str) -> float:
    return _slow_host_limit(url) or LINK_CHECK_RETRY_TIMEOUT


@dataclass
class LinkResult:
    url: str
    origins: list[str]
    status: int | None
    error: str | None
    timed_out: bool = False

    @property
    def broken(self) -> bool:
        """Any failure, including a timeout that persisted through the retry."""
        return self.error is not None or self.status is None or self.status >= 400

    @property
    def slow(self) -> bool:
        """A persistent timeout on a host known to be slow but working."""
        return self.timed_out and _slow_host_limit(self.url) is not None

    @property
    def fails_run(self) -> bool:
        return self.broken and not self.slow


def collect_link_targets(db_path: Path | None) -> tuple[dict[str, list[str]], list[str]]:
    """Map each distinct URL to where it came from; also return skipped-entry notes."""
    targets: dict[str, list[str]] = {}
    skipped: list[str] = []
    for source in load_research_sources():
        if source.get("link_check") == "skip":
            skipped.append(f"research_sources:{source['key']} — {source['link_check_reason']}")
            continue
        targets.setdefault(source["url"], []).append(f"research_sources:{source['key']} url")
        search = research_search_url(source, LINK_CHECK_SAMPLE_QUERY)
        if search:
            targets.setdefault(search, []).append(f"research_sources:{source['key']} search")

    if db_path is not None:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT TRIM(url), source_author, GROUP_CONCAT(DISTINCT source_work), COUNT(*) "
                "FROM theology_content WHERE url IS NOT NULL AND TRIM(url) <> '' "
                "GROUP BY TRIM(url), source_author ORDER BY TRIM(url)"
            ).fetchall()
        for url, author, works, count in rows:
            targets.setdefault(url, []).append(f"theology_content:{author} ({works}; {count} rows)")
    return targets, skipped


def make_http_fetcher(
    client: httpx.AsyncClient, timeout_for: Callable[[str], float] | None = None
) -> Fetcher:
    """HEAD first; fall back to a streamed GET when HEAD errors or is refused.

    ``timeout_for`` gives a per-URL timeout; otherwise the client's applies.
    """

    async def fetch(url: str) -> int:
        options = {"timeout": timeout_for(url)} if timeout_for else {}
        try:
            response = await client.head(url, **options)
            if response.status_code < 400:
                return response.status_code
        except httpx.HTTPError:
            pass
        async with client.stream("GET", url, **options) as response:
            return response.status_code

    return fetch


async def check_links(
    targets: dict[str, list[str]],
    fetch: Fetcher,
    concurrency: int = LINK_CHECK_CONCURRENCY,
    retry: Fetcher | None = None,
) -> list[LinkResult]:
    """Fetch every target with bounded concurrency; network errors become broken results.

    A timeout is retried once with ``retry`` (a slower fetcher), so a slow host
    is not reported as broken; a timeout that persists is marked ``timed_out``.
    """
    semaphore = asyncio.Semaphore(concurrency)

    def failed(url: str, origins: list[str], exc: Exception) -> LinkResult:
        return LinkResult(
            url, origins, None, f"{type(exc).__name__}: {exc}".strip(": "),
            timed_out=isinstance(exc, httpx.TimeoutException),
        )

    async def check(url: str, origins: list[str]) -> LinkResult:
        async with semaphore:
            try:
                return LinkResult(url, origins, await fetch(url), None)
            except httpx.TimeoutException as exc:
                if retry is None:
                    return failed(url, origins, exc)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                return failed(url, origins, exc)
            try:
                return LinkResult(url, origins, await retry(url), None)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                return failed(url, origins, exc)

    return list(await asyncio.gather(*(check(url, origins) for url, origins in targets.items())))


async def run_link_check(db_path: Path | None) -> bool:
    if db_path is not None and not db_path.is_file():
        print(f"Database not found: {db_path}; checking the research-source catalogue only")
        db_path = None
    targets, skipped = collect_link_targets(db_path)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # the report below lists every URL
    client_options = {"follow_redirects": True, "headers": {"User-Agent": _USER_AGENT}}
    async with httpx.AsyncClient(timeout=LINK_CHECK_TIMEOUT, **client_options) as client:
        results = await check_links(
            targets,
            make_http_fetcher(client),
            retry=make_http_fetcher(client, timeout_for=retry_timeout),
        )

    failing = [r for r in results if r.fails_run]
    timed_out = [r for r in failing if r.timed_out]
    slow = [r for r in results if r.slow]
    for result in sorted(results, key=lambda r: r.url):
        if result.slow:
            label = "SLOW   "
        elif result.timed_out:
            label = "TIMEOUT"
        else:
            label = "BROKEN " if result.broken else "OK     "
        outcome = result.error or result.status
        print(f"{label} {outcome} {result.url}")
        if result.broken:
            for origin in result.origins:
                print(f"          from {origin}")
    for note in skipped:
        print(f"SKIP    {note}")
    ok = len(results) - len(failing) - len(slow)
    print(f"\n{len(results)} links checked: {ok} ok, "
          f"{len(failing) - len(timed_out)} broken, {len(timed_out)} timed out "
          f"(no response within {LINK_CHECK_RETRY_TIMEOUT:.0f} s on retry), "
          f"{len(slow)} slow (known-slow host, warning only), "
          f"{len(skipped)} catalogue entries skipped")
    return not failing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "db" / "study_bible.db",
        help="study_bible.db whose theology_content URLs are also checked (optional)",
    )
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run_link_check(args.db)) else 1)


if __name__ == "__main__":
    main()
