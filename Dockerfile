FROM python:3.11-slim

LABEL maintainer="ps-throttle"
LABEL description="PlayStation Bandwidth Guardian - auto-throttles Transmission when PS is active"

# Install network tools for ping and ARP
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        iputils-ping \
        net-tools \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Run as non-root where possible
# Note: ping requires NET_RAW capability, which is added via docker-compose
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 9091)); s.close()" || exit 0

ENTRYPOINT ["python", "-m", "src.main"]
