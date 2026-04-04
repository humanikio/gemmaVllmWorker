# Synthcore Worker — Gemma 4 MoE

## Research

Background research informing our model selection, quantization strategy, and deployment approach.

- [Quantization Primer](research/quantization-primer.md) — How INT4/AWQ/GPTQ/FP8 quantization works and why MoE + quant is the sweet spot
- [Gemma 4 Model Family](research/gemma4-model-family.md) — All variants (31B, 26B-A4B MoE, E4B, E2B), architecture details, heterogeneous attention
- [Gemma 4 vLLM Support](research/gemma4-vllm-support.md) — What shipped in v0.19.0, known bugs, stability by variant, upcoming PRs to watch
- [Available Quants](research/available-quants.md) — Survey of quantized gemma-4-26B-A4B-it models on HuggingFace (AWQ, GPTQ, FP8, NVFP4, GGUF)
- [Approach and Future Moves](research/approach-and-future.md) — Our deployment strategy, RunPod config, risk register, and roadmap of vLLM improvements to adopt

## Guides

How to develop, test, and deploy the worker.

- [RunPod SSH Dev Flow](guides/runpod-ssh-dev-flow.md) — Install runpodctl, spin up a GPU pod, SSH in, test the worker on real hardware

## Reference

Upstream worker-vllm documentation (from runpod-workers/worker-vllm).

- [Configuration](configuration.md) — All environment variables and configuration options
- [Conventions](conventions.md) — Development conventions and architecture guide
