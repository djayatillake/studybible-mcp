#!/usr/bin/env bash
# Upload the local study_bible.db to Fly.io (studybible-mcp app) without ever
# leaving production without a database.
#
#   gzip -> check free space -> sftp upload under a temp name -> gunzip to a
#   temp name -> verify size + sha256 -> atomic mv over the live DB -> restart
#
# Run scripts/upgrade_database.py on the local file before uploading.
# Run this from your own terminal: Claude Code's permission rules block the
# sftp upload and remote writes. For small changes, prefer patching in place
# (.claude/commands/deploy-db.md, Step 4a).
#
# Usage:
#   scripts/upload-db.sh              # upload db/study_bible.db
#   scripts/upload-db.sh path/to.db   # upload a specific file

set -euo pipefail

APP="studybible-mcp"
LOCAL_DB="${1:-db/study_bible.db}"
REMOTE_PATH="/data/study_bible.db"
REMOTE_NEW="${REMOTE_PATH}.new"
TMP_GZ="/tmp/study_bible.db.gz"

trap 'rm -f "$TMP_GZ"' EXIT

if [[ ! -f "$LOCAL_DB" ]]; then
    echo "Error: $LOCAL_DB not found" >&2
    exit 1
fi

file_size() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1"; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
remote() { fly ssh console -a "$APP" -C "sh -c '$1'"; }

local_size=$(file_size "$LOCAL_DB")
local_sha=$(sha256 "$LOCAL_DB")
echo "Local DB: $LOCAL_DB ($(( local_size / 1048576 )) MB, sha256 $local_sha)"

# 1. Compress
echo "Compressing..."
gzip -c "$LOCAL_DB" > "$TMP_GZ"
gz_size=$(file_size "$TMP_GZ")
echo "  Compressed: $(( gz_size / 1048576 )) MB"

# 2. Check free space: the live DB stays while the upload and the
#    decompressed replacement are both on the volume.
needed_kb=$(( (local_size + gz_size) / 1024 + 51200 ))
free_kb=$(remote "df -Pk /data | tail -1" | tr -d '\r' | awk '{print $4}')
echo "  Volume free: $(( free_kb / 1024 )) MB, needed: $(( needed_kb / 1024 )) MB"
if (( free_kb < needed_kb )); then
    echo "Error: not enough space on /data. Extending the volume is irreversible" >&2
    echo "(volumes never shrink) and adds to the bill; if you accept that:" >&2
    echo "  fly volumes list -a $APP" >&2
    echo "  fly volumes extend <volume-id> --size <GB> -a $APP" >&2
    exit 1
fi

# 3. Upload alongside the live DB
echo "Uploading compressed DB..."
remote "rm -f ${REMOTE_NEW} ${REMOTE_NEW}.gz"
echo "put $TMP_GZ ${REMOTE_NEW}.gz" | fly ssh sftp shell -a "$APP"

# 4. Decompress to a temporary name
echo "Decompressing on server..."
remote "gzip -dc ${REMOTE_NEW}.gz > ${REMOTE_NEW} && rm -f ${REMOTE_NEW}.gz"

# 5. Verify size and checksum before touching the live DB
echo "Verifying..."
remote_size=$(remote "stat -c%s ${REMOTE_NEW}" | tr -d '\r')
remote_sha=$(remote "sha256sum ${REMOTE_NEW}" | tr -d '\r' | cut -d' ' -f1)
if [[ "$remote_size" != "$local_size" || "$remote_sha" != "$local_sha" ]]; then
    echo "Error: uploaded file mismatch (size $remote_size, sha256 $remote_sha); live DB untouched." >&2
    remote "rm -f ${REMOTE_NEW}"
    exit 1
fi

# 6. Atomic swap (same filesystem rename). The database runs in WAL mode: an
#    old -wal/-shm left beside the new file would be replayed onto it at the
#    next open and corrupt it, so remove them in the same step. The running
#    server keeps its handles on the old inode until the restart.
echo "Replacing live DB..."
remote "mv ${REMOTE_NEW} ${REMOTE_PATH} && rm -f ${REMOTE_PATH}-wal ${REMOTE_PATH}-shm"

# 7. Restart
echo "Restarting app..."
fly apps restart "$APP"

echo "Done. Verify with: curl -s https://${APP}.fly.dev/health | python3 -m json.tool"
