# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build NsJail from source.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS nsjail-builder

ARG NSJAIL_VERSION=3.4

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        build-essential \
        bison \
        flex \
        pkg-config \
        libprotobuf-dev \
        protobuf-compiler \
        libnl-route-3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch "${NSJAIL_VERSION}" --depth 1 \
        https://github.com/google/nsjail.git /nsjail \
    && make -C /nsjail \
    && strip /nsjail/nsjail

# ---------------------------------------------------------------------------
# Stage 2: runtime image.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime

# Runtime shared libraries that the nsjail binary links against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libprotobuf32 \
        libnl-route-3-200 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nsjail-builder /nsjail/nsjail /usr/local/bin/nsjail

WORKDIR /app

COPY pyproject.toml README.md ./
COPY aisnekbox ./aisnekbox
COPY config ./config

RUN pip install --no-cache-dir ".[server]"

# The official python image ships the interpreter under /usr/local/bin, so
# point the default executable there (the config default targets /usr/bin for
# Debian-style hosts).
ENV AISNEKBOX_HOST=0.0.0.0 \
    AISNEKBOX_PORT=8060 \
    AISNEKBOX_NSJAIL_BINARY=/usr/local/bin/nsjail \
    AISNEKBOX_NSJAIL_CONFIG=/app/config/nsjail.cfg \
    AISNEKBOX_DEFAULT_EXECUTABLE=/usr/local/bin/python3

EXPOSE 8060

CMD ["gunicorn", "aisnekbox.api.app:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8060", \
     "--workers", "2"]
