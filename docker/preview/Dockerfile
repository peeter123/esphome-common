# Image for bin/esphome-preview.py: ESPHome at the project's pinned version,
# installed from the one-line requirements.txt the tool generates, with the
# native toolchain the `host` platform needs. Build context: this file and that
# generated requirements.txt only.
FROM python:3.13-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ccache \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# /cache is a named volume: build output, PlatformIO packages and ccache.
ENV ESPHOME_DATA_DIR=/cache/data \
    PLATFORMIO_CORE_DIR=/cache/platformio \
    CCACHE_DIR=/cache/ccache \
    ESPHOME_PREFDIR=/tmp/prefs

WORKDIR /work
