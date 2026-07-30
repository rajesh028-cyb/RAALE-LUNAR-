FROM python:3.11-slim

# Avoid writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install runtime system packages if any (curl for healthcheck, sqlite3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire backend source
COPY . /app/backend/

# Create uploads directory and set permissions for non-root user
RUN mkdir -p /app/uploads && \
    useradd -u 10001 -u 1000 -m appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check command using python (or curl if installed)
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
