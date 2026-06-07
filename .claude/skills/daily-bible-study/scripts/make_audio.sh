#!/usr/bin/env bash
# Render the day's voiceover: raw-json (direct, preserves <sup>/glyphs) -> clean ->
# validate (0 glyphs / 0 Strong's) -> Kokoro build. Run from the repo root.
# Best run in the background (build is ~8-9 min for a ~43-min episode).
#
# Usage:
#   make_audio.sh --html podcast/dayN/Bible_in_a_Year_Study_DayN.html --work podcast/dayN \
#       --title "Day N · …" --subtitle "Passage · Passage" --date YYYY-MM-DD [--voice bm_george]
set -euo pipefail

HTML="" WORK="" TITLE="" SUBTITLE="" DATE="" VOICE="bm_george"
while [ $# -gt 0 ]; do
  case "$1" in
    --html) HTML="$2"; shift 2;;
    --work) WORK="$2"; shift 2;;
    --title) TITLE="$2"; shift 2;;
    --subtitle) SUBTITLE="$2"; shift 2;;
    --date) DATE="$2"; shift 2;;
    --voice) VOICE="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
: "${HTML:?--html required}" "${WORK:?--work required}" "${TITLE:?--title required}"

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SUB="$HOME/.claude/skills/substack-podcast/scripts"
PY=".venv-tts/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found — run from the repo root (/Users/david/studybible-mcp)." >&2; exit 1; }
[ -f "$SUB/clean.py" ] || { echo "ERROR: substack-podcast skill not found at $SUB" >&2; exit 1; }

echo "== build raw json (direct) =="
"$PY" "$SKILL_DIR/scripts/make_audio_input.py" --html "$HTML" --work "$WORK" \
      --title "$TITLE" --subtitle "$SUBTITLE" --date "$DATE"

echo "== clean =="
"$PY" "$SUB/clean.py" --work "$WORK"

echo "== validate =="
T=$(ls "$WORK"/text/*.txt | head -1)
G=$(grep -oE '[֐-׿Ͱ-Ͽἀ-῿]' "$T" | wc -l | tr -d ' ' || true)
S=$(grep -oE '\b[HG][0-9]{2,5}\b' "$T" | wc -l | tr -d ' ' || true)
echo "glyphs=$G strongs=$S  (both must be 0)"
[ "$G" = 0 ] && [ "$S" = 0 ] || { echo "VALIDATION FAILED — fix the HTML before building." >&2; exit 1; }

echo "== build audio (Kokoro, voice=$VOICE) =="
PYTHONPATH="$SUB" "$PY" "$SUB/build.py" --work "$WORK" --voice "$VOICE"

echo "== artifacts =="
ls -la "$WORK"/audio/
for f in "$WORK"/audio/*.mp3; do
  echo "$f -> $(ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$f" 2>/dev/null)s, $(du -h "$f" | cut -f1)"
done
