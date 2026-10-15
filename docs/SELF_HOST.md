# Self-Hosting the Study Bible MCP Server

This guide covers running your own instance of the Study Bible MCP server.

## Option 1: Local Development

### Prerequisites
- Python 3.10 or higher
- pip or uv package manager

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/djayatillake/studybible-mcp.git
   cd studybible-mcp
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e ".[sse]"
   ```

4. **Download source data**
   ```bash
   python scripts/download_stepbible.py
   python scripts/download_biblical_versions.py
   python scripts/download_ancient_sources.py
   python scripts/download_bsb.py
   ```
   The additional commands download the pinned 59-book Rahlfs morphology
   corpus, explicit MT/LXX versification mappings, public-domain Brenton English
   and Greek USFM, and every registered ancient-source corpus (currently the
   licensed Josephus and Philo Greek/English corpora, the 1 Enoch and 4 Ezra
   pseudepigrapha, the Targum Onkelos Aramaic/English corpus, the Hebrew
   Qumran corpus, and the Mishnah from Sefaria) into
   `data/ancient_sources/<corpus>/`, and the public-domain Berean Standard
   Bible text into `data/bsb/`, checked against its pinned SHA-256 (without
   it the verse tools show STEPBible's word glosses).
   They validate source checksums before import; the build imports each
   downloaded corpus and fails on an incomplete one.
5. **Build the database**
   ```bash
   python scripts/build_database.py
   python scripts/import_heiser_content.py
   ```
   This creates the base `db/study_bible.db` and imports the bundled attributed
   theology and manuscript-variant records. Its final size depends on the
   optional graph, commentary, and embedding datasets; the deployed database is
   about 750MB once the MT/LXX and Josephus corpora are imported; Philo adds
   about 34MB and the pseudepigrapha about 2MB.

   To bring an existing database (for example one downloaded from a deployment,
   which carries the licence notice under "Data Source" below)
   up to the current schema and sources, upgrade it in place instead of
   rebuilding:
   ```bash
   python scripts/upgrade_database.py --database db/study_bible.db
   ```
   The upgrade downloads the pinned LXX/Brenton sources and every registered
   ancient-source corpus (present files are skipped and every file is
   checksum-verified), migrates the legacy mixed `textual_variants` tables and
   adds new columns, imports MT/LXX, every downloaded ancient-source corpus,
   and the bundled variant cases, and runs SQLite integrity and foreign-key
   checks on a temporary copy. The original file is replaced only when everything
   succeeds, and re-running is safe. Pass `--offline` to use sources already
   under `data/`. A server pointed at a database that has not been upgraded
   answers `get_textual_variant` with a message to run this script.

6. **Run the server**

   For local use with Claude Desktop (stdio):
   ```bash
   python -m study_bible_mcp.server --transport stdio
   ```

   For network access (Streamable HTTP at `/mcp/`, with the deprecated legacy SSE transport at `/sse`):
   ```bash
   python -m study_bible_mcp.server --transport http --port 8080
   ```

### Claude Desktop Configuration (Local)

```json
{
  "mcpServers": {
    "study-bible": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "study_bible_mcp.server", "--transport", "stdio"],
      "cwd": "/path/to/studybible-mcp"
    }
  }
}
```

---

## Option 2: Docker Deployment

### Build the Image

```bash
docker build -t studybible-mcp .
```

The Docker image contains the server code only. It expects a pre-built database to be mounted at `/data/study_bible.db`.

### Run Locally

```bash
docker run -p 8080:8080 \
  -v /absolute/path/to/db:/data:ro studybible-mcp
```
Test the server:
```bash
curl http://localhost:8080/health
```

### Claude Desktop Configuration (Docker)

```json
{
  "mcpServers": {
    "study-bible": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8080/mcp/"]
    }
  }
}
```

---

## Option 3: Fly.io Deployment

### Prerequisites
- [Fly.io CLI](https://fly.io/docs/hands-on/install-flyctl/) installed
- Fly.io account

### Steps

1. **Authenticate with Fly.io**
   ```bash
   fly auth login
   ```

2. **Launch the app**
   ```bash
   fly launch --name your-studybible-mcp
   ```
   - Choose a region close to you
   - Skip the Postgres and Redis prompts

3. **Create a volume for the database**
   ```bash
   fly volumes create studybible_data --size 3 --region <your-region>
   ```

4. **Deploy**
   ```bash
   fly deploy
   ```

5. **Initialize the database** (first time only)

   SSH into the machine:
   ```bash
   fly ssh console
   ```

   Copy the database to the volume:
   ```bash
   cp /app/db/study_bible.db /data/study_bible.db
   ```

   Exit SSH:
   ```bash
   exit
   ```

6. **Update environment variable**

   Edit `fly.toml` to use the volume-mounted database:
   ```toml
   [env]
     STUDY_BIBLE_DB = "/data/study_bible.db"
   ```

   Redeploy:
   ```bash
   fly deploy
   ```

### Your MCP URL

Your server will be available at:
```
https://your-studybible-mcp.fly.dev/mcp/
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STUDY_BIBLE_DB` | Path to SQLite database | Auto-detected |
| `PORT` | Server port for HTTP/SSE transports | `8080` |
| `TRANSPORT` | Transport mode (`stdio`, `sse`, or `http`) | `stdio` |
| `STUDY_BIBLE_DB_READERS` | Read-only database connections that tool calls run on in parallel (`0`: one shared connection) | `4` |
| `STUDY_BIBLE_LOG_DIR` | Directory for the HTTP server's rotating `server.log` (empty: console only) | `logs/` beside the database |
| `STUDY_BIBLE_LOG_KEY` | Key for the daily client hash in log lines | random, kept in `<log dir>/.client-key` |
| `GIT_COMMIT` | Commit shown in the startup log line (`fly deploy --build-arg GIT_COMMIT=$(git rev-parse --short HEAD)`) | `unknown` |

---

## Updating the Database

To refresh the STEPBible data:

```bash
# Download latest data
python scripts/download_stepbible.py --force

# Rebuild database
python scripts/build_database.py --rebuild
```

To upgrade an existing database without a rebuild, run `python scripts/upgrade_database.py --database db/study_bible.db` (see step 5 above).

For Docker, restart the container with the rebuilt database mount. On Fly.io, upload the database to the persistent volume separately from the code deployment, and upload it before running `fly deploy` for code that needs the new tables. Upload it next to the live file under a temporary name, check its size and checksum, then `mv` it over the old database; never delete the live database first. `scripts/upload-db.sh` does this and stops before uploading if `df` shows too little free space. Extend the volume with `fly volumes extend <volume-id> --size <GB>` if needed. The full runbook is in `.claude/commands/deploy-db.md`.

---

## Monitoring (Fly.io)

View live logs (Fly keeps only recent lines):
```bash
fly logs
```

The HTTP server also writes a rotating log on the volume, `/data/logs/server.log`
(5 MB, plus `server.log.1` to `.3`), so earlier incidents can be read back:
```bash
fly ssh console -C "tail -n 100 /data/logs/server.log"
# or open a shell on the machine and search it there:
fly ssh console
grep -E 'WARNING|ERROR' /data/logs/server.log | tail -n 50
```
One line per event, times in UTC. `tool:` lines give each call's outcome,
duration, output size and a short argument summary (`SLOW` past 2 s); `http:`
lines each request's status and duration (`idle=` marks the first request after
5 quiet minutes); `sse:` lines legacy SSE sessions (`open`, `close`, and `stale`
for a POST to an unknown session, once per session id, then a count every 10
minutes); `study-bible-mcp:` lines startup (version, commit, database,
sqlite-vec), shutdown, event-loop stalls and clock jumps (a suspended machine
resuming). Clients appear as a network prefix plus a daily keyed hash
(`203.0.113.*~3fa1c2`), never a full IP address.

Count legacy SSE use on one day, in a `fly ssh console` shell (distinct
clients that opened a stream, SSE sessions opened, and distinct stale session
ids):
```bash
cat /data/logs/server.log* | grep '^2026-10-15' | grep ' sse: open ' | grep -o 'client=[^ ]*' | sort -u | wc -l
cat /data/logs/server.log* | grep '^2026-10-15' | grep -c ' sse: open '
cat /data/logs/server.log* | grep '^2026-10-15' | grep ' sse: stale ' | grep -o 'sid=[0-9a-f]*' | sort -u | wc -l
```

Check status:
```bash
fly status
```

SSH into the machine:
```bash
fly ssh console
```

---

## Cost Estimates

### Fly.io
- Check current Fly.io pricing and allowances before deploying.
- The production configuration uses one shared CPU, 1GB RAM, and a persistent volume.

### Self-hosted
- Python 3.10+ and enough memory for SQLite queries
- At least 3GB of database storage: the ~750MB database, a full temporary copy during upgrades or uploads, plus downloads and embeddings

---

## Data Source

This project uses data from [STEPBible](https://github.com/STEPBible/STEPBible-Data),
licensed under CC BY 4.0. The data includes:

- **TBESG/TBESH**: Greek and Hebrew lexicons
- **TAGNT/TAHOT**: Tagged Greek NT and Hebrew OT
- **TIPNR**: Proper names database
- **TEGMC/TEHMC**: Morphology code expansions

The STEPBible data remains freely available under the same license.

The ancient-source corpora keep their own licences, printed in every result's
Sources block. A database that includes them, such as the one served at
`/download/study_bible.db`, contains CC BY-NC 4.0 material (the ETCBC Dead Sea
Scrolls transcription and the Metsudah Chumash English), for non-commercial use
only, and CC BY-SA 4.0 material (Perseus Josephus, First1KGreek Philo, Latin
Wikisource 4 Ezra), which must be shared alike. The server sends this notice in
the download's `X-Data-License-Notice` header and in the root endpoint's
description.
