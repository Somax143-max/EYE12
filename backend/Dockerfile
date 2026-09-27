# ==============================================================================
# DRISHTI AI: Production Backend Docker Container for Render / Cloud Deployment
# ==============================================================================
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies for OpenCV and Healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU and Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir \
    torch==2.1.2+cpu --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Copy backend application code
COPY backend /app/backend
COPY data /app/data
COPY config /app/config
COPY results /app/results
COPY logs /app/logs

WORKDIR /app/backend

# Create non-root user
RUN useradd -m -u 1001 drishti && \
    chown -R drishti:drishti /app

USER drishti

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

CMD ["python", "server.py", "8080"]
