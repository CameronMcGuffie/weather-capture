# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend-deps
WORKDIR /build
COPY backend/requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends rtl-433 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/weather.db \
    STATIC_DIR=/app/static

WORKDIR /app
COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./static

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
