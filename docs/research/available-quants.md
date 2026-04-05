# Available Quantized Models — Gemma 4 26B-A4B-IT

Surveyed April 4, 2026. Focus on the MoE variant since that's our target.

## vLLM-Compatible (what we can use)

### AWQ — Best Option Right Now

| Model ID | Bits | VRAM | Downloads | Format |
|----------|------|------|-----------|--------|
| `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` | 4 | ~13 GB | 15K | compressed-tensors |
| `cyankiwi/gemma-4-26B-A4B-it-AWQ-8bit` | 8 | ~26 GB | 102 | compressed-tensors |
| `lcu0312/gemma-4-26B-A4B-it-AWQ-4bit` | 4 | ~13 GB | 97 | compressed-tensors |

**Recommendation**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` — highest download count, proven to work.

### GPTQ

| Model ID | Bits | VRAM | Downloads | Notes |
|----------|------|------|-----------|-------|
| `raydelossantos/gemma-4-26B-A4B-it-GPTQ-Int4` | 4 | ~13 GB | 0 | Brand new (Apr 4) |
| `raydelossantos/gemma-4-26B-A4B-it-GPTQ-Int4-v2` | 4 | ~13 GB | 0 | Updated same day |

**Status**: Too new to trust. Zero downloads. GPTQ tooling for Gemma 4 is still maturing (llm-compressor blocked on transformers pin).

### FP8

| Model ID | VRAM | Downloads | Notes |
|----------|------|-----------|-------|
| `protoLabsAI/gemma-4-26B-A4B-it-FP8` | ~26 GB | 4.6K | FP8 dynamic |
| `leon-se/gemma-4-26B-A4B-it-FP8-Dynamic` | ~26 GB | 210 | compressed-tensors |

**Status**: Good quality but still needs a 40 GB+ GPU. Defeats our cost goal.

### NVFP4

| Model ID | VRAM | Downloads | Notes |
|----------|------|-----------|-------|
| `bg-digitalservices/Gemma-4-26B-A4B-it-NVFP4` | ~13 GB | 3.1K | W4A4, Blackwell/Hopper only |

**Status**: Broken in vLLM 0.19.0 (issue #38912, scale key mismatch). Also requires H100/B200 GPUs.

### Intel AutoRound

| Model ID | VRAM | Downloads | Notes |
|----------|------|-----------|-------|
| `Intel/gemma-4-26B-A4B-it-int4-mixed-AutoRound` | ~13 GB | 1.7K | Mixed-precision INT4 |
| `Intel/gemma-4-26B-A4B-it-int4-AutoRound` | ~13 GB | 713 | Standard INT4 |

**Status**: Untested with vLLM. Interesting mixed-precision approach but unproven for our stack.

## Not vLLM-Compatible (reference only)

### GGUF (llama.cpp / Ollama)

| Model ID | Downloads | Notes |
|----------|-----------|-------|
| `unsloth/gemma-4-26B-A4B-it-GGUF` | 301K | Most popular overall |
| `lmstudio-community/gemma-4-26B-A4B-it-GGUF` | 202K | High adoption |
| `bartowski/google_gemma-4-26B-A4B-it-GGUF` | 32K | imatrix |
| `ggml-org/gemma-4-26B-A4B-it-GGUF` | 23K | Official ggml |

The 500K+ combined GGUF downloads confirm strong community adoption of this model. GGUF is not usable with vLLM though.

### MLX (Apple Silicon)

| Model ID | Downloads |
|----------|-----------|
| `mlx-community/gemma-4-26b-a4b-it-4bit` | 16K |

## Decision

**Target model**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit`

- 4-bit AWQ = ~13 GB VRAM
- Fits on 24 GB GPUs (A10G, RTX 4090, L4)
- 15K downloads — community validated
- `compressed-tensors` format — native to vLLM, auto-detected

### Important: compressed-tensors Format

This model is AWQ-quantized but stored in **compressed-tensors** format (not raw AWQ safetensors). vLLM auto-detects this from the model's `config.json`. **Do NOT set `QUANTIZATION=awq`** — it will cause a validation error:

```
Quantization method specified in the model config (compressed-tensors) does not match
the quantization method specified in the `quantization` argument (awq).
```

Just set `MODEL_NAME` and let vLLM handle quantization detection.

### Missing Chat Template

The `cyankiwi` quant also stripped the `chat_template` field from `tokenizer_config.json`. This is a Jinja2 template (~12K chars) that tells vLLM how to format chat messages into the token format the model expects — system/user/assistant turns, tool call syntax, thinking blocks, multimodal placeholders, etc.

Without it, `/v1/chat/completions` fails with:
```
As of transformers v4.44, default chat template is no longer allowed
```

**Fix**: We vendor the complete `tokenizer_config.json` from Google's original model (sourced from [unsloth/gemma-4-26B-A4B-it](https://huggingface.co/unsloth/gemma-4-26B-A4B-it), an ungated mirror) in the `model/` directory. The Dockerfile patches it into the model snapshot at build time, overwriting the incomplete version from `cyankiwi`.

The chat template is model-family-level — identical between the original Google model, the unsloth mirror, and any quant. Quantization only changes weight precision, not tokenizer behavior. This is a safe patch.

If we ever switch quant providers, check whether the new quant includes `chat_template` in its `tokenizer_config.json`. If it does, the `model/` override can be removed.

### Confirmed Working (April 5, 2026)

Tested on RunPod L40S (48GB, Ada sm_89) with vLLM 0.19.0 + transformers 5.5.0. Model loads, serves OpenAI-compatible chat completions with HMAC auth, generates quality code output. Completions endpoint (`/v1/completions`) and models endpoint (`/v1/models`) confirmed working.
