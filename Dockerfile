FROM nvidia/cuda:12.6.3-base-ubuntu22.04

# Retry apt-get update — NVIDIA mirror can be mid-sync during builds
RUN apt-get update -y || (sleep 5 && apt-get update -y) \
    && apt-get install -y python3-pip

RUN ldconfig /usr/local/cuda-12.6/compat/

# Install vLLM 0.19.0 with FlashInfer (Gemma 4 support requires >= 0.19.0)
# vLLM 0.19.0 requires torch==2.10.0 which is available for cu126, cu128, cu129.
# CUDA 12.6 is the lowest version that supports torch 2.10.0 and has broad
# GPU driver compatibility (RTX 4090 driver 560+, L40S, A100, H100).
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install "vllm[flashinfer]==0.19.0" --extra-index-url https://download.pytorch.org/whl/cu126

# Install additional Python dependencies (after vLLM to avoid PyTorch version conflicts)
COPY builder/requirements.txt /requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade -r /requirements.txt

# ── Model configuration ─────────────────────────────────────────────
# Model weights are NOT baked into the image.
# On first boot, boot_model.py downloads weights to /workspace/models/
# (network volume, NVMe SSD). Subsequent boots reuse cached weights.
# This keeps the image at ~10GB instead of ~25GB.
ARG MODEL_NAME="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
ARG TOKENIZER_NAME=""
ARG MODEL_REVISION=""
ARG TOKENIZER_REVISION=""

ENV MODEL_NAME=$MODEL_NAME \
    MODEL_REVISION=$MODEL_REVISION \
    TOKENIZER_NAME=$TOKENIZER_NAME \
    TOKENIZER_REVISION=$TOKENIZER_REVISION \
    BASE_PATH="/workspace/models" \
    HF_DATASETS_CACHE="/workspace/models/huggingface-cache/datasets" \
    HUGGINGFACE_HUB_CACHE="/workspace/models/huggingface-cache/hub" \
    HF_HOME="/workspace/models/huggingface-cache/hub" \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    # Suppress Ray metrics agent warnings
    RAY_METRICS_EXPORT_ENABLED=0 \
    RAY_DISABLE_USAGE_STATS=1 \
    # Prevent rayon thread pool panic in containers
    TOKENIZERS_PARALLELISM=false \
    RAYON_NUM_THREADS=4

# ── Runtime defaults ────────────────────────────────────────────────
# Do NOT set QUANTIZATION — model uses compressed-tensors, vLLM auto-detects
# Requires 48GB+ VRAM GPU (L40S, L40, A6000, A100). 24GB cards OOM on warmup.
ENV PORT=80 \
    MAX_MODEL_LEN=100000 \
    GPU_MEMORY_UTILIZATION=0.95 \
    ENABLE_PREFIX_CACHING=true \
    OPENAI_SERVED_MODEL_NAME_OVERRIDE=gemma-4-26b-moe \
    MAX_CONCURRENCY=30 \
    PYTHONPATH="/:/vllm-workspace"

COPY src /src
COPY model/tokenizer_config.json /tmp/tokenizer_config.json

# No build-time model download — weights are downloaded at runtime to
# the network volume (/workspace/models/) by boot_model.py.
# See docs/humanik-cloud/idle-timeout.md for the volume architecture.

EXPOSE 80
CMD ["python3", "/src/server.py"]
