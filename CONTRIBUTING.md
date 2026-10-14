# Contributing

Thank you for helping. This server feeds an AI agent that prepares evangelical
Protestant Bible studies, so a few rules matter more here than in most projects:
output size, the line between Scripture and other sources, and the provenance of
every dataset. CI checks what it can. The rest is in the pull-request checklist.

## Setup and tests

```bash
uv sync --extra dev --extra sse
uv run pytest -q
uv run ruff check src tests scripts
```

The suite takes about ten seconds. Every test builds its own temporary database.
No test touches the network or the production database. CI runs it on Python
3.10 and 3.11 for every pull request. CI also builds the Docker image and runs
`ruff`, which must pass; `uv run ruff check --fix src tests scripts` fixes most
findings.

`tests/test_contracts.py` checks the rules below that can be checked
automatically: tool annotations, the tool-description budget, default result
limits, smoke-runner coverage and JSON validity. If it fails, read its message
before changing a number in it.

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. The
Docker image installs `requirements.txt`, which is exported from the lock. After
changing a dependency, run `uv lock`, then
`uv export --frozen --no-dev --extra sse --no-emit-project -o requirements.txt`;
a contract test fails while the two differ.

## The full database

The production database is about 800 MB. It is not in git, and it is deployed
separately from the code.

- `scripts/build_database.py` builds the database from scratch.
- `scripts/upgrade_database.py` upgrades an existing database in place. It
  downloads pinned, checksummed sources and imports them.
- `scripts/smoke_server.py --db path/to/study_bible.db` calls every tool against a
  full database. CI cannot run it, so run it locally when you change a tool.
  Every new tool needs a smoke case; a contract test enforces this.
- `scripts/check_links.py` checks the external links the tools hand out. Run it
  occasionally, or start the manual "Link check" workflow.

## Rules every change keeps

1. **Small outputs.** Every tool's description and schema is sent to the model in
   every session, and every result lands in its context.
   - List tools default to at most 4 results.
   - Descriptions are short and static. Do not paste data lists into them.
   - Print provenance, licences and caveats once per response, not on every row.
   - Include before/after output sizes for typical calls in your pull request.
2. **Scripture is kept distinct from everything else.**
   - Material outside the 66-book Protestant canon, including the Apocrypha, says
     so where the agent will quote it:
     - a per-result tag;
     - one caveat per response;
     - ⚠ notes at known problem passages, in
       `src/study_bible_mcp/corpora/editorial_notes.json`.
   - Pseudepigrapha are paired with aligned biblical passages.
   - The ancient-source corpora cover texts up to about AD 200 that witness the
     Second Temple world. Targum Onkelos (final form c. 3rd–5th c. AD) is the
     one stated exception, kept for its earlier tradition and labelled with its
     final-form date. Later material was left out deliberately, so open an
     issue before proposing it.
3. **Data provenance.**
   - Pin downloads to a commit or revision and verify checksums. The build must
     fail on a mismatch.
   - Take licence claims from the source's own statement, not from a third-party
     label, and record NonCommercial or ShareAlike terms.
   - Do not add copyrighted text.
4. **Safe database changes.**
   - A schema or data change must work as an idempotent in-place upgrade of the
     production database, and give the same result as a fresh build.
   - Never drop or silently rewrite curated data: theology entries, translation
     decisions, textual variants.
   - Say whether the current code still works on the upgraded database, because
     that decides the deploy order.
5. **Self-contained tests.**
   - Build test databases in `tmp_path`.
   - Use `httpx.MockTransport` instead of the network.
   - Add a test for each behaviour you add or fix.

## Pull requests

- Keep each pull request to one concern. If you stack pull requests, say so, and
  keep each one reviewable on its own.
- Describe the change: what changed and why, how you verified it (tests and any
  real-data checks), its effect on output size, and deploy notes.
- AI-assisted contributions are welcome; please say so. Reviewers check claims
  against the data.
- Do not commit downloaded source data (`data/lxx/`, `data/ancient_sources/`) or
  database files.
