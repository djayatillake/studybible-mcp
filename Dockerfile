# Study Bible MCP Server Dockerfile
#
# Multi-stage build:
# 1. Build stage: Download STEPBible data, build database, generate embeddings
# 2. Runtime stage: Minimal image with pre-built database + embeddings
#
# Build: docker build --build-arg OPENAI_API_KEY=sk-... -t studybible-mcp .
# Run:   docker run -p 8080:8080 studybible-mcp

# ============================================================================
# Stage 1: Builder - Download data, build database, generate embeddings
# ============================================================================
FROM python:3.11-slim AS builder

# OpenAI API key for embedding generation (required at build time)
ARG OPENAI_API_KEY
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies (includes sqlite-vec and openai)
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

# Generate embeddings for semantic search (~$0.05 API cost, ~5 min)
RUN if [ -n "$OPENAI_API_KEY" ]; then \
        echo "Generating embeddings..." && \
        python scripts/generate_embeddings.py --db-path /build/db/study_bible.db; \
    else \
        echo "WARNING: OPENAI_API_KEY not set, skipping embedding generation"; \
    fi

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

# Copy requirements and install (includes sqlite-vec for vector search)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
