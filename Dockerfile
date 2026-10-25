# syntax=docker/dockerfile:1

FROM node:22-slim AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js svelte.config.js jsconfig.json ./
COPY src ./src
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --user-group --create-home youhoard \
    && mkdir -p /data /media \
    && chown youhoard:youhoard /data /media

# uv keeps no cache, so none is baked into the image, and the other caches go to /tmp: the
# container works as any user (Compose `user:`), not only UID 1000.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Writable by everyone, so YTDLP_UPDATE_ON_START can upgrade yt-dlp whatever user runs it.
RUN uv sync --frozen --no-dev --no-install-project \
    && chmod -R a+rwX /opt/venv
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# The code changes most often, so it goes last: an update only rebuilds and pulls these layers.
COPY main.py ./
COPY app ./app
COPY --from=frontend /src/app/static/dist ./app/static/dist

USER youhoard
ENV DATA_DIR=/data \
    MEDIA_DIR=/media \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
VOLUME ["/data", "/media"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
