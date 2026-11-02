ARG PYTHON_IMAGE=images-kcs.ke.com/python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

COPY debian.sources /etc/apt/sources.list.d/debian.sources

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VOICE_SMITHS_HOST=0.0.0.0 \
    VOICE_SMITHS_PORT=8765 \
    VOICE_SMITHS_DATA_DIR=/data \
    VOICE_SMITHS_UPLOAD_DIR=/data/uploads \
    VOICE_SMITHS_AUDIO_DIR=/data/audio

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY backend/ ./backend/
RUN mkdir -p /data/uploads /data/audio

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('VOICE_SMITHS_PORT', '8765') + '/api/health', timeout=3)"]

CMD ["python", "app.py"]
