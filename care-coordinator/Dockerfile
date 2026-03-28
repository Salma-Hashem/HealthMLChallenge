# ── Build stage: compile the React frontend ─────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ .
RUN npm run build

# ── Runtime stage: Flask + gunicorn ─────────────────────────────────────────
FROM python:3.11-slim

# Non-root user for security
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install Python dependencies first (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY --chown=app:app . .

# Copy compiled frontend assets from build stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Drop privileges
USER app

EXPOSE 5000

# Health check — used by Docker and docker-compose
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" \
  || exit 1

# Start gunicorn with 2 workers
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120"]
