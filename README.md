# gemmaVllmWorker

[![Deploy on RunPod](https://api.runpod.io/badge/humanikio/gemmaVllmWorker)](https://console.runpod.io/hub/humanikio/gemmaVllmWorker)

Self-hosted Gemma 4 26B MoE inference — OpenAI-compatible API with tool calling, SSE streaming, and optional Humanik Cloud orchestration.

## What This Is

A GPU inference worker serving [Google Gemma 4 26B-A4B](https://huggingface.co/google/gemma-4-26b-a4b-it) via vLLM with full OpenAI API compatibility. Runs standalone on any GPU or as a managed pool service through Humanik Cloud.

| Spec | Value |
|------|-------|
| Model | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| Architecture | MoE — 128 experts, top-8 routing (~4B active params/token) |
| Min VRAM | 48GB (24GB cards OOM on CUDA graph warmup) |
| Context | 60K default (configurable, model supports up to 128K) |
| API | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |
| Tool Calling | Native via vLLM `gemma4` parser |
| Streaming | SSE (`text/event-stream`) |
| Engine | vLLM 0.19.0 + FlashInfer |
| CUDA | 12.6 (driver ≥560 required) |
| Image | ~10GB slim (model weights downloaded at runtime) |

## Two Ways to Run

### 1. Standalone (Any GPU Provider)

Deploy directly on RunPod, AWS, GCP, or bare metal. The worker runs as a standard HTTP server with no external dependencies.

```bash
docker build -t gemmavllmworker .
docker run --gpus all -p 8000:8000 gemmavllmworker
```

Model weights are downloaded on first boot to `/workspace/models/` (~15GB from HuggingFace). Subsequent boots reuse cached weights if the volume persists.

### 2. Humanik Cloud (Managed Pool Service)

When deployed through [Humanik Cloud](https://humanik.cloud), the worker activates additional features:

- **HMAC Auth** — Control plane signature verification on all endpoints
- **Heartbeat** — Redis-based instance discovery for ALB routing
- **Idle Timeout** — Auto-pause pods after configurable idle period
- **Pause/Resume** — Stopped pods resume in ~2:45 (vs ~12 min cold start)
- **Pool Service** — Shared across all tenants, no per-user GPU allocation
- **Tool Calling** — Full OpenAI tool_calls support via vLLM's `gemma4` parser
- **SSE Streaming** — End-to-end through the Nexus proxy chain

These features activate automatically when Humanik Cloud env vars are present (`NEXUS_TENANT_ID`, `NEXUS_SERVICE_ID`, `NEXUS_INSTANCE_ID`, `NEXUS_REDIS_URL`). Without them, the worker runs as a plain vLLM server.

#### Humanik Cloud Architecture

```
Client → NexusAPI → Control Plane → ALB → RunPod Pod (this worker)
                                      ↓
                                 Redis Registry (heartbeat, status, routing)
```

The worker reports health via Redis heartbeats every 10s. The ALB routes requests to healthy instances. On idle timeout, the worker signals the CP which pauses the pod (preserves disk). On the next request, the ALB resumes the paused pod (~2:45 warm start).

See [docs/humanik-cloud/](docs/humanik-cloud/) for the full integration docs.

## GPU Compatibility

| GPU | VRAM | Status |
|-----|------|--------|
| RTX A6000 | 48GB | **Primary** — tested, confirmed working |
| L40S | 48GB | **Works** — tested |
| L40 | 48GB | Expected to work (same Ada arch) |
| A100 | 80GB | Expected to work |
| RTX 4090 | 24GB | **OOM** — CUDA graph warmup exceeds VRAM |
| RTX 5090 | 32GB | **Incompatible** — Blackwell Marlin kernel PTX issue |

## Configuration

All config via environment variables. Override at pod creation or in docker run.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_MODEL_LEN` | `8192` | Max context length (set to `60000` via Humanik Cloud runtimeEnv) |
| `GPU_MEMORY_UTILIZATION` | `0.95` | Fraction of GPU VRAM to use |
| `MAX_CONCURRENCY` | `30` | Concurrent requests per worker |
| `OPENAI_SERVED_MODEL_NAME_OVERRIDE` | `gemma-4-26b-moe` | Model name in API responses |
| `ENABLE_PREFIX_CACHING` | `true` | Cache common prefixes across requests |
| `BASE_PATH` | `/workspace/models` | Where model weights are stored/downloaded |

### Tool Calling

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_AUTO_TOOL_CHOICE` | `false` | Set `true` to accept `tool_choice: "auto"` |
| `TOOL_CALL_PARSER` | — | Set to `gemma4` for native Gemma tool call parsing |

Gemma 4 uses its own tool call format (`<|tool_call>call:name{args}<tool_call|>`) — vLLM's built-in `gemma4` parser converts this to standard OpenAI `tool_calls`. Do NOT use `hermes` — Gemma is not Hermes-compatible.

### Humanik Cloud Settings (injected by control plane)

| Variable | Description |
|----------|-------------|
| `NEXUS_TENANT_ID` | Tenant ID for this instance |
| `NEXUS_SERVICE_ID` | Service ID |
| `NEXUS_INSTANCE_ID` | Unique instance identifier |
| `NEXUS_REDIS_URL` | Redis URL for heartbeat registry |
| `CP_INSTANCE_HMAC_SECRET` | HMAC secret for request signing |
| `IDLE_TIMEOUT_MINUTES` | Minutes before auto-pause (0 = persistent) |

**Do NOT set `QUANTIZATION`** — the model uses compressed-tensors format, vLLM auto-detects it.

See [docs/configuration.md](docs/configuration.md) for the full reference including all vLLM engine args.

## Usage

### curl

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-26b-moe",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

### With Tool Calling

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-26b-moe",
    "messages": [{"role": "user", "content": "List files in /workspace"}],
    "tools": [{"type": "function", "function": {"name": "list_files", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
    "tool_choice": "auto"
  }'
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

response = client.chat.completions.create(
    model="gemma-4-26b-moe",
    messages=[{"role": "user", "content": "Write a Python fibonacci generator"}],
    max_tokens=500,
)
print(response.choices[0].message.content)
```

### Via Humanik Cloud (Pool Service)

```bash
curl https://api.humanik.cloud/api/v1/proxy/v1/chat/completions \
  -H "Authorization: Bearer $NEXUS_API_KEY" \
  -H "X-Service-Id: gemmaWorker" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma-4-26b-moe", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Model Weights

Weights are NOT baked into the Docker image. On first boot, `boot_model.py` downloads from HuggingFace to `BASE_PATH` (~15GB, ~5 min). Subsequent boots on the same volume skip the download.

- **With persistent volume:** Download once, reuse across restarts
- **Without volume:** Re-downloads on each cold start
- **Resume from pause:** No download needed (container disk preserved)

## Measured Timings (RTX A6000)

| Phase | Time |
|-------|------|
| Cold start (first boot) | ~12-15 min |
| Cold start (cached image) | ~7-10 min |
| Resume from pause | ~2:45 |
| Warm routing | <1s |
| First request (lazy engine init) | ~20s |

## Shutdown & Signals

The worker handles shutdown signals differently based on the reason:

| Signal | Action | Redis |
|--------|--------|-------|
| Idle timeout | Signal CP `idle-timeout` → CP pauses pod | Hash preserved for resume |
| SIGTERM | Signal CP `shutdown` → CP destroys pod | Deregistered |
| CUDA crash | Signal CP `unhealthy` → CP destroys pod | Deregistered |

A `_shutdown_signaled` guard prevents duplicate signals — after idle-timeout, the subsequent SIGTERM from RunPod's `stopPod` is suppressed so the CP doesn't accidentally destroy the just-paused pod.

## Docs

- [Humanik Cloud Integration](docs/humanik-cloud/) — HMAC auth, heartbeat, idle timeout
- [Configuration Reference](docs/configuration.md) — All env vars and vLLM engine args
- [Research](docs/research/) — Quantization, Gemma 4 architecture, available quants
- [Guides](docs/guides/) — RunPod SSH dev flow

## Based On

Forked from [runpod-workers/worker-vllm](https://github.com/runpod-workers/worker-vllm). Core vLLM serving architecture from upstream. Rebuilt for Gemma 4 MoE with runtime model download, pause/resume lifecycle, and [Humanik Cloud](https://humanik.cloud) orchestration.
