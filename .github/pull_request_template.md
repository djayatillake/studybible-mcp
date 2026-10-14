## Summary

<!-- What changes, and why. If this is stacked on another PR, say which. -->

## Verification

<!-- Tests added or changed; real-data checks (e.g. smoke_server.py against a full database). -->

## Checklist

- [ ] `uv run pytest -q` and `uv run ruff check src tests scripts` pass, and new behaviour has tests (temporary databases, no network)
- [ ] Output size: list tools default to ≤ 4 results; provenance is printed once per response; before/after sizes for typical calls are given above
- [ ] Tool descriptions stay short and static (`tests/test_contracts.py` budget)
- [ ] Non-canonical material is labelled as not Scripture at the point of use (see CONTRIBUTING.md)
- [ ] New data: downloads are pinned and checksummed, and the licence is taken from the source itself
- [ ] Database changes: in-place upgrade is idempotent, existing curated data is untouched, and the deploy order is stated
- [ ] AI assistance disclosed, if any
