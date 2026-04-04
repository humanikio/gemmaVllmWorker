# Gemma 4 Model Family

Google's Gemma 4 release (March 2026) — model variants, architecture, and capabilities.

## Model Variants

| Model | Total Params | Active Params | Context | Modalities | License |
|-------|-------------|---------------|---------|------------|---------|
| gemma-4-31B-it | 31B | 31B (dense) | 262K | Vision + Text | Apache 2.0 |
| **gemma-4-26B-A4B-it** | 26B | **~4B (MoE)** | 262K | Vision + Text | Apache 2.0 |
| gemma-4-E4B-it | ~4B | ~4B (dense) | 131K | Audio + Vision + Text | Apache 2.0 |
| gemma-4-E2B-it | ~2B | ~2B (dense) | 131K | Audio + Vision + Text | Apache 2.0 |

## Architecture Highlights

### MoE (26B-A4B)

- **128 fine-grained experts**, top-8 routing per token
- 30 transformer layers, hidden_size=2816
- MoE intermediate size of 704 per expert
- Only ~4B parameters activated per forward pass — rest stays dormant in VRAM

### Heterogeneous Attention (all variants)

Gemma 4 alternates two attention types within the same model:

| Attention Type | head_dim | Purpose | % of Layers |
|---------------|----------|---------|-------------|
| Sliding-window | 256 | Local context, efficient | ~83% |
| Full/global | 512 | Long-range dependencies | ~17% |

Layer breakdown by variant:

| Variant | Total Layers | Sliding | Full |
|---------|-------------|---------|------|
| E2B | 35 | 28 | 7 |
| E4B | 42 | 35 | 7 |
| 26B-A4B | 30 | 25 | 5 |
| 31B | 60 | 50 | 10 |

### Other Notable Features

- **Logit softcapping**: `final_logit_softcapping=30.0` (inherited from Gemma 2/3)
- **Shared K/V** (31B only): `attention_k_eq_v=true` — K and V projections share weights
- **Per-layer input projection** (E2B/E4B only): `hidden_size_per_layer_input=256`
- **Dynamic vision resolution**: Configurable per-request token budgets (70, 140, 280, 560, 1120)
- **Structured thinking**: `<|channel|>thought` delimiters for reasoning traces
- **Tool calling**: Custom protocol with dedicated tokens
- **Vocabulary**: 262,144 tokens across all variants
- **Multilingual**: Trained on 140+ languages

## Why 26B-A4B Is the Sweet Spot for Cost-Efficient Serving

The MoE variant gives you the quality of a 26B model with the compute cost of a 4B model. The trade-off is VRAM — all 26B weights must be loaded even though only 4B are active. This is exactly what quantization solves: compress 52 GB → 13 GB, and the per-token compute stays at 4B.
