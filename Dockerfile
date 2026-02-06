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

# Copy requirements and install (includes sqlite-vec for vector search)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY pyproject.toml .
COPY src/ src/

# Install the package
RUN pip install --no-cache-dir -e .

# Create data directory for Fly.io volume mount
RUN mkdir -p /data

# Environment variables - use volume-mounted database
ENV TRANSPORT=sse
ENV PORT=8080
ENV STUDY_BIBLE_DB=/data/study_bible.db

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the server
CMD ["python", "-m", "study_bible_mcp.server", "--transport", "sse", "--host", "0.0.0.0"]
