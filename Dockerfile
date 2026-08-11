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

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9870/api/health', timeout=2)" || exit 0

ENTRYPOINT ["python", "-m", "src.main"]
