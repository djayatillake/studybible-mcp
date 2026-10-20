"""Rate limiting: the client address comes from the configured proxy header; idle addresses are forgotten."""

from study_bible_mcp import observability, server
from study_bible_mcp.observability import request_ip


def test_request_ip_uses_the_configured_proxy_header(monkeypatch):
    scope = {"client": ("127.0.0.1", 5000)}
    headers = {"fly-client-ip": "198.51.100.1", "x-forwarded-for": "198.51.100.2",
               "x-proxy-client": "203.0.113.9"}
    assert request_ip(scope, headers) == "198.51.100.1"  # Fly-Client-IP by default
    monkeypatch.setattr(observability, "CLIENT_IP_HEADER", "x-proxy-client")
    assert request_ip(scope, headers) == "203.0.113.9"
    assert request_ip(scope, {"x-forwarded-for": "198.51.100.2, 203.0.113.9"}) == "198.51.100.2"
    assert request_ip(scope, {}) == "127.0.0.1"


def test_rate_limiter_forgets_idle_addresses():
    limiter = server.RateLimitMiddleware(app=None, window_seconds=60)
    limiter._requests["old"] = [100.0]
    limiter._requests["new"] = [200.0]
    limiter._limited_logged["old"] = 100.0
    limiter._sweep(window_start=150.0)
    assert dict(limiter._requests) == {"new": [200.0]}
    assert limiter._limited_logged == {}
    assert limiter._requests["unseen"] == []  # still a defaultdict
