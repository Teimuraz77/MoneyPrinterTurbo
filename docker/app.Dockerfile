# Image for the long-running bot and the CPU job containers (compositor, uploader).
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY app ./app
COPY wwnn ./wwnn
COPY resource ./resource
ARG EXTRAS=bot,upload
RUN pip install --no-cache-dir -e ".[${EXTRAS}]"
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "wwnn", "--help"]
