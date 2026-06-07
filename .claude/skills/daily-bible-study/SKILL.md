---
name: daily-bible-study
description: >-
  Produce the daily "Bible in a Year" study end-to-end: pull the smooth BSB text,
  run the study-bible MCP tools, present the readings, write the post HTML, render
  the Kokoro voiceover, and create a Substack DRAFT (studybible.substack.com). Use
  whenever the user gives the day's passages or says "Day N" / "today's study".
  Runs from the repo root /Users/david/studybible-mcp.
---

# Daily Bible-in-a-Year Study → Substack

David publishes one study per day at **studybible.substack.com** (author: David
Jayatillake). Each post is "Day N · <theme>", subtitle = the passage list, with a
~40-min voiceover. This skill turns *a list of passages* into a finished Substack
draft + audio. **Always run from the repo root** (`/Users/david/studybible-mcp`).
`SKILL_DIR` = the directory containing this file.

Related memory: see `project_substack_workflow.md` and `feedback_context_economy.md`.

---

## The daily flow (3 stages — the user drives the gates)

This is normally done in **three messages**, not one. Don't skip ahead.

1. **Readings** — user gives the day's passages. You pull BSB + run the tools and
   present **Part One** (the readings + the "N threads" list) inline in chat, with
   the **full BSB verses shown inline**. Then stop.
2. **Questions** — user asks follow-up questions; you answer them in chat. These
   become **Part Two — "Questions We Followed."**
3. **Publish** — user says they're ready. You assemble the HTML, render the audio,
   and create the Substack draft for review. User adds the audio + publishes.

You can compress stages if the user asks, but the default is staged.

---

## Step 0 — Establish Day N, date, theme, passages

- **Day N + date**: yesterday's anchor — **Day 8 = Saturday 6 June 2026**. So Day 9 =
  Sun 7 June 2026, etc. Confirm the date from the environment's "Today's date".
- **Passages**: the user supplies them (e.g. "Proverbs 1:8-19, Matthew 7:1-23, Genesis 17").
- **Theme**: you compose a 3-part descriptive phrase for the title once you've read
  the passages (e.g. "The Two Ways, the Sign of the Covenant and the Judge of All
  the Earth"). Use the word "and", not "&".

---

## Step 1 — Pull text + run the study tools

### 1a. Smooth BSB (do NOT use lookup_verse for this)
The MCP `lookup_verse` returns a *wooden interlinear* and only the first verse of a
range. The smooth BSB lives in `db/study_bible.db`, table `bsb_verses`. Use the helper:

```bash
.venv-tts/bin/python "$SKILL_DIR/scripts/pull_bsb.py" \
  "Proverbs 1:8-19" "Matthew 6:25-34" "Matthew 7:1-23" "Genesis 17" "Genesis 18"
```

(Book codes are non-obvious — Mark=`Mrk`, John=`Jhn`, Ezekiel=`Ezk`, Joel=`Jol`,
Nahum=`Nam`, Song=`Sng`; the script resolves full names for you.)

### 1b. Study-bible MCP tools — these are DEFERRED; load before use
Run `ToolSearch` with `select:mcp__study-bible__lookup_verse,mcp__study-bible__word_study,mcp__study-bible__get_cross_references,mcp__study-bible__get_study_notes,mcp__study-bible__get_textual_variant,mcp__study-bible__get_ane_context,mcp__study-bible__get_torah_weave,mcp__study-bible__get_bible_dictionary,mcp__study-bible__get_key_terms,mcp__study-bible__people_in_passage,mcp__study-bible__lookup_name,mcp__study-bible__get_theology_context,mcp__study-bible__explore_person_events,mcp__study-bible__explore_place`
then call them (batch independent calls in parallel):

- **`lookup_verse`** (per passage) — for the original Greek/Hebrew + Strong's to quote
  in callouts. (Its smooth gloss is poor — use `pull_bsb.py` text for the body.)
- **`word_study`** — `strongs=` for each key term (≈2 per passage; see voice below).
- **`get_cross_references`** — for each load-bearing verse (default cap 8 is fine).
- **`get_study_notes`** — chapter-level Tyndale + translation notes. **Gotcha:** a
  whole-chapter call can exceed the token limit and spill to a file; pull just the
  Tyndale layer with `awk '/^### Translation Notes/{exit}{print}' <file>`.
- **`get_textual_variant`** — for any NT-quotes-OT or notable MT/LXX/DSS divergence.
- **Torah/Genesis passages also:** `get_torah_weave` (the Kline unit + paired cells),
  `people_in_passage`, `get_theology_context` (Heiser two-powers / divine council),
  `get_ane_context`, `get_bible_dictionary`, `explore_place`.
- **`get_ane_context` gotcha:** a chapter reference often returns nothing — fall back
  to `dimension=` + `period=` (e.g. `legal_covenant`/`patriarchal`, `gender_family`,
  `social_structure`; periods: patriarchal, exodus_conquest, …, roman).
- **Context economy** (see memory): list tools default to a few high-signal results —
  trust the strength ordering, don't pad or crank limits without reason.

### 1c. Present Part One in chat
Write the readings in the house voice (see "Voice & structure" below): for each
passage — a description heading, the **full BSB verses inline**, exegetical
commentary, **Hebrew/Greek callouts** (script + transliteration + Strong's), and a
"A thread worth marking" note that links across the day and to adjacent days. End
with "**N threads tying Day N together**" (match the number to the day where it
reads well — Day 7 had seven, Day 8 had eight). Then hand back for questions.

---

## Step 2 — Answer the user's questions (→ Part Two)

Answer each follow-up using the tools (re-pull cross-refs / word studies / ANE /
theology as needed). Keep each answer self-contained — it becomes one entry under
**Part Two — "Questions We Followed"** (italic question + answer).

---

## Step 3 — Assemble the post HTML

Copy `resources/template.html` to `podcast/dayN/Bible_in_a_Year_Study_DayN.html` and
fill it in. **`mkdir -p podcast/dayN` first.** The template encodes the exact CSS,
section order, and the structural rules below.

**Structural rules that keep the audio pipeline working — do not break these:**
- Everything is a **direct child of the single `<div class="wrap">`** (flat). No
  `<section>`/`<header>`/nested wrappers — `clean.py` only recurses one level into a div.
- **Verse blockquotes:** `<blockquote class="verses"><sup>8</sup> text<br> …</blockquote>`.
  `<sup>` renders as superscript on Substack **and** is stripped from the audio.
- **Callouts are `<blockquote class="callout">`** (never a `<div>` — a div would be
  dropped from the audio). Lead with `<strong>Hebrew/Greek — …</strong>`.
- **Original-language words in `<strong>`**, transliteration in `<em>`, Strong's like
  `H8549` / `G3309`. `clean.py` drops the script + Strong's, keeps the transliteration.
- Keep the `<h2>Part One — The Readings</h2>` heading verbatim — `clean.py`'s
  intro-strip starts the audio at "Part One".
- Order: `p.kicker` → `h1` (passages) → `p.orn` ❦ → `p.banner` ("Day N · Weekday,
  D Month YYYY · Theme") → `p.intro` → Part One → threads (`<ol>`) → Part Two →
  Part Three appendix → `p.orn` → "On Sources" → `p.sdg` "Soli Deo gloria."

**Appendix (Part Three) sections** to include as `<h3>` + `<ul>`: Word Studies,
Cross-Reference Sets, Textual Note, Ancient Near East Context, Torah Weave,
Dictionary & Place Data, Study Notes Consulted — then "On Sources."

---

## Step 4 — Render the voiceover (Kokoro, local, free)

```bash
bash "$SKILL_DIR/scripts/make_audio.sh" \
  --html podcast/dayN/Bible_in_a_Year_Study_DayN.html \
  --work podcast/dayN \
  --title "Day N · <Weekday>, <D Month YYYY> · <Theme>" \
  --subtitle "<Passage> · <Passage> · …" \
  --date YYYY-MM-DD
# default voice bm_george (British male, matches the series). Add --voice to change.
```

This script: builds the raw JSON **directly** (preserving `<sup>`/glyph tags — it does
**not** use the lossy `html_to_raw.py`, which would read verse numbers aloud) →
`clean.py` → **validates 0 glyphs / 0 Strong's** → `build.py`. Render ~8-9 min for a
~43-min episode; **run it in the background** and keep working on the draft. Output:
`podcast/dayN/audio/01_*.mp3` (~50 MB) plus a large `.wav` you can delete.

Dependencies (already set up on this machine): repo venv **`.venv-tts`** (NOT the skill
venv); Kokoro/torch/soundfile/bs4 in it; `ffmpeg` on PATH; the
`~/.claude/skills/substack-podcast/scripts/{clean.py,build.py}`.

---

## Step 5 — Create the Substack draft (Claude-in-Chrome)

**Substack has no publishing API** — the only way in is browser automation in a Chrome
that is **logged into Substack**. Load the browser tools first:
`ToolSearch select:mcp__claude-in-chrome__tabs_context_mcp,...navigate,...computer,...find,...read_page,...file_upload`.

1. `tabs_context_mcp { createIfEmpty: true }` → get the `tabId`.
2. `navigate` → `https://studybible.substack.com/publish/post?type=newsletter`.
   **Each navigation to this URL creates a NEW empty draft — navigate once.**
3. Screenshot. **If you see "Sign in to Study Bible / this page is private"**, the
   controlled Chrome isn't logged in → **STOP and ask the user to sign in themselves**
   (you must never enter passwords). When they confirm, navigate once more.
4. **Title:** click the title field (≈ 700,132), `type` the title.
5. **Subtitle:** click "Add a subtitle…" (≈ 700,187), `type` the passage list.
   (Coords drift as the title wraps — screenshot to confirm before clicking.)
6. **Body:** generate the paste-ready body and load it onto the clipboard as
   `text/html`, then click into the editor and paste:
   ```bash
   .venv-tts/bin/python "$SKILL_DIR/scripts/make_substack_body.py" \
     --html podcast/dayN/Bible_in_a_Year_Study_DayN.html --work podcast/dayN
   bash "$SKILL_DIR/scripts/clip_html.sh" podcast/dayN/body_substack.html
   ```
   Then in the browser: click the body ("Start writing…", ≈ 700,255) → `computer key cmd+v`.
   Substack preserves headings, blockquotes, `<sup>`, bold, lists, dividers, and
   Greek/Hebrew glyphs. Screenshot top + middle + bottom to verify.
   (`make_substack_body.py` drops the kicker/h1/banner/first-ornament — those already
   live in the title & subtitle fields — and strips class attributes.)
7. **Leave it as a DRAFT.** Never click Continue/Publish — the user reviews and publishes.

---

## Step 6 — Audio upload (currently manual)

The ~50 MB mp3 exceeds the browser `file_upload` 10 MB cap, so you can't auto-insert
it. Default: tell the user to add the voiceover themselves (audio/headphones button in
the toolbar, or *Settings → add a voiceover*) from `podcast/dayN/audio/01_*.mp3`. If
they want it auto-uploaded, render a <10 MB copy and `file_upload` it to Substack's
audio `<input type=file>`:
```bash
ffmpeg -y -i podcast/dayN/audio/01_*.mp3 -ac 1 -b:a 24k podcast/dayN/audio/voiceover_small.mp3
```

---

## Voice & structure (match the series)

Elegant, scholarly-but-readable. Per reading: a "<Passage> — <one-line description>"
heading; the full BSB inline; commentary that does real exegesis; 1-3 **callouts**
("Hebrew/Greek — <hook>") giving the key word (script + translit + Strong's + sense);
and "A thread worth marking" notes that connect within the day and to adjacent days
(e.g. Day 8's *tamim* ↔ Day 7's *teleios*; Mt 7:23 ↔ Ps 6:8). Flag contested readings
humbly (divine-council / two-powers is "one school of reading; alternatives noted").
Close with the threads list, then Part Two/Three when ready. Scripture = BSB (public
domain); credit BDB/LSJ/Strong's, Tyndale, TSK, Weinfeld/Nuzi (ANE), Heiser
(two-powers), Moshe Kline (Torah Weave).

## Title / subtitle conventions
- **Substack title:** `Day N · <Theme>` (middot `·`, "and" not "&", no date).
- **Substack subtitle:** passages joined ` · `, en-dash ranges (`1:8–19`).
- **HTML banner** (`p.banner`): `Day N · <Weekday>, <D Month YYYY> · <Theme>`.

## Gotchas (consolidated)
- study-bible + claude-in-chrome MCP tools are **deferred** → ToolSearch-load first.
- `lookup_verse` ≠ smooth BSB → use `pull_bsb.py` / `bsb_verses`.
- whole-chapter `get_study_notes` can spill to a file → `awk` out the Tyndale layer.
- `get_ane_context` by chapter is often empty → use `dimension` + `period`.
- Audio: build raw JSON **directly** (not `html_to_raw`) so `<sup>` verse numbers are
  stripped; venv is **`.venv-tts`**; validate 0 glyphs / 0 Strong's before building.
- Substack: no API; needs a logged-in Chrome (**user signs in — you can't**); each
  `publish/post` navigation makes a new draft; body via clipboard-`text/html` + Cmd+V;
  50 MB audio > 10 MB upload cap → audio stays manual.

## Files in this skill
- `scripts/pull_bsb.py` — smooth BSB for passages from `bsb_verses`.
- `scripts/make_audio.sh` — raw-json → clean → validate → build (the audio pipeline).
- `scripts/make_audio_input.py` — direct raw-JSON adapter (preserves `<sup>`/glyphs).
- `scripts/make_substack_body.py` — paste-ready body (drops title/subtitle dupes).
- `scripts/clip_html.sh` — load an HTML file onto the macOS clipboard as `text/html`.
- `resources/template.html` — the post skeleton + exact CSS + structural rules.
