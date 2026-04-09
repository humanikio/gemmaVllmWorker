# gemmaVllmWorker — Documentation

## Humanik Cloud Integration

Optional features that activate when deployed via [Humanik Cloud](https://humanik.io). Completely inert in standalone mode — the worker runs as a standard OpenAI-compatible server without them.

- [Overview](humanik-cloud/README.md) — Architecture, env vars, what activates and what doesn't
- [HMAC Auth](humanik-cloud/hmac-auth.md) — Control plane signature verification on all inference endpoints
- [Heartbeat](humanik-cloud/heartbeat.md) — Redis-based instance discovery, status lifecycle, load tracking
- [Idle Timeout](humanik-cloud/idle-timeout.md) — Scale-to-zero via configurable idle auto-termination

## Guides

How to develop, test, and deploy the worker.

- [RunPod SSH Dev Flow](guides/runpod-ssh-dev-flow.md) — Install runpodctl, spin up a GPU pod, SSH in, test the worker on real hardware
- [RunPod Hub Cold Start](guides/runpod-hub-cold-start.md) — Why `/ping` must stay responsive during model load, and how `run_in_executor` keeps the event loop free

## Research

Background research informing our model selection, quantization strategy, and deployment approach.

- [Quantization Primer](research/quantization-primer.md) — How INT4/AWQ/GPTQ/FP8 quantization works and why MoE + quant is the sweet spot
- [Gemma 4 Model Family](research/gemma4-model-family.md) — All variants (31B, 26B-A4B MoE, E4B, E2B), architecture details, heterogeneous attention
- [Gemma 4 vLLM Support](research/gemma4-vllm-support.md) — What shipped in v0.19.0, known bugs, stability by variant, upcoming PRs to watch
- [Available Quants](research/available-quants.md) — Survey of quantized models on HuggingFace, why we picked cyankiwi AWQ, missing chat template fix
- [Approach and Future Moves](research/approach-and-future.md) — Deployment strategy, GPU compat matrix, performance baseline, lessons learned, roadmap

## Model Assets (`model/`)

Build-time assets patched into the Docker image.

- **`tokenizer_config.json`** — Complete tokenizer config with chat template, sourced from [unsloth/gemma-4-26B-A4B-it](https://huggingface.co/unsloth/gemma-4-26B-A4B-it). The `cyankiwi` AWQ quant stripped the `chat_template` field required for `/v1/chat/completions`. See [Available Quants — Missing Chat Template](research/available-quants.md#missing-chat-template).

## Reference

- [Configuration](configuration.md) — All environment variables and configuration options
- [Conventions](conventions.md) — Development conventions and architecture guide
