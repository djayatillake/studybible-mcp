# Study Bible MCP Server Dockerfile
#
# Lightweight runtime image - expects pre-built database with embeddings
# to be mounted via Fly.io volume at /data/study_bible.db
#
# The database (with embeddings) is built once locally and uploaded to
# the Fly volume. No need to rebuild - the Bible doesn't change.
#
# Build: docker build -t studybible-mcp .
# Run:   docker run -p 8080:8080 -v /path/to/db:/data studybible-mcp

FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the locked runtime dependencies. requirements.txt is exported from
# uv.lock (pinned, with hashes; includes sqlite-vec for vector search and the
# web-server packages from the sse extra).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and privacy policy
COPY pyproject.toml .
COPY PRIVACY.md .
COPY src/ src/

# Install the package itself; its dependencies all came from the lock above
RUN pip install --no-cache-dir --no-deps -e .

# Create data directory for Fly.io volume mount
RUN mkdir -p /data

# The commit shown in the startup log line:
#   fly deploy --build-arg GIT_COMMIT=$(git rev-parse --short HEAD)
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# Environment variables - use volume-mounted database
ENV TRANSPORT=http
ENV PORT=8080
ENV STUDY_BIBLE_DB=/data/study_bible.db

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the server
CMD ["python", "-m", "study_bible_mcp.server", "--host", "0.0.0.0"]
