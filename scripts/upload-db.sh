#!/usr/bin/env bash
# Upload the local study_bible.db to Fly.io (studybible-mcp app).
#
# Wraps the 7-step manual process:
#   gzip -> remove old -> sftp upload -> gunzip -> verify -> restart -> cleanup
#
# Usage:
#   scripts/upload-db.sh              # upload db/study_bible.db
#   scripts/upload-db.sh path/to.db   # upload a specific file

set -euo pipefail

APP="studybible-mcp"
LOCAL_DB="${1:-db/study_bible.db}"
REMOTE_PATH="/data/study_bible.db"
TMP_GZ="/tmp/study_bible.db.gz"

trap 'rm -f "$TMP_GZ"' EXIT

if [[ ! -f "$LOCAL_DB" ]]; then
    echo "Error: $LOCAL_DB not found" >&2
    exit 1
fi

local_size=$(stat -f%z "$LOCAL_DB" 2>/dev/null || stat -c%s "$LOCAL_DB" 2>/dev/null)
echo "Local DB: $LOCAL_DB ($(( local_size / 1048576 )) MB)"

# 1. Compress
echo "Compressing..."
gzip -c "$LOCAL_DB" > "$TMP_GZ"
gz_size=$(stat -f%z "$TMP_GZ" 2>/dev/null || stat -c%s "$TMP_GZ" 2>/dev/null)
echo "  Compressed: $(( gz_size / 1048576 )) MB"

# 2. Remove old DB on Fly
echo "Removing old DB on Fly..."
fly ssh console -a "$APP" -C "rm -f $REMOTE_PATH" || true

# 3. Upload compressed file
echo "Uploading compressed DB..."
echo "put $TMP_GZ ${REMOTE_PATH}.gz" | fly ssh sftp shell -a "$APP"

# 4. Decompress on server
echo "Decompressing on server..."
fly ssh console -a "$APP" -C "gzip -d ${REMOTE_PATH}.gz"

# 5. Verify
echo "Verifying..."
fly ssh console -a "$APP" -C "ls -la $REMOTE_PATH"

# 6. Restart
echo "Restarting app..."
fly apps restart "$APP"

echo "Done. Verify with: curl -s https://${APP}.fly.dev/health | python3 -m json.tool"
