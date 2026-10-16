# syntax=docker/dockerfile:1
# TDM Platform API image (Step 17).
#   docker build -t tdm-api .
# Secrets are NEVER baked in: pass them at runtime (env / secret store). Data lives
# in the /data volume. Runs as an unprivileged user; migrations run on start.

FROM python:3.10.5-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.lock .
RUN pip install --prefix=/install -r requirements.lock

FROM python:3.10.5-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TDM_AUTH_MODE=production \
    TDM_DATA_DIR=/data
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin tdm \
 && mkdir -p /data && chown tdm:tdm /data
COPY --from=deps /install /usr/local
WORKDIR /app
COPY --chown=tdm:tdm . .
USER tdm
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
# TLS is terminated by the reverse proxy in front of this container.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
