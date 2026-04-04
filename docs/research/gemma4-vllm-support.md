# Gemma 4 vLLM Support Status

vLLM 0.19.0 (released April 2, 2026) added Gemma 4 support. This doc tracks what landed, what's broken, and what's coming.

## What Shipped in v0.19.0

### PR #38826 — Main Implementation

Author: `lucianommartins` | Merged by: `ywang96` (Roger Wang) | April 2, 2026

+5,051 lines across 20 files. Comprehensive implementation covering:

| Component | File | Lines |
|-----------|------|-------|
| Core text model | `gemma4.py` | +1,239 |
| Multimodal (vision/audio) | `gemma4_mm.py` | +1,341 |
| Shared utilities | `gemma4_utils.py` | +292 |
| Custom RoPE | `gemma4_rope.py` | +84 |
| Tool call parser | `gemma4_tool_parser.py` | +724 |
| Reasoning parser | `gemma4_reasoning_parser.py` | +193 |
| Tests | various | +744 |

Supports: `Gemma4ForCausalLM` with MoE, vision tower, reasoning trace parsing (`<thought>` tags), structured tool use.

### PR #38847 — Day-One Bugfix

The `Gemma4ToolParser.__init__()` was written against an old base class signature. Tool calling was completely broken until this 3-line fix landed same day.

## Known Issues (as of April 4, 2026)

### Critical

| Issue | Problem | Affects |
|-------|---------|---------|
| #38887 | E4B ~9 tok/s on RTX 4090 — heterogeneous head_dims force TRITON_ATTN globally | E4B, consumer GPUs |
| #38886 | E4B weight loading fails — `Gemma4ClippableLinear` `input_max` unrecognized | E4B NVFP4 |
| #38926 | 31B freezes during loading on multi-GPU RTX 6000 PRO | 31B, multi-GPU |

### Medium

| Issue | Problem | Affects |
|-------|---------|---------|
| #38912 | MoE NVFP4 quantization broken — `expert_params_mapping` scale key mismatch | 26B-A4B NVFP4 |
| #38855 | Reasoning parser fails — `<\|channel\|>` tokens stripped before parsing | All variants |
| #38946 | Tool use streaming produces invalid JSON | All variants (streaming) |
| #38910 | Tool parser duplicates HTML tag prefixes in streamed args | All variants (streaming) |

### Low

| Issue | Problem | Affects |
|-------|---------|---------|
| #38918 | Turing GPUs (SM 7.5) can't run — shared memory limits exceeded by head_dim=512 | T4, RTX 2080 Ti |
| #38884 | `torch._dynamo` fails with fake tensors | Edge case |

## Stability by Variant

| Variant | Status | Notes |
|---------|--------|-------|
| 31B dense | Best | Most tested, fewest issues (avoid multi-GPU RTX 6000 PRO) |
| 26B-A4B MoE | Good | Works with AWQ/GPTQ quants. NVFP4 broken (#38912) |
| E4B | Rough | Weight loading issues, severe perf regression on consumer GPUs |
| E2B | Rough | Same issues as E4B |

## Open PRs — What's Coming

| PR | Title | Impact |
|----|-------|--------|
| #38891 | Per-layer attention backend selection | **Big** — lets 83% of layers use FlashAttention instead of Triton fallback. Major perf fix for consumer GPUs |
| #38879 | YOCO fast prefill optimization | **Big** — +39% throughput, -34% TTFT, -27% TPOT on benchmarks |
| #37190 | MoE expert CPU offloading | **Interesting** — 14.8 tok/s at 8.6 GB VRAM by caching 8 experts on GPU |
| #38945 | Fix invalid JSON in tool use streaming | Fixes #38946 |
| #38833 | ROCm: pad MoE intermediate size | AMD GPU support |
| #38824 | ROCm: add head-dim 512 | AMD GPU support |

## Confirmed Working (Our Testing, April 4, 2026)

Tested `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` on RunPod L40S (Ada sm_89):

- **vLLM 0.19.0** + **transformers 5.5.0** — model loads and serves via OpenAI-compatible API
- Quantization format: `compressed-tensors` (auto-detected, do NOT set `QUANTIZATION` env var)
- Engine init: ~127s (model cached on volume), ~160s (first download)
- KV cache: 24.5 GB available on L40S, 106K tokens, 14.2x concurrency at 8192 ctx
- Code generation quality: Good — clean Python output with docstrings, proper algorithms

### vLLM 0.19.0 Breaking Changes We Hit

Three fixes needed in the OpenAI serving layer (all committed to our repo):

1. **`OpenAIServingRender` required** — New object that `OpenAIServingChat` and `OpenAIServingCompletion` depend on. Must be created from `model_config`, `renderer`, `io_processor`, and `model_registry`.
2. **`log_error_stack` moved** — No longer a param on chat/completion constructors. Moved to `OpenAIServingRender`.
3. **`warmup()` is sync** — Was async, now returns `None`. Must call without `await`.

### GPU Compatibility

| GPU Arch | Compute | Status |
|----------|---------|--------|
| Ada (L4, L40S, RTX 4090) | sm_89 | **Works** |
| Ampere (A10G, RTX 3090, A5000) | sm_86 | Expected to work |
| Blackwell (RTX 5090) | sm_12.0 | **FAILS** — Marlin kernel PTX incompatible |
| Turing (T4, RTX 2080 Ti) | sm_75 | **FAILS** — shared memory limits |

## Dependencies

- **vLLM**: >= 0.19.0 (hard requirement)
- **transformers**: >= 5.5.0 (hard requirement — `gemma4` model_type not recognized in older versions)
- **llm-compressor**: Currently pinned to `transformers<=4.57.6`, cannot quantize Gemma 4 natively yet (issue #2562)
