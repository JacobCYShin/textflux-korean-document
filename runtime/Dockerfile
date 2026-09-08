# syntax=docker/dockerfile:1.7
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime@sha256:ac7c098a81512e719afa5d2d497f812d7db3498f340a4b819c69cb7b3b257126

ARG TEXTFLUX_GIT_SHA=c791924acc4a93d48021c3731a75fada805cc501
LABEL org.opencontainers.image.title="textflux-offline" \
      org.opencontainers.image.source="https://github.com/yyyyyxie/textflux" \
      org.opencontainers.image.revision="${TEXTFLUX_GIT_SHA}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HOME=/opt/textflux/hf-home \
    HF_HUB_CACHE=/opt/textflux/hf-home/hub

WORKDIR /opt/textflux/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY runtime/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-runtime.txt

# TextFlux ships a modified diffusers tree. Install this exact local source,
# rather than pulling an unrelated PyPI diffusers release.
COPY vendor/textflux/ /opt/textflux/app/
RUN python -m pip install --no-cache-dir --no-deps /opt/textflux/app/diffusers

ENV HOME=/opt/textflux \
    XDG_CACHE_HOME=/opt/textflux/cache

COPY runtime/offline_infer.py /opt/textflux/offline_infer.py
RUN mkdir -p /opt/textflux/hf-home/hub /opt/textflux/cache \
    && printf '1' > /opt/textflux/hf-home/hub/version.txt \
    && rm -rf /root/.cache/huggingface

# Checkpoints are intentionally not copied into this image. The runner receives
# their NAS-provided absolute path through TEXTFLUX_MODEL_ROOT or CLI options.

ENTRYPOINT ["python", "/opt/textflux/offline_infer.py"]
