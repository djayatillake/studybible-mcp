#!/usr/bin/env bash
# Load an HTML file onto the macOS clipboard as text/html, so a normal Cmd+V pastes
# formatted content (headings, blockquotes, <sup>, bold, Greek/Hebrew) into Substack's
# editor. Pairs with: click into the body, then `computer key cmd+v`.
#
# Usage: clip_html.sh FILE.html
set -euo pipefail
f="${1:?usage: clip_html.sh FILE.html}"
[ -f "$f" ] || { echo "no such file: $f" >&2; exit 1; }
HEX=$(xxd -p "$f" | tr -d '\n')
osascript -e "set the clipboard to «data HTML${HEX}»"
echo "clipboard <- $f ($(wc -c < "$f" | tr -d ' ') bytes as text/html)"
