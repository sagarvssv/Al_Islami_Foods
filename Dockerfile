FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.railway.txt .
RUN pip install --no-cache-dir -r requirements.railway.txt

# Copy application code
COPY approval_server.py .
COPY agent/ agent/

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Run server
CMD ["python", "approval_server.py"]