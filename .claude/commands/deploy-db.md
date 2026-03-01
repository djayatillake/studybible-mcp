# Deploy Database to Fly

This skill manages the study_bible.db database deployment lifecycle: download from Fly, local editing, then delete + re-upload to Fly.

## Database Overview

- **Local path**: `db/study_bible.db` (~617MB with embeddings)
- **Remote path**: `/data/study_bible.db` on Fly volume (app: `studybible-mcp`)
- **Environment variable**: `STUDY_BIBLE_DB=/data/study_bible.db`
- The database is mounted via Fly.io persistent volume, NOT baked into the Docker image
- The code (tools.py, server.py, parsers) is deployed separately via `fly deploy`

## Step 1: Download from Fly (if needed)

If the local `db/study_bible.db` is stale or missing, download from the running Fly instance:

```bash
curl -o db/study_bible.db https://studybible-mcp.fly.dev/download/study_bible.db
```

This uses the `/download/study_bible.db` endpoint built into the server.

## Step 2: Make Local Changes

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

## Step 3: Upload to Fly

The database is too large (~617MB) for reliable raw sftp transfer. Always compress first:

```bash
# 1. Compress locally
gzip -c db/study_bible.db > /tmp/study_bible.db.gz

# 2. Remove old DB from Fly
fly ssh console -a studybible-mcp -C "rm -f /data/study_bible.db" 2>/dev/null

# 3. Upload compressed file
echo "put /tmp/study_bible.db.gz /data/study_bible.db.gz" | fly ssh sftp shell -a studybible-mcp 2>/dev/null

# 4. Decompress on server
fly ssh console -a studybible-mcp -C "gzip -d /data/study_bible.db.gz" 2>/dev/null

# 5. Verify size matches local (should be ~617MB)
fly ssh console -a studybible-mcp -C "ls -la /data/study_bible.db" 2>/dev/null

# 6. Restart app to pick up new DB
fly apps restart studybible-mcp 2>/dev/null

# 7. Clean up
rm -f /tmp/study_bible.db.gz
```

## Step 4: Verify

```bash
# Health check
curl -s https://studybible-mcp.fly.dev/health | python3 -m json.tool

# Verify entry count (download small portion and check)
# The health endpoint confirms database_exists: true
```

## Code Deployment (separate from DB)

When only code changes (tools.py, server.py, parsers, system_prompt) — no DB changes:

```bash
fly deploy
```

This rebuilds the Docker image and deploys. The persistent volume with the DB is NOT affected.

## Important Notes

- **NEVER use raw sftp for the full 617MB file** — it silently truncates, producing a corrupt DB
- **Always gzip → upload → gunzip** for reliable transfer
- The Fly volume has ~1GB. The compressed file (~250MB) + decompressed file (~617MB) = ~870MB fits, but `gzip -d` does in-place decompression so it only needs ~617MB at peak
- If you change both code AND data, do `fly deploy` first (for code), then upload DB (for data), then restart
- The download endpoint (`/download/study_bible.db`) serves the file from the running instance
