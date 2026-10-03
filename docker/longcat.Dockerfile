# LongCat-Video-Avatar 1.5 job image (GPU). Code pinned to meituan-longcat/LongCat-Video@6b3f4b8;
# weights are mounted read-only at /models (see README "Model downloads").
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3.10-dev python3-pip git ffmpeg libsndfile1 fonts-dejavu-core \
    && ln -sf /usr/bin/python3.10 /usr/bin/python && rm -rf /var/lib/apt/lists/*
ARG LONGCAT_REF=6b3f4b8582a8bc3f20f795735f5383716c4ba794
RUN git clone https://github.com/meituan-longcat/LongCat-Video /opt/LongCat-Video \
    && cd /opt/LongCat-Video && git checkout ${LONGCAT_REF}
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
      --index-url https://download.pytorch.org/whl/cu124
# flash-attn compiles against torch (slow, ~20-40 min). MAX_JOBS limits RAM use during the build.
ARG MAX_JOBS=8
RUN pip install --no-cache-dir ninja packaging psutil \
    && MAX_JOBS=${MAX_JOBS} pip install --no-cache-dir flash_attn==2.7.4.post1 --no-build-isolation
# Upstream requirements minus packages the avatar path never imports (streamlit UI, the OpenAI
# client used only by the optional prompt enhancer, triton client, a bogus 'libsndfile1' wheel).
RUN cd /opt/LongCat-Video && { cat requirements.txt; echo; cat requirements_avatar.txt; } \
      | grep -v -E '^(torch|flash-attn|streamlit|openai|tritonserverclient|libsndfile1)==' > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt
# Optional experimental 24 GB path: community PR #115 low-VRAM script (unmerged, pinned head).
ARG WITH_LOWMEM_PR=0
ARG LOWMEM_PR_SHA=f92256a4bcf32898592e2d3374b7ca0525fd5761
RUN if [ "$WITH_LOWMEM_PR" = "1" ]; then \
      cd /opt/LongCat-Video && git fetch --depth 1 origin ${LOWMEM_PR_SHA} \
      && git checkout ${LOWMEM_PR_SHA} -- run_demo_avatar_single_lowmem.py \
      && pip install --no-cache-dir torchao==0.10.0 accelerate ; fi
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY wwnn ./wwnn
COPY resource ./resource
RUN pip install --no-cache-dir --no-deps -e . && pip install --no-cache-dir feedparser requests pillow
# Write run_demo_avatar_single_audio_to_video_wwnn.py (fails the build if upstream changed).
RUN python -m wwnn.avatar.patch_longcat /opt/LongCat-Video
ENV LONGCAT_REPO_DIR=/opt/LongCat-Video PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
CMD ["python", "-m", "wwnn.avatar.runner", "--help"]
