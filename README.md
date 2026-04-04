# gemmaVllmWorker

Synthcore's self-hosted LLM inference worker — Gemma 4 26B-A4B MoE (AWQ 4-bit) on RunPod Serverless via vLLM.

## What This Is

A RunPod Serverless worker that serves [Google Gemma 4 26B-A4B](https://huggingface.co/google/gemma-4-26b-a4b-it) — a Mixture-of-Experts model with 26B total params but only ~4B active per token. Quantized to 4-bit AWQ to fit on a 24GB GPU, giving 26B-quality output at minimal cost.

| Spec | Value |
|------|-------|
| Model | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| Architecture | MoE — 128 experts, top-8 routing |
| Active params/token | ~4B |
| VRAM | ~13 GB (fits 24GB GPU) |
| Context | Up to 262K (default: 8192) |
| API | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |
| Engine | vLLM 0.19.0 |

## Deploy to RunPod

### Option 1: Pre-built Image (recommended)

```
synthcore/gemma-vllm-worker:latest
```

Set these env vars on your RunPod Serverless endpoint:

| Variable | Value |
|----------|-------|
| `MODEL_NAME` | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| `QUANTIZATION` | `awq` |
| `MAX_MODEL_LEN` | `8192` |
| `GPU_MEMORY_UTILIZATION` | `0.95` |
| `OPENAI_SERVED_MODEL_NAME_OVERRIDE` | `gemma-4-26b-moe` |
| `ENABLE_PREFIX_CACHING` | `true` |

GPU: Any 24GB Ampere/Ada (A10G, L4, RTX 4090).

### Option 2: Build with Model Baked In (faster cold starts)

```bash
export DOCKER_BUILDKIT=1

docker build -t synthcore/gemma-vllm-worker:latest \
  --build-arg MODEL_NAME="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit" \
  --build-arg BASE_PATH="/models" \
  --build-arg QUANTIZATION="awq" \
  .
```

This downloads the model during build so the container starts faster on RunPod (no HuggingFace download at boot).

For gated/private models, pass your HF token as a build secret:

```bash
export HF_TOKEN="hf_xxxxx"
docker build -t synthcore/gemma-vllm-worker:latest \
  --secret id=HF_TOKEN \
  --build-arg MODEL_NAME="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit" \
  --build-arg BASE_PATH="/models" \
  .
```

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

All config is via environment variables. See [docs/configuration.md](docs/configuration.md) for the full reference.

Key variables for this deployment:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | — | HuggingFace model ID |
| `QUANTIZATION` | — | `awq`, `gptq`, or omit for none |
| `MAX_MODEL_LEN` | auto | Max context length (higher = more VRAM for KV cache) |
| `GPU_MEMORY_UTILIZATION` | `0.95` | Fraction of GPU VRAM to use |
| `MAX_CONCURRENCY` | `30` | Concurrent requests per worker |
| `OPENAI_SERVED_MODEL_NAME_OVERRIDE` | model path | Name in OpenAI API responses |
| `ENABLE_PREFIX_CACHING` | `false` | Cache common prefixes across requests |

Any vLLM `AsyncEngineArgs` field can be set by uppercasing its name (e.g., `ENFORCE_EAGER=true`, `ENABLE_CHUNKED_PREFILL=true`).

Copy `.env.example` for local reference:

```bash
cp .env.example .env
```

## Docs

See [docs/README.md](docs/README.md) for full documentation including:

- **Research** — Quantization deep-dive, Gemma 4 architecture, vLLM support status, available quants survey
- **Reference** — Configuration reference, development conventions

## Based On

Forked from [runpod-workers/worker-vllm](https://github.com/runpod-workers/worker-vllm). Core engine architecture (handler, vLLM wrapper, OpenAI compat layer) comes from upstream. Configured and tailored for Gemma 4 MoE serving on Synthcore's infrastructure.
