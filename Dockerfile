# syntax=docker/dockerfile:1.6
# 国内可传 --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONFIG_DIR=/config \
    PORT=3155 \
    TZ=Asia/Shanghai

WORKDIR /app

# python:3.12-slim already carries ca-certificates; timezone data comes from the
# `tzdata` wheel in requirements.txt, so no apt-get layer is needed here.

# Keep this layer before COPY app/web so source edits do not reinstall deps.
# PIP_INDEX_URL can point at a nearby mirror to speed up downloads.
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile --prefer-binary --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY app ./app
COPY web ./web

RUN mkdir -p /config
VOLUME ["/config"]

EXPOSE 3155

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3155/api/health', timeout=3)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3155} --proxy-headers --forwarded-allow-ips='*'"]
