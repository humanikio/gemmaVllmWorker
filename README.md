# gemmaVllmWorker

Humanik's self-hosted LLM inference worker — Gemma 4 26B-A4B MoE (AWQ 4-bit) on RunPod Serverless via vLLM.

## What This Is

A RunPod Serverless worker that serves [Google Gemma 4 26B-A4B](https://huggingface.co/google/gemma-4-26b-a4b-it) — a Mixture-of-Experts model with 26B total params but only ~4B active per token. Quantized to 4-bit AWQ (compressed-tensors format) and baked into the Docker image for fast cold starts.

| Spec | Value |
|------|-------|
| Model | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| Architecture | MoE — 128 experts, top-8 routing |
| Active params/token | ~4B |
| VRAM | ~13 GB (fits 24GB GPU) |
| Context | Up to 262K (default: 8192) |
| API | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |
| Engine | vLLM 0.19.0 |
| Quantization format | compressed-tensors (auto-detected by vLLM) |

## Deploy to RunPod

### Build the Image

The model is baked into the image at build time (~7GB download during build). No HuggingFace download needed at runtime.

```bash
export DOCKER_BUILDKIT=1

docker build -t humanik/gemma-vllm-worker:latest .
```

The Dockerfile defaults to `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` with `/models` as the base path. No build args needed for our standard deployment.

### Deploy as Serverless Endpoint

Push the image and create a RunPod Serverless endpoint:

```bash
docker push humanik/gemma-vllm-worker:latest
```

On RunPod, create a serverless endpoint with:
- **Image**: `humanik/gemma-vllm-worker:latest`
- **GPU**: Any 24GB+ Ada or Ampere GPU (L4, RTX 4090, A10G, RTX 3090)
- **Min workers**: 0 (scale to zero)
- **Max workers**: as needed

All configuration is baked into the image. Override via env vars if needed:

| Variable | Baked Default | Description |
|----------|--------------|-------------|
| `MAX_MODEL_LEN` | `8192` | Max context length |
| `GPU_MEMORY_UTILIZATION` | `0.95` | Fraction of GPU VRAM to use |
| `MAX_CONCURRENCY` | `30` | Concurrent requests per worker |
| `OPENAI_SERVED_MODEL_NAME_OVERRIDE` | `gemma-4-26b-moe` | Model name in API responses |
| `ENABLE_PREFIX_CACHING` | `true` | Cache common prefixes across requests |

**Do NOT set `QUANTIZATION`** — the model uses compressed-tensors format and vLLM auto-detects it. Setting `QUANTIZATION=awq` will cause a validation error.

### GPU Compatibility

| GPU | Arch | Status |
|-----|------|--------|
| L4 / L40S | Ada (sm_89) | **Works** (tested on L40S) |
| RTX 4090 | Ada (sm_89) | **Works** |
| A10G / RTX 3090 / A5000 | Ampere (sm_86) | Expected to work |
| RTX 5090 | Blackwell (sm_12.0) | **FAILS** — Marlin kernel incompatible |
| T4 / RTX 2080 Ti | Turing (sm_75) | **FAILS** — shared memory limits |

## Usage

### OpenAI-Compatible API

Point any OpenAI SDK client at your RunPod endpoint:

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-runpod-api-key",
    base_url="https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1",
)

response = client.chat.completions.create(
    model="gemma-4-26b-moe",
    messages=[{"role": "user", "content": "Write a Python fibonacci generator"}],
    temperature=0.3,
    max_tokens=500,
)
print(response.choices[0].message.content)
```

Streaming:

```python
stream = client.chat.completions.create(
    model="gemma-4-26b-moe",
    messages=[{"role": "user", "content": "Explain async/await in Python"}],
    max_tokens=300,
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

List available models:

```python
models = client.models.list()
print([m.id for m in models])
```

### curl

```bash
curl https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d '{
    "model": "gemma-4-26b-moe",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

### Native vLLM API (non-OpenAI)

For direct vLLM access without the OpenAI wrapper:

```json
{
  "input": {
    "prompt": "Explain what a neural network is.",
    "sampling_params": {
      "temperature": 0.7,
      "max_tokens": 200
    },
    "stream": true
  }
}
```

Or with chat messages (auto-applies the model's chat template):

```json
{
  "input": {
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Write a binary search in Rust."}
    ],
    "sampling_params": {
      "temperature": 0.3,
      "max_tokens": 500
    }
  }
}
```

## Configuration

All config is baked into the image via env vars. Override at runtime if needed. See [docs/configuration.md](docs/configuration.md) for the full reference.

Any vLLM `AsyncEngineArgs` field can be set by uppercasing its name (e.g., `ENFORCE_EAGER=true`, `ENABLE_CHUNKED_PREFILL=true`).

## Docs

See [docs/README.md](docs/README.md) for full documentation:

- **Research** — Quantization deep-dive, Gemma 4 architecture, vLLM support status, available quants survey
- **Guides** — RunPod SSH dev flow for GPU pod testing
- **Reference** — Configuration reference, development conventions

## Based On

Forked from [runpod-workers/worker-vllm](https://github.com/runpod-workers/worker-vllm). Core engine architecture (handler, vLLM wrapper, OpenAI compat layer) comes from upstream. Configured and tailored for Gemma 4 MoE serving on Humanik's infrastructure.
