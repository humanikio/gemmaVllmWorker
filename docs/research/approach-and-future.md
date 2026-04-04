# Approach and Future Moves

Our strategy for deploying Gemma 4 MoE as a cost-efficient "free LLM" tier, and what to watch for.

## Current Approach

### Goal

Offer free LLM inference to Humanik users by self-hosting the most cost-efficient model possible on RunPod serverless.

### Why Gemma 4 26B-A4B MoE + AWQ 4-bit

| Factor | Value |
|--------|-------|
| Model | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| VRAM required | ~13 GB |
| GPU target | 24 GB class (A10G, L4, RTX 4090) |
| Active params per token | ~4B (8 of 128 experts) |
| Quality | 26B-class output |
| Inference speed | Near 4B-model speed |
| Cost | Cheapest GPU tier on RunPod |
| Deployment | RunPod serverless (bursty, pay-per-request) |
| Context window | 262K tokens |

### Architecture

```
User request → Humanik API → RunPod Serverless Endpoint
                                  │
                                  ▼
                          synthcore-worker-gemma (this repo)
                                  │
                                  ├── handler.py (RunPod entry)
                                  ├── engine.py (vLLM wrapper)
                                  └── vLLM 0.19.0 + Gemma 4 26B-A4B AWQ
                                       │
                                       ▼
                                  OpenAI-compatible API
                                  /v1/chat/completions
                                  /v1/models
```

### RunPod Configuration (Tested April 4, 2026)

```env
MODEL_NAME=cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit
# Do NOT set QUANTIZATION — model uses compressed-tensors format, vLLM auto-detects
GPU_MEMORY_UTILIZATION=0.95
MAX_MODEL_LEN=8192
MAX_CONCURRENCY=30
ENABLE_PREFIX_CACHING=true
OPENAI_SERVED_MODEL_NAME_OVERRIDE=gemma-4-26b-moe
# HF cache MUST point to the volume, not container disk (30GB fills up)
HF_HOME=/runpod-volume/huggingface-cache
HUGGINGFACE_HUB_CACHE=/runpod-volume/huggingface-cache/hub
```

GPU target: Ada (sm_89) or Ampere (sm_86). See GPU Compatibility below.

### Tested Performance (L40S, 48GB)

| Metric | Value |
|--------|-------|
| Cold start (model cached) | ~127s |
| Cold start (first download) | ~160s |
| KV cache available | 24.5 GB |
| KV cache tokens | 106,976 |
| Max concurrency at 8192 ctx | 14.2x |
| CUDA graph capture | 12s |

### GPU Compatibility Matrix

Tested on RunPod, April 4, 2026:

| GPU | Arch | sm | VRAM | Status | Notes |
|-----|------|-----|------|--------|-------|
| L40S | Ada | 8.9 | 48 GB | **Works** | Tested and confirmed. Best dev option |
| L4 | Ada | 8.9 | 24 GB | Expected to work | Same arch as L40S, tighter on VRAM |
| RTX 4090 | Ada | 8.9 | 24 GB | Expected to work | Low stock on RunPod |
| RTX A5000 | Ampere | 8.6 | 24 GB | Expected to work | Untested |
| RTX 3090 | Ampere | 8.6 | 24 GB | Expected to work | Cheapest option |
| RTX 5090 | **Blackwell** | 12.0 | 32 GB | **FAILS** | Marlin kernel PTX incompatible |
| T4 | Turing | 7.5 | 16 GB | **FAILS** | Shared memory limits (head_dim=512) |

**Rule: Use Ada or Ampere only. Avoid Blackwell and Turing.**

## Future Moves

### Near-Term (watch these PRs)

**1. Per-layer attention backend (PR #38891)**
When merged: allows 83% of layers to use FlashAttention instead of Triton fallback. Significant throughput improvement on Ampere GPUs (what we'd run on RunPod).
- **Action**: Bump vLLM version when this lands.

**2. YOCO fast prefill (PR #38879)**
When merged: +39% throughput, -34% time-to-first-token. Directly improves user-perceived latency.
- **Action**: Enable `--kv-sharing-fast-prefill` flag when available.

**3. Tool calling streaming fix (PR #38945)**
When merged: fixes invalid JSON in streamed tool calls. Required if we want to expose tool use through the free tier.
- **Action**: No config change needed, just bump vLLM.

**4. Reasoning parser fix (issue #38855)**
When fixed: enables proper `reasoning_content` separation in responses. Useful for chain-of-thought features.
- **Action**: Set `REASONING_PARSER=gemma4` once the fix lands.

### Medium-Term Opportunities

**5. MoE expert CPU offloading (PR #37190)**
If merged: could run the full BF16 model at 8.6 GB VRAM with expert caching. Would allow even cheaper GPUs (16 GB class) or higher quality (no quantization loss).
- **Trade-off**: 14.8 tok/s is slower than quantized-on-GPU, but the VRAM savings could justify cheaper hardware.

**6. NVFP4 support (issue #38912)**
When fixed: NVIDIA's FP4 format may give better quality than INT4 AWQ at the same memory footprint. Requires Hopper+ GPUs though (H100), which are more expensive.
- **Decision**: Only worth it if RunPod H100 spot pricing drops enough to offset the quality gain.

**7. Speculative decoding for Gemma 4 (issue #38893)**
Feature request for Eagle3 spec decode targeting Gemma 4. Would significantly improve throughput by predicting multiple tokens at once.
- **Impact**: Could 2-3x effective throughput, huge for cost efficiency.

### Long-Term Considerations

**8. Gemma 4 E4B (audio + vision + text)**
Once the weight loading (#38886) and performance (#38887) issues are resolved, the E4B model is interesting:
- ~4B params, no MoE complexity
- Audio input support — could enable voice-driven features
- 131K context
- Would need even less VRAM than the quantized MoE
- **Blocker**: Currently broken in vLLM 0.19.0.

**9. Context length scaling**
Starting at `MAX_MODEL_LEN=8192` for cost reasons. The model supports 262K. As usage patterns become clear, we can increase this — each doubling roughly doubles KV cache memory.

**10. LoRA fine-tuning**
The worker already supports LoRA adapters (`LORA_MODULES` env var). Could fine-tune Gemma 4 MoE on Humanik-specific tasks (code generation, platform-specific knowledge) without retraining the full model.

## Lessons Learned (April 4, 2026 Testing)

### compressed-tensors, not AWQ
The `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` model is stored in **compressed-tensors** format, not raw AWQ. Setting `QUANTIZATION=awq` causes a validation error. Remove it entirely — vLLM auto-detects the format from the model config.

### vLLM 0.19.0 API Breaking Changes
Three breaking changes in the OpenAI serving layer required code fixes:
1. **`OpenAIServingRender`** — New required object that must be created and passed to both `OpenAIServingChat` and `OpenAIServingCompletion`
2. **`log_error_stack`** — Moved from chat/completion constructors to the render layer
3. **`warmup()`** — Changed from async to sync. `await self.chat_engine.warmup()` → `self.chat_engine.warmup()`

### Blackwell GPUs (RTX 5090) Incompatible
The Marlin quantization kernel compiles PTX for specific CUDA compute capabilities. Blackwell (sm_12.0) is too new — the PTX fails with `cudaErrorUnsupportedPtxVersion`. This is a kernel-level issue, not a config fix. Must use Ada (sm_89) or Ampere (sm_86).

### HF Cache Location Critical
The default HuggingFace cache (`~/.cache/huggingface`) writes to the container disk. On RunPod, that's typically 20-30GB — the model download (~7GB) plus unpacking fills it. Always point `HF_HOME` to the persistent volume.

### GPU Memory Doesn't Free in Containers
After a CUDA crash, GPU memory stays allocated even after all processes exit. `nvidia-smi --gpu-reset` is blocked by container permissions. The only fix is to stop/start the pod.

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AWQ quant has quality issues for code tasks | Medium | High | Benchmark against raw API calls before launch. Fallback to FP8 on larger GPU if needed |
| vLLM 0.19.0 Gemma 4 bugs in production | High | Medium | Pin to known-good vLLM commit. Monitor RunPod worker logs for CUDA errors |
| Cold start latency too high for "free" UX | Medium | Medium | Consider baking model into Docker image (Option 2 in Dockerfile). Current cold start: ~127s cached |
| RunPod 24 GB GPU availability | Low | High | Configure fallback to 40 GB tier (L40S) with same image. L40S confirmed working |
| Blackwell GPU assigned by RunPod | Medium | High | Explicitly set `gpuIds` in hub.json to Ada/Ampere only. Already done |
| Upstream model updates (Gemma 4.1?) | Low | Low | Pin model revision. Evaluate upgrades when available |
