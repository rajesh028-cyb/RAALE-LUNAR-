FROM python:3.11-slim

# Avoid writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install runtime system packages if any
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire backend source
COPY . /app/backend/

# Set permissions for non-root user
RUN useradd -u 10001 -u 1000 -m appuser && \
    chown -R appuser:appuser /app

USER appuser

# Start loader service
CMD ["python", "backend/loader/main.py"]
