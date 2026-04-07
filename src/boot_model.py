"""
Boot Model — Runtime model download with volume caching.

Checks if model weights already exist at BASE_PATH. If yes, skips download
(network volume, previous boot, or baked image). If no, downloads from HuggingFace.

Works in any environment:
  - RunPod with network volume: /workspace/models persists across stop/resume
  - RunPod without volume: /workspace/models on ephemeral disk, re-downloads on cold start
  - Local dev / other providers: wherever BASE_PATH points
"""

import os
import json
import logging
import shutil

log = logging.getLogger("boot-model")
logging.basicConfig(level=logging.INFO)

BASE_PATH = os.environ.get("BASE_PATH", "/workspace/models")
MODEL_ARGS_PATH = os.path.join(BASE_PATH, "local_model_args.json")
TOKENIZER_PATCH_SRC = "/tmp/tokenizer_config.json"


def ensure_model() -> dict:
    """Download model if not already present at BASE_PATH. Returns model args."""

    # Check if weights already exist (network volume, previous boot, or baked image)
    if os.path.exists(MODEL_ARGS_PATH):
        log.info(f"Model found at {MODEL_ARGS_PATH} — skipping download")
        with open(MODEL_ARGS_PATH) as f:
            args = json.load(f)
        # engine_args.py reads from /local_model_args.json — keep it in sync
        with open("/local_model_args.json", "w") as f:
            json.dump(args, f)
        return args

    log.info(f"No model at {BASE_PATH} — downloading from HuggingFace...")

    # Point HF cache at BASE_PATH so weights land on the volume (if mounted)
    hf_cache = os.path.join(BASE_PATH, "huggingface-cache", "hub")
    os.environ["HF_HOME"] = hf_cache
    os.environ["HUGGINGFACE_HUB_CACHE"] = hf_cache
    os.environ["HF_DATASETS_CACHE"] = os.path.join(BASE_PATH, "huggingface-cache", "datasets")

    os.makedirs(BASE_PATH, exist_ok=True)

    from download_model import download

    model_name = os.environ.get("MODEL_NAME", "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit")
    model_revision = os.environ.get("MODEL_REVISION") or None
    tokenizer_name = os.environ.get("TOKENIZER_NAME") or model_name
    tokenizer_revision = os.environ.get("TOKENIZER_REVISION") or model_revision

    log.info(f"Downloading model: {model_name}")
    model_path = download(model_name, model_revision, "model", hf_cache)

    log.info(f"Downloading tokenizer: {tokenizer_name}")
    tokenizer_path = download(tokenizer_name, tokenizer_revision, "tokenizer", hf_cache)

    # Patch tokenizer_config.json if the vendored patch exists
    if os.path.exists(TOKENIZER_PATCH_SRC):
        dest = os.path.join(tokenizer_path, "tokenizer_config.json")
        shutil.copy(TOKENIZER_PATCH_SRC, dest)
        log.info(f"Patched tokenizer_config.json into {dest}")

    # Write model args (persists on volume for next boot)
    metadata = {
        "MODEL_NAME": model_path,
        "MODEL_REVISION": model_revision,
        "TOKENIZER_NAME": tokenizer_path,
        "TOKENIZER_REVISION": tokenizer_revision,
    }
    metadata = {k: v for k, v in metadata.items() if v not in (None, "")}

    with open(MODEL_ARGS_PATH, "w") as f:
        json.dump(metadata, f)
    with open("/local_model_args.json", "w") as f:
        json.dump(metadata, f)

    log.info(f"Model ready at {BASE_PATH}")
    return metadata


if __name__ == "__main__":
    args = ensure_model()
    print(json.dumps(args, indent=2))
