FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    UPLOAD_DIR=/tmp/ml-enterprise/uploads \
    CLEANUP_UPLOADS_AFTER_SUCCESS=true

WORKDIR /app/backend

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN mkdir -p /tmp/ml-enterprise/uploads

CMD ["sh", "-c", "python -m alembic upgrade head && python -m app.run"]
