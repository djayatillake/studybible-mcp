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
voiceover (typically 50–60 min; the length follows the readings). This skill turns *a list of passages* into a finished Substack
draft + audio. **Always run from the repo root** (`/Users/david/studybible-mcp`).
`SKILL_DIR` = the directory containing this file.

Related memory: see `project_substack_workflow.md` and `feedback_context_economy.md`.

---

## The daily flow (3 stages — the user drives the gates)

This is normally done in **three messages**, not one. Don't skip ahead.

1. **Readings** — user gives the day's passages. You pull BSB + run the tools and
   present **Part One** (the readings, plus a closing connections list only if the day
   has real ones) inline in chat, with the **full BSB verses shown inline**. Then stop.
2. **Questions** — user asks follow-up questions; you answer them in chat. These
   become **Part Two — "Questions We Followed."**
3. **Publish** — user says they're ready. You assemble the HTML, render the audio,
   and create the Substack draft for review. User adds the audio + publishes.

You can compress stages if the user asks, but the default is staged.

---

## Step 0 — Establish Day N, date, theme, passages

- **Day N — derive from the filesystem, NOT from "today."** David schedules posts in
  advance (he often produces several days ahead while away), so the environment's
  "Today's date" does **not** tell you which day you're making. The next study is
  **`(highest existing podcast/dayN) + 1`**:
  ```bash
  ls -d podcast/day* 2>/dev/null | sed 's:.*/day::' | sort -n | tail -1   # highest N so far
  ```
  Confirm N with the user before assembling ("this is Day 17 — yes?"). If the user names
  a Day N, trust the user over the count. **A `podcast/dayN` that already exists is a
  finished study — never overwrite or `rm -rf` it (see the Step 3 guard).**
- **Date — derive from the day-number anchor, NOT from "today."** Anchor:
  **Day 8 = Saturday 6 June 2026**, so Day N falls on `6 June 2026 + (N − 8)` days
  (Day 9 = Sun 7 Jun, Day 16 = Sun 14 Jun, Day 17 = Mon 15 Jun, …).
- **Passages — fetch from the YouVersion plan (added 7 Aug 2026).** The series follows
  *The Bible with Nicky and Pippa Gumbel (Classic)*, plan id **65489**, and the plan's
  day number **matches podcast Day N** (verified at Day 88). Once N is established,
  WebFetch the **public** plan page and read the day's passages off it:
  ```
  https://www.bible.com/reading-plans/65489-the-bible-with-nicky-and-pippa-gumbel-classic/day/N
  ```
  (The `/users/dave665/…/subscription/…/day/N` form the user sometimes pastes
  307-redirects to a YouVersion login WebFetch can't pass — strip it down to the
  public URL above.) **Sanity-check continuity**: each continuing book should resume
  exactly where the previous day stopped (see the `<h1>` in
  `podcast/day(N-1)/Bible_in_a_Year_Study_Day(N-1).html`). If the user pastes passages
  explicitly, those win. **Never infer the readings from continuation alone** — at
  Day 88 the wisdom slot switched books mid-stream (Psalm 38 → Proverbs 8) and the
  guessed Luke range was wrong; the plan page is the source of truth.
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

Save the output to a file in the scratchpad (e.g. `bsbN.txt`) — the HTML is later
generated from it (Step 3). **Quote-check every other verse you quote** (cross-references,
Part Two evidence) by running it through `pull_bsb.py` as well, before it goes in the
post. Don't quote from memory: at Day 130, Ps 2:4, John 12:32 and Num 22:23 had all
been quoted in other translations' wording in chat and had to be corrected to the BSB.

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
- **Atonement/ransom/sacrifice trigger:** whenever a reading touches the cross,
  sacrifice, ransom, blood, Leviticus, or Hebrews, pull **all three** before writing:
  `get_theology_context(theme="atonement_models")` (the substitution-vs-representation
  synthesis + the ransom saying), `get_ane_context(dimension="ane_methodology")` for
  `method_008` (the representation-frame read-order), and
  `get_ane_context(dimension="religious_practices", period="exodus_conquest")` for the
  Rillera/Milgrom non-penal cult cells. **Default frame = representation** (inclusive,
  last Adam / union); penal substitution is a true juridical facet *inside* it, never
  bare exclusive place-taking. (Avoids the PSA-default error — see those cells.)
- **Context economy** (see memory): list tools default to a few high-signal results —
  trust the strength ordering, don't pad or crank limits without reason.

### 1c. Present Part One in chat
Write the readings in your own voice (see "Voice & structure" below): for each
passage — a description heading, the **full BSB verses inline**, exegetical
commentary, and **Hebrew/Greek callouts** (script + transliteration + Strong's) where
a word repays it. **Split a long reading into movements** — one heading per movement,
each with its verses then its commentary (Day 130: John 6:25–40 / 41–51 / 52–59;
Judges 10:1–5 / 6–18) — rather than one long block of verses followed by all the comment.

**Connecting threads are optional** (user feedback, 23 Sep 2026: forced threads read
as filler). When a connection to another reading or an adjacent day is real and
matters — a shared Hebrew word, a deliberate echo, a quotation — make it in the
commentary where it comes up. Don't add a per-reading "thread" note, don't pad to a
count, and don't go looking for adjacent-day links to fill space. If the day has
several genuine cross-passage links, you may close Part One with a short numbered list
under a heading of your own (Day 130: "What holds the day together"); a day without
them skips the list. Then hand back for questions.

---

## Step 2 — Answer the user's questions (→ Part Two)

Answer each follow-up using the tools (re-pull cross-refs / word studies / ANE /
theology as needed). Keep each answer self-contained — it becomes one entry under
**Part Two — "Questions We Followed."** Format each entry **quote-first** (per reader
feedback — see "Reader-friendly structure" below):

1. `h3` question title.
2. **When the question turns on a specific verse**, quote it *once* up front in a
   `blockquote.verses` — just the operative verse/clause, not a whole long passage —
   **before** the italic question. (Skip the quote for purely conceptual questions not
   anchored to one verse.)
3. `p.q` the italic question.
4. `p` the answer — which **must not re-quote that same text**. It may quote *other*
   verses it brings in as evidence; it refers back to the lead quote by reference.

Never ask the question and then re-quote the same verse to answer it. If a long answer
makes several moves, **signpost** them (a short "first… / then… / here's the turn" or a
one-line recap) so the reader never loses the thread.

---

## Step 3 — Assemble the post HTML

**First, guard against clobbering an existing study.** `podcast/dayN/` directories are
finished deliverables that **persist across sessions**, are **git-ignored** (so not in
version control), and are **not Trash-recoverable** — a stray `rm -rf` is unrecoverable
(the content survives only if it was already pushed to a Substack draft). So before
writing anything, create the dir *only if it's free*:
```bash
[ -e "podcast/dayN/Bible_in_a_Year_Study_DayN.html" ] && echo "STOP: day N already exists" || mkdir -p podcast/dayN
```
If that prints `STOP`, the day number is wrong (or this day is already done) — **stop and
reconfirm N with the user. Never `rm -rf` a `podcast/dayN` directory to "start clean."**
(A Write-tool rejection like *"file already exists / not read yet"* means the same thing:
something real is already there — inspect it, don't clear it.)

Then build `podcast/dayN/Bible_in_a_Year_Study_DayN.html` from `resources/template.html`,
which encodes the exact CSS, section order, and the structural rules below. **Generate the
file rather than hand-typing verses:** write a short Python script in the scratchpad that
parses the saved `pull_bsb.py` output (`===== <Passage> =====` headers, `N  text` lines),
emits each `blockquote.verses` from it, holds the prose as HTML strings, takes the
`<head>` from the template, and refuses to overwrite an existing file. That way no verse
is retyped, and full passages are guaranteed. After writing, sanity-check it:
```bash
F=podcast/dayN/Bible_in_a_Year_Study_DayN.html
grep -o '<sup>' $F | wc -l          # = total reading verses + Part Two lead quotes
grep -c 'Part One — The Readings' $F   # = 1
```
and confirm there's no Hebrew/Greek script outside `<strong>` and only one `<div>`.

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
  D Month YYYY · Theme") → `p.intro` → Part One → *(optional)* connections list
  (`h2` + `<ol>`) → Part Two → Part Three appendix → `p.orn` → "On Sources" →
  `p.sdg` "Soli Deo gloria."

**Appendix (Part Three) sections** to include as `<h3>` + `<ul>`: Word Studies,
Cross-Reference Sets, Textual Note, Ancient Near East Context, **Theology Context**,
Torah Weave, Dictionary & Place Data, Study Notes Consulted — then "On Sources."
Omit a section that has nothing in it (e.g. Torah Weave on a day with no Torah reading)
rather than leaving it empty.

**Theology Context section**: one `<li>` per scholar/corpus actually drawn on that
day (`get_theology_context` and the atonement/ANE-methodology stack) — e.g. Rillera
(*Lamb of the Free*, non-penal cult grammar), Stott (*The Cross of Christ*,
self-substitution), Owen (definite atonement, mortification), Heiser (divine
council / two-powers), Bradley (corporate headship, domain transfer), Lennox,
Milgrom (kipper as purgation), Moffitt — naming **which claim or frame of theirs
the study used and where**. Skip scholars merely retrieved but unused; this section
is provenance, not a bibliography.

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
`clean.py` → **validates 0 glyphs / 0 Strong's** → `build.py`. Render takes ~7–9 min
(Day 130: a 58-min episode in ~7 min); **run it in the background** and keep working
on the draft. Output: `podcast/dayN/audio/01_*.mp3` (~50–70 MB) plus a large `.wav`
you can delete.

The script exports `LC_ALL=en_US.UTF-8` itself (added 23 Sep 2026). With `LANG` unset,
as in the desktop app's shell, BSD `grep` matched the glyph ranges byte by byte and
reported false glyphs for em dashes and ❦ (Day 130 showed `glyphs=110` on clean text).
If validation ever fails, re-run the check under a UTF-8 locale before editing the HTML.

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
   **Right before pasting, confirm the clipboard holds this day's body.** Parallel
   sessions share the clipboard (see `feedback_clipboard_race_substack.md`):
   ```bash
   osascript -e 'the clipboard as «class HTML»' | sed -E 's/^«data HTML//; s/»$//' | xxd -r -p | head -c 120
   ```
   It should print the start of this day's `p.intro`.
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

## Voice & structure

Write in your own voice (user, 23 Sep 2026): clear, direct, scholarly but readable. Don't
imitate earlier posts or open them for style. The only earlier-day file to open is the
previous day's `<h1>`, to check the passages continue. Let the length follow the
readings, not a word target. Per reading: a "<Passage> — <one-line description>" heading
(one per movement for long readings); the full BSB inline; commentary that does real
exegesis; **callouts** ("Hebrew/Greek — <hook>") giving a key word (script + translit +
Strong's + sense) where the word repays it. There's no set number of callouts.

**Connections are optional, never quotas.** Link across the day or to an adjacent day
only when the link is really in the text and helps the reader (e.g. Day 8's *tamim* ↔
Day 7's *teleios*; Mt 7:23 ↔ Ps 6:8; Day 130's *yechidah* → LXX *monogenēs* → John 3:16),
and make it in the commentary where it comes up. If a day's readings don't connect,
treat them separately; that's fine. Flag contested readings
humbly (divine-council / two-powers is "one school of reading; alternatives noted").
**Pseudepigrapha must be labelled** (user rule, 4 Aug 2026): any citation of 1 Enoch,
Jubilees, or other non-canonical Second Temple works must say in the same breath that
the work is pseudepigraphal / not Scripture, AND be paired with the canonical passages
carrying the same tradition (e.g. 1 Enoch's Watchers → Gen 6:1–4; 2 Pet 2:4; Jude 6 —
noting Jude 14–15 quotes 1 Enoch without according it canonical status). Never let a
non-canonical citation stand as though it were a biblical proof.
Close Part One with the connections list only if the day earns one, then Part Two/Three
when ready. Scripture = BSB (public
domain); credit BDB/LSJ/Strong's, Tyndale, TSK, Weinfeld/Nuzi (ANE), Heiser
(two-powers), Moshe Kline (Torah Weave).

**Reader-friendly structure (from reader feedback, 10 Jun 2026):**
- **Quote-first questions.** Lead a Part Two question with the verse it turns on, then
  ask; never ask and then re-quote the same text to answer (see Step 2). Front-load the
  text so the reader meets it once.
- **Signpost long sections.** If there's a closing connections list, keep each item to
  one idea, point-first, with a bolded title naming it (avoid Day-1-style long prose
  items). In any long prose stretch, whether extended commentary or a multi-move Part Two
  answer, add brief transitions or a one-line recap when you move to a new point or a
  new book ("first… / second… / here's the turn"), so a reader coming off a dense
  paragraph is never left asking "where are we now." Prefer several short signposted
  steps (bulleted or numbered where the points are parallel) over one sprawling block.

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
  The glyph check needs a UTF-8 locale (`make_audio.sh` now sets it); a `glyphs=N` failure
  on text that should be clean is the locale, not the HTML.
- Quote every cross-reference from `pull_bsb.py`, not memory (Day 130 caught three
  quotations in other translations' wording).
- Substack: no API; needs a logged-in Chrome (**user signs in — you can't**); each
  `publish/post` navigation makes a new draft; body via clipboard-`text/html` + Cmd+V;
  50 MB audio > 10 MB upload cap → audio stays manual.
- **Getting ahead (common):** derive **Day N from `(highest existing podcast/dayN) + 1`**
  and the date from the **Day 8 = Sat 6 Jun 2026** anchor — never from the environment's
  "today." Confirm N with the user.
- **Never clobber a `podcast/dayN` dir:** they're finished studies, git-ignored and
  Trash-bypassed, so deletion is unrecoverable. Guard with
  `[ -e podcast/dayN/Bible_in_a_Year_Study_DayN.html ] && STOP`; never `rm -rf` one. A
  Write "already exists" rejection = something's there → inspect, don't clear. (See
  `feedback_no_rm_podcast_dirs.md`.)
- A very long study trips Substack's *"Near email length limit"* banner — informational
  only (affects the emailed copy, not the web post); leave as draft regardless.

## Files in this skill
- `scripts/pull_bsb.py` — smooth BSB for passages from `bsb_verses`.
- `scripts/make_audio.sh` — raw-json → clean → validate → build (the audio pipeline).
- `scripts/make_audio_input.py` — direct raw-JSON adapter (preserves `<sup>`/glyphs).
- `scripts/make_substack_body.py` — paste-ready body (drops title/subtitle dupes).
- `scripts/clip_html.sh` — load an HTML file onto the macOS clipboard as `text/html`.
- `resources/template.html` — the post skeleton + exact CSS + structural rules.
