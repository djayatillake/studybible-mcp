# Study Bible MCP Server Dockerfile
#
# Multi-stage build:
# 1. Build stage: Download STEPBible data and build database
# 2. Runtime stage: Minimal image with pre-built database
#
# Build: docker build -t studybible-mcp .
# Run:   docker run -p 8080:8080 studybible-mcp

# ============================================================================
# Stage 1: Builder - Download data and build database
# ============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY pyproject.toml .
COPY src/ src/
COPY scripts/ scripts/

# Install the package
RUN pip install --no-cache-dir -e .

# Create directories
RUN mkdir -p data db

# Download STEPBible data
RUN python scripts/download_stepbible.py --data-dir /build/data

# Build the database
RUN python scripts/build_database.py --data-dir /build/data --db-path /build/db/study_bible.db

# Verify database was built
RUN ls -la /build/db/

# ============================================================================
# Stage 2: Runtime - Minimal production image
# ============================================================================
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install SSE dependencies
RUN pip install --no-cache-dir starlette uvicorn

# Copy source code
COPY pyproject.toml .
COPY src/ src/

# Install the package
RUN pip install --no-cache-dir -e .

# Copy pre-built database from builder stage
COPY --from=builder /build/db/study_bible.db /app/db/study_bible.db

# Create data directory for Fly.io volume mount
RUN mkdir -p /data

# Environment variables
ENV TRANSPORT=sse
ENV PORT=8080
ENV STUDY_BIBLE_DB=/app/db/study_bible.db

# For Fly.io with volume, use /data/study_bible.db instead:
# ENV STUDY_BIBLE_DB=/data/study_bible.db

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the server
CMD ["python", "-m", "study_bible_mcp.server", "--transport", "sse", "--host", "0.0.0.0"]
