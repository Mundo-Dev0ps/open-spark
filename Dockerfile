# syntax=docker/dockerfile:1.7
#
# Spark Libre backend image.
# Multi-stage:
#   builder  — installs deps + dev tools into /venv (editable install)
#   dev      — builder result + tests, used for TDD via `docker compose run`
#   runtime  — slim, non-root, healthcheck, default target for `compose up`
#
# Secrets are env-driven inside the container (SPARK_USE_ENV_SECRETS=1),
# so we never depend on the host's keyring / DBus.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# ---- builder ---------------------------------------------------------------
FROM base AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install -e ".[dev]"

# ---- dev (tests live here) -------------------------------------------------
FROM base AS dev
ARG UID=1000
ARG GID=1000
COPY --from=builder /venv /venv
COPY --from=builder /app /app
COPY tests ./tests
ENV PATH=/venv/bin:$PATH \
    SPARK_USE_ENV_SECRETS=1 \
    XDG_DATA_HOME=/app/.local/share

RUN set -eux; \
    groupadd -g "${GID}" spark 2>/dev/null \
        || groupmod -n spark "$(getent group ${GID} | cut -d: -f1)" 2>/dev/null \
        || true; \
    useradd -u "${UID}" -g "${GID}" -d /app -s /bin/sh -M spark 2>/dev/null \
        || usermod -l spark -d /app "$(id -un ${UID})" 2>/dev/null \
        || true; \
    mkdir -p /app/.local/share/spark-libre/overlays; \
    chown -R "${UID}:${GID}" /app

USER spark
EXPOSE 8765
CMD ["pytest", "-q"]

# ---- runtime (default) -----------------------------------------------------
FROM base AS runtime
ARG UID=1000
ARG GID=1000
COPY --from=builder /venv /venv
COPY --from=builder /app /app
ENV PATH=/venv/bin:$PATH \
    SPARK_USE_ENV_SECRETS=1 \
    XDG_DATA_HOME=/app/.local/share

# UID/GID must match the host user that owns the bind-mounted .data/
# directory, otherwise the container can't write overlays. Override at
# build time:
#   docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g) backend
RUN set -eux; \
    groupadd -g "${GID}" spark 2>/dev/null \
        || groupmod -n spark "$(getent group ${GID} | cut -d: -f1)" 2>/dev/null \
        || true; \
    useradd -u "${UID}" -g "${GID}" -d /app -s /bin/sh -M spark 2>/dev/null \
        || usermod -l spark -d /app "$(id -un ${UID})" 2>/dev/null \
        || true; \
    mkdir -p /app/.local/share/spark-libre/overlays; \
    chown -R "${UID}:${GID}" /app

USER spark
EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys, urllib.request; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=2).status == 200 else 1)"

CMD ["spark-libre"]
