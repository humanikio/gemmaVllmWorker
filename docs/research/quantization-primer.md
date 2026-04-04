# Quantization Primer

How model quantization works and why it matters for serving Gemma 4 MoE cost-effectively.

## Core Concept

A model is billions of floating-point weights. Quantization stores those weights with fewer bits, trading precision for memory savings.

### Bit-Width and Memory

| Format | Bits per weight | Bytes per weight | 26B model size |
|--------|-----------------|------------------|----------------|
| BF16 (default) | 16 | 2.0 | ~52 GB |
| FP8 | 8 | 1.0 | ~26 GB |
| INT8 | 8 | 1.0 | ~26 GB |
| INT4 (GPTQ/AWQ) | 4 | 0.5 | ~13 GB |
| NVFP4 | 4 | 0.5 | ~13 GB |

### How INT4 Works

4 bits = 16 distinct values (2^4). Weights are grouped (typically 128 per group), and each group gets mapped to a 16-step grid between its min and max:

```
Group of 128 weights:
  min = -1.38,  max = 2.05
  step = (2.05 - (-1.38)) / 15 = 0.2287

  Quantized values: -1.380, -1.151, -0.923, -0.694, ... , 2.050
  Each weight → nearest of 16 values → stored as 4-bit int (0-15)
  Metadata stored per group: scale + zero_point (~0.2% overhead)
```

Reconstruction: `real_value ≈ zero_point + (int4_value × scale)`

### Smart Quantization Methods

Naive quantization treats all weights equally. Production methods are smarter:

**GPTQ** — Runs a calibration dataset through the model. Measures per-weight impact on output quality. Quantizes sequentially, correcting accumulated error at each step. Protects high-impact weights.

**AWQ (Activation-Aware Weights)** — Identifies which weights produce the largest activations (signal amplifiers). Scales those weights up before quantization so they get more of the 16 available levels. Result: high-impact weights keep more precision.

**FP8** — Uses 8-bit floating point instead of integer quantization. Retains the exponent/mantissa structure of floats, better at representing the natural distribution of neural network weights. Nearly lossless but only halves memory (vs 4x reduction with INT4).

**NVFP4** — NVIDIA's proprietary 4-bit floating point format. Better than INT4 for weight distributions with outliers, but requires Hopper/Blackwell GPUs (H100, B200, etc.).

### Quality Impact

| Method | VRAM | Quality vs BF16 | Notes |
|--------|------|------------------|-------|
| FP8 | 26 GB | ~99.5% | Nearly lossless |
| INT8 | 26 GB | ~99% | Excellent |
| AWQ INT4 | 13 GB | ~97-99% | Best INT4 method for inference |
| GPTQ INT4 | 13 GB | ~96-98% | Slightly behind AWQ for serving |
| Naive INT4 | 13 GB | ~90-95% | Noticeably worse, not recommended |

## Why MoE + Quantization Is Especially Powerful

```
                        BF16          INT4
Dense 31B:            62 GB    →    15.5 GB   (all 31B active per token)
MoE 26B-A4B:          52 GB    →    13 GB     (only 4B active per token)
```

With quantized MoE:
- **Storage**: 13 GB for all 128 experts (fits a 24 GB GPU)
- **Compute**: Only 8 of 128 experts fire per token (~4B params of work)
- **Result**: 26B-quality output at 4B-model speed in 13 GB of VRAM
