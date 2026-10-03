# Chatterbox TTS job image (GPU). Separate from LongCat: Chatterbox pins transformers==5.2.0,
# LongCat pins transformers==4.41.0.
# Blackwell GPUs (sm_120) need torch >= 2.7 + CUDA 12.8: set TTS_BASE_IMAGE and TTS_TORCH_OVERRIDE
# (see .env.example). Chatterbox itself pins torch==2.6.0, so the override upgrades torch afterwards.
ARG BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
FROM ${BASE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*
# resemble-ai/chatterbox pinned (pyproject 0.1.7; English ChatterboxTTS + Turbo)
ARG CHATTERBOX_REF=5de7a54aa4e5e2baadb0182dde554908b48b85c2
RUN pip install --no-cache-dir "chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox@${CHATTERBOX_REF}"
# e.g. "torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128" (empty = keep 2.6.0)
ARG TORCH_OVERRIDE=""
RUN if [ -n "$TORCH_OVERRIDE" ]; then pip install --no-cache-dir $TORCH_OVERRIDE; fi
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY wwnn ./wwnn
COPY resource ./resource
RUN pip install --no-cache-dir --no-deps -e . && pip install --no-cache-dir "loguru>=0.7,<0.8" feedparser pillow requests
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "wwnn.tts.synth", "--help"]
