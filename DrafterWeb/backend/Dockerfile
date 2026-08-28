# Build context is DrafterWeb/, not backend/, so this stage can reach frontend/.
FROM node:24-alpine AS frontend

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY frontend/ frontend/
# vite.config.ts writes to ../backend/app/static, which is why the whole
# project root is the context rather than just the frontend directory.
RUN mkdir -p backend/app/static && cd frontend && npm run build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /src/backend/app/static ./app/static

# Rankings arrive as a read-only bind mount, not baked into the image, so
# regenerating them on the host does not require a rebuild.
ENV RANKINGS_DIR=/rankings \
    DATA_DIR=/data \
    SEASON=2026

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
