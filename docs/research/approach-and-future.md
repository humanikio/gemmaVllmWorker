# Approach and Future Moves

Our strategy for deploying Gemma 4 MoE as a cost-efficient "free LLM" tier, and what to watch for.

## Current Approach

### Goal

Offer free LLM inference to Synthcore users by self-hosting the most cost-efficient model possible on RunPod serverless.

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
User request → Synthcore API → RunPod Serverless Endpoint
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

### RunPod Configuration

```env
MODEL_NAME=cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit
QUANTIZATION=awq
GPU_MEMORY_UTILIZATION=0.95
MAX_MODEL_LEN=8192          # Start conservative, scale up based on usage
MAX_CONCURRENCY=30
DTYPE=float16
ENFORCE_EAGER=false
```

GPU target: 24 GB (A10G or L4 on RunPod)

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
The worker already supports LoRA adapters (`LORA_MODULES` env var). Could fine-tune Gemma 4 MoE on Synthcore-specific tasks (code generation, platform-specific knowledge) without retraining the full model.

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AWQ quant has quality issues for code tasks | Medium | High | Benchmark against raw API calls before launch. Fallback to FP8 on larger GPU if needed |
| vLLM 0.19.0 Gemma 4 bugs in production | High | Medium | Pin to known-good vLLM commit. Monitor RunPod worker logs for CUDA errors |
| Cold start latency too high for "free" UX | Medium | Medium | Consider baking model into Docker image (Option 2 in Dockerfile) |
| RunPod 24 GB GPU availability | Low | High | Configure fallback to 40 GB tier (L40S) with same image |
| Upstream model updates (Gemma 4.1?) | Low | Low | Pin model revision. Evaluate upgrades when available |
