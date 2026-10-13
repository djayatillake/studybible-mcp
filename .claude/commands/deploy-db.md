# Deploy Database to Fly

This skill manages the study_bible.db database deployment lifecycle: download from Fly, upgrade and edit locally, then upload alongside the live database and swap it in atomically. Production must never be left without a database.

## Database Overview

- **Local path**: `db/study_bible.db` (~680MB before the evidence/LXX/Josephus upgrade, ~750MB after)
- **Remote path**: `/data/study_bible.db` on Fly volume (app: `studybible-mcp`)
- **Environment variable**: `STUDY_BIBLE_DB=/data/study_bible.db`
- The database is mounted via Fly.io persistent volume, NOT baked into the Docker image
- The code (tools.py, server.py, parsers) is deployed separately via `fly deploy`

## Running This From Claude Code

- `fly` reports `No access token available` inside Claude Code even when
  `~/.fly/config.yml` holds a valid token. Export it in the same command and run
  with the sandbox disabled:
  `export FLY_API_TOKEN=$(awk '/access_token:/{print $2}' ~/.fly/config.yml) && fly ...`
  Never `cat` or `head` that file: it prints the token into the transcript.
- Read-only steps (`fly status`, `fly deploy`, the health and endpoint checks)
  work from Claude Code. Writes to the production volume do not: Claude Code's
  permission rules block the sftp upload and `fly ssh console` commands that
  change `/data`. Claude prepares those commands (or the patch script below);
  the user runs them from their own terminal.

## Step 1: Download from Fly (if needed)

If the local `db/study_bible.db` is stale or missing, download from the running Fly instance:

```bash
curl -o db/study_bible.db https://studybible-mcp.fly.dev/download/study_bible.db
```

This uses the `/download/study_bible.db` endpoint built into the server.

## Step 2: Upgrade the Schema and Sources

Always run the in-place upgrade after downloading and before uploading:

```bash
.venv/bin/python3 scripts/upgrade_database.py --database db/study_bible.db
```

It downloads the pinned LXX/Brenton and Josephus sources (files already present
are skipped; every file is checksum-verified), migrates the legacy textual-variant
tables, imports MT/LXX, Josephus, and the bundled variant cases, then runs
`PRAGMA integrity_check` and `PRAGMA foreign_key_check` on a temporary copy. The
original file is replaced only if every step succeeds, and re-running it is safe.
Use `--offline` when the sources are already under `data/`.

## Step 3: Make Other Local Changes (optional)

ANE context data lives in `data/ane_context/*.json` (13 dimension files). To re-import after editing:

```bash
# Clear old ANE data
sqlite3 db/study_bible.db "DELETE FROM ane_book_mappings; DELETE FROM ane_entries;"

# Re-import from JSON files
.venv/bin/python3 -c "
import sqlite3
from pathlib import Path
from scripts.build_database import import_ane_context
conn = sqlite3.connect('db/study_bible.db')
import_ane_context(conn, Path('data/ane_context'))
conn.close()
"
```

For a full database rebuild (all data, not just ANE):
```bash
.venv/bin/python3 scripts/build_database.py
```

## Step 4a: Small Data Changes — Patch in Place (preferred)

When only a few rows change (corrected URLs, deduplicated links, a data fix),
apply the change to the live database directly instead of uploading 700MB. It
cannot overwrite changes that exist only on the server, and it needs no extra
volume space or restart (the server opens the file with an ordinary connection).

1. Write a Python script that makes the change in one transaction, matching rows
   by natural key rather than id, and rolls back and exits non-zero if any
   update does not hit exactly the expected rows. Test it on a copy of the local
   database rolled back to the production state, and run it twice to confirm
   it is idempotent.
2. Compress and base64-encode it (`fly ssh console` has no stdin, and the
   image ships only `src/`, not `scripts/`):

```bash
python3 -c "import base64,zlib,sys;print(base64.b64encode(zlib.compress(open(sys.argv[1],'rb').read(),9)).decode())" patch.py > patch.b64
```

3. Run it on the server (from the user's terminal):

```bash
fly ssh console -a studybible-mcp -C "python -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('$(cat patch.b64)')))\""
```

4. Check the live endpoint (Step 5).

The database runs in WAL mode and the server keeps it open, so a patch's changes
stay in `/data/study_bible.db-wal` until SQLite checkpoints them. Anything that
copies or replaces the raw `/data/study_bible.db` must allow for that: the
Step 1 download serves the file without the WAL's changes, and replacing the file
while a stale `-wal`/`-shm` remains beside it corrupts the new file at its next
open (Step 4b removes them in the same step as the swap).

## Step 4b: Upload the Whole Database

Use this when the change is too large to patch, e.g. after
`scripts/upgrade_database.py` adds new corpora. Run it from your own terminal.
`scripts/upload-db.sh` automates this step. The manual sequence is below. The live
database stays in place until the verified replacement is moved over it.

```bash
# 1. Compress locally and record the checksum of the uncompressed file
gzip -c db/study_bible.db > /tmp/study_bible.db.gz
sha256sum db/study_bible.db
ls -l db/study_bible.db /tmp/study_bible.db.gz

# 2. Check free space on the volume. /data must hold the live DB, the
#    compressed upload, and the decompressed replacement at the same time.
fly ssh console -a studybible-mcp -C "df -h /data"
fly ssh console -a studybible-mcp -C "ls -l /data"

# 3. Upload alongside the live DB under a temporary name
echo "put /tmp/study_bible.db.gz /data/study_bible.db.new.gz" | fly ssh sftp shell -a studybible-mcp

# 4. Decompress to a temporary name and remove the compressed copy
fly ssh console -a studybible-mcp -C "sh -c 'gzip -dc /data/study_bible.db.new.gz > /data/study_bible.db.new && rm /data/study_bible.db.new.gz'"

# 5. Verify size and checksum match the local values from step 1
fly ssh console -a studybible-mcp -C "ls -l /data/study_bible.db.new"
fly ssh console -a studybible-mcp -C "sha256sum /data/study_bible.db.new"

# 6. Atomically replace the live DB (same filesystem, so mv is a rename) and
#    remove the old WAL files: the DB runs in WAL mode, and a stale -wal left
#    beside the new file is replayed onto it at the next open, corrupting it.
fly ssh console -a studybible-mcp -C "sh -c 'mv /data/study_bible.db.new /data/study_bible.db && rm -f /data/study_bible.db-wal /data/study_bible.db-shm'"

# 7. Restart app to pick up new DB (frees the old file's space)
fly apps restart studybible-mcp

# 8. Clean up
rm -f /tmp/study_bible.db.gz
```

If step 5 shows a mismatch, delete `/data/study_bible.db.new` and repeat from
step 3; the live database is untouched.

### If the volume is too small

The upgraded database (~750MB) plus the live one (~680MB) and the compressed
upload (~300MB) need about 1.75GB. The `studybible_data` volume is 2GB (check
with `fly volumes list -a studybible-mcp`), which fits with little margin. If
`df` shows less free space than the compressed plus uncompressed sizes, the
volume has to be extended first.

**Get the user's explicit go-ahead before extending.** It cannot be undone
(volumes grow but never shrink), it adds to the monthly bill, and the machine
may restart. State the current and new size when asking.

```bash
fly volumes list -a studybible-mcp
fly volumes extend <volume-id> --size 3 -a studybible-mcp
fly ssh console -a studybible-mcp -C "df -h /data"
```

Never free space by deleting the live `/data/study_bible.db`.

## Step 5: Verify

```bash
# Health check
curl -s https://studybible-mcp.fly.dev/health | python3 -m json.tool

# Exercise every tool against the local copy you uploaded
.venv/bin/python3 scripts/smoke_server.py --db db/study_bible.db

# Call a tool on the live server. The endpoint needs the trailing slash:
# POST /mcp without it fails.
curl -s -X POST https://studybible-mcp.fly.dev/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_textual_variant","arguments":{"reference":"Psalm 82:6"}}}' \
  | sed -n 's/^data: //p' | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['content'][0]['text'][:1500])"
```

Check something the change should have altered, not just that the server
answers.

## Code Deployment (separate from DB)

When only code changes (tools.py, server.py, parsers, system_prompt) — no DB changes:

```bash
fly deploy
```

This rebuilds the Docker image and deploys. The persistent volume with the DB is NOT affected.

## Important Notes

- **Order when both code and data change**: `fly deploy` the code first, then upload the database straight away. New code on the old database degrades politely: `get_textual_variant` reports that the database needs upgrading and the newly added tools report missing data. The reverse order is worse: the previous code's `get_textual_variant` reads the dropped legacy table and returns a raw SQL error until the new code is live.
- **NEVER use raw sftp for the full uncompressed file**: it silently truncates and produces a corrupt DB. Always upload the gzip, then decompress on the server and compare the checksum.
- **NEVER delete the live database before the replacement is verified**: upload under a temporary name and `mv` it over the old file.
- The download endpoint (`/download/study_bible.db`) serves the file from the running instance.
