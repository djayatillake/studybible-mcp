# Self-Hosting the Study Bible MCP Server

This guide covers running your own instance of the Study Bible MCP server.

## Option 1: Local Development

### Prerequisites
- Python 3.10 or higher
- pip or uv package manager

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/studybible-mcp.git
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

4. **Download STEPBible data**
   ```bash
   python scripts/download_stepbible.py
   ```
   This downloads ~50MB of lexicon and tagged text data.

5. **Build the database**
   ```bash
   python scripts/build_database.py
   ```
   This creates `db/study_bible.db` (~100MB).

6. **Run the server**

   For local use with Claude Desktop (stdio):
   ```bash
   python -m study_bible_mcp.server --transport stdio
   ```

   For network access (SSE):
   ```bash
   python -m study_bible_mcp.server --transport sse --port 8080
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

The Dockerfile downloads STEPBible data and builds the database during the build process.

### Run Locally

```bash
docker run -p 8080:8080 studybible-mcp
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
      "args": ["-y", "mcp-remote", "http://localhost:8080/sse"]
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
   fly volumes create studybible_data --size 1 --region <your-region>
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
https://your-studybible-mcp.fly.dev/sse
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STUDY_BIBLE_DB` | Path to SQLite database | Auto-detected |
| `PORT` | Server port (SSE mode) | `8080` |
| `TRANSPORT` | Transport mode (`stdio` or `sse`) | `stdio` |

---

## Updating the Database

To refresh the STEPBible data:

```bash
# Download latest data
python scripts/download_stepbible.py --force

# Rebuild database
python scripts/build_database.py --rebuild
```

For Docker/Fly.io, rebuild the image to include the new database.

---

## Monitoring (Fly.io)

View logs:
```bash
fly logs
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
- **Free tier**: 3 shared-cpu-1x VMs with 256MB RAM each
- **This app**: Uses ~256-512MB RAM, fits in free tier
- **Volume**: 1GB volume is $0.15/month

### Self-hosted
- Any server with Python 3.10+ and 256MB+ RAM
- Database is ~100MB, read-only

---

## Data Source

This project uses data from [STEPBible](https://github.com/STEPBible/STEPBible-Data),
licensed under CC BY 4.0. The data includes:

- **TBESG/TBESH**: Greek and Hebrew lexicons
- **TAGNT/TAHOT**: Tagged Greek NT and Hebrew OT
- **TIPNR**: Proper names database
- **TEGMC/TEHMC**: Morphology code expansions

All data remains freely available under the same license.
