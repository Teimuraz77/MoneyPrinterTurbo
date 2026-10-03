# LongCat-Video-Avatar 1.5 job image (GPU). Code pinned to meituan-longcat/LongCat-Video@6b3f4b8;
# weights are mounted read-only at /models (see README "Model downloads").
#
# Two toolchains via build args (docker-compose.yml passes them from .env):
#   default (Ampere/Ada/Hopper: 3090, 4090, A6000, L40S, A100, H100): CUDA 12.4 + torch 2.6.0, upstream's pin
#   Blackwell (sm_120: RTX PRO 4000/6000 Blackwell = Hetzner GEX45/GEX131, RTX 50xx): needs CUDA >= 12.8
#     and torch >= 2.7 -> LONGCAT_CUDA_IMAGE=nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04,
#     LONGCAT_TORCH_VERSION=2.7.0, LONGCAT_TORCHVISION_VERSION=0.22.0, LONGCAT_TORCHAUDIO_VERSION=2.7.0,
#     LONGCAT_TORCH_INDEX=https://download.pytorch.org/whl/cu128, LONGCAT_TORCHAO_VERSION=0.11.0
#     (deviates from upstream's torch pin: NOT validated by upstream, verify in the first GPU session).
ARG CUDA_IMAGE=nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04
FROM ${CUDA_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3.10-dev python3-pip git ffmpeg libsndfile1 fonts-dejavu-core \
    && ln -sf /usr/bin/python3.10 /usr/bin/python && rm -rf /var/lib/apt/lists/*
ARG LONGCAT_REF=6b3f4b8582a8bc3f20f795735f5383716c4ba794
RUN git clone https://github.com/meituan-longcat/LongCat-Video /opt/LongCat-Video \
    && cd /opt/LongCat-Video && git checkout ${LONGCAT_REF}
ARG TORCH_VERSION=2.6.0
ARG TORCHVISION_VERSION=0.21.0
ARG TORCHAUDIO_VERSION=2.6.0
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir torch==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION} \
      torchaudio==${TORCHAUDIO_VERSION} --index-url ${TORCH_INDEX}
# flash-attn: prebuilt wheel for torch 2.6 (default); compiled from source for other torch versions
# (slow, ~20-60 min). MAX_JOBS limits RAM use during the build.
ARG FLASH_ATTN_VERSION=2.7.4.post1
ARG MAX_JOBS=8
RUN pip install --no-cache-dir ninja packaging psutil wheel setuptools \
    && MAX_JOBS=${MAX_JOBS} pip install --no-cache-dir flash_attn==${FLASH_ATTN_VERSION} --no-build-isolation
# Upstream requirements minus: torch/flash-attn (installed above), sympy (torch pins its own), packages
# the avatar path never imports (streamlit UI, the OpenAI client of the optional prompt enhancer,
# triton client) and a bogus 'libsndfile1' wheel (the system lib is installed via apt).
RUN cd /opt/LongCat-Video && { cat requirements.txt; echo; cat requirements_avatar.txt; } \
      | grep -v -E '^(torch|flash-attn|sympy|streamlit|openai|tritonserverclient|libsndfile1)==' > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt \
    && python -c "import torch; assert torch.__version__.startswith('${TORCH_VERSION}'), torch.__version__"
# Optional experimental 24 GB path: community PR #115 low-VRAM script (unmerged, pinned head).
ARG WITH_LOWMEM_PR=0
ARG LOWMEM_PR_SHA=f92256a4bcf32898592e2d3374b7ca0525fd5761
ARG TORCHAO_VERSION=0.10.0
RUN if [ "$WITH_LOWMEM_PR" = "1" ]; then \
      cd /opt/LongCat-Video && git fetch --depth 1 origin ${LOWMEM_PR_SHA} \
      && git checkout ${LOWMEM_PR_SHA} -- run_demo_avatar_single_lowmem.py \
      && pip install --no-cache-dir torchao==${TORCHAO_VERSION} accelerate ; fi
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
