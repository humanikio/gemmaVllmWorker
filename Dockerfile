FROM nvidia/cuda:12.9.1-base-ubuntu22.04

RUN apt-get update -y \
    && apt-get install -y python3-pip

RUN ldconfig /usr/local/cuda-12.9/compat/

# Install vLLM 0.19.0 with FlashInfer (Gemma 4 support requires >= 0.19.0)
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install "vllm[flashinfer]==0.19.0" --extra-index-url https://download.pytorch.org/whl/cu129

# Install additional Python dependencies (after vLLM to avoid PyTorch version conflicts)
COPY builder/requirements.txt /requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade -r /requirements.txt

# ── Model configuration ─────────────────────────────────────────────
# Model is baked into the image at build time for fastest cold starts.
# The download_model.py script pulls weights from HuggingFace during build.
ARG MODEL_NAME="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
ARG TOKENIZER_NAME=""
ARG BASE_PATH="/models"
ARG MODEL_REVISION=""
ARG TOKENIZER_REVISION=""

ENV MODEL_NAME=$MODEL_NAME \
    MODEL_REVISION=$MODEL_REVISION \
    TOKENIZER_NAME=$TOKENIZER_NAME \
    TOKENIZER_REVISION=$TOKENIZER_REVISION \
    BASE_PATH=$BASE_PATH \
    HF_DATASETS_CACHE="${BASE_PATH}/huggingface-cache/datasets" \
    HUGGINGFACE_HUB_CACHE="${BASE_PATH}/huggingface-cache/hub" \
    HF_HOME="${BASE_PATH}/huggingface-cache/hub" \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    # Suppress Ray metrics agent warnings
    RAY_METRICS_EXPORT_ENABLED=0 \
    RAY_DISABLE_USAGE_STATS=1 \
    # Prevent rayon thread pool panic in containers
    TOKENIZERS_PARALLELISM=false \
    RAYON_NUM_THREADS=4

# ── Runtime defaults ────────────────────────────────────────────────
# Do NOT set QUANTIZATION — model uses compressed-tensors, vLLM auto-detects
ENV MAX_MODEL_LEN=8192 \
    GPU_MEMORY_UTILIZATION=0.95 \
    ENABLE_PREFIX_CACHING=true \
    OPENAI_SERVED_MODEL_NAME_OVERRIDE=gemma-4-26b-moe \
    MAX_CONCURRENCY=30 \
    PYTHONPATH="/:/vllm-workspace"

COPY src /src

# Download model weights at build time (bake into image)
RUN --mount=type=secret,id=HF_TOKEN,required=false \
    if [ -f /run/secrets/HF_TOKEN ]; then \
    export HF_TOKEN=$(cat /run/secrets/HF_TOKEN); \
    fi && \
    python3 /src/download_model.py

# Patch tokenizer_config.json — the cyankiwi AWQ quant stripped the chat_template.
# Download the complete config from unsloth's ungated mirror and overwrite.
RUN python3 -c "\
import json, shutil; \
from huggingface_hub import hf_hub_download; \
d = json.load(open('/local_model_args.json')); \
dest = d['TOKENIZER_NAME'] + '/tokenizer_config.json'; \
src = hf_hub_download('unsloth/gemma-4-26B-A4B-it', 'tokenizer_config.json'); \
shutil.copy(src, dest); \
print(f'Patched chat template into {dest}') \
"

EXPOSE 8000
CMD ["python3", "/src/server.py"]
