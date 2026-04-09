# RunPod Hub — Cold Start and Event Loop Requirements

## Background

RunPod Hub uses a health check protocol to measure cold start time and determine when a worker is ready to serve traffic:

- **`/ping` → 204** — worker is initializing (model loading, engine warmup)
- **`/ping` → 200** — worker is ready to serve requests

RunPod's `aiapi` sidecar calls `/ping` on a configurable interval (default 20s) until it sees 200. If the health check times out (no response at all — not even 204) too many times, RunPod kills the pod and marks the test as failed.

## The Problem: Blocking the Event Loop

FastAPI and uvicorn are built on Python's `asyncio`. The event loop is **single-threaded** — if any code running on it blocks (e.g. performs synchronous I/O or CPU-bound work), **all** HTTP request handling freezes until that code returns. That includes `/ping`.

For this worker, two startup operations are long-running and synchronous:

| Operation | Typical Duration |
|-----------|-----------------|
| `ensure_model()` — HuggingFace model download | 60–120s (first boot) |
| `vLLMEngine()` — weight loading + CUDA graph compilation | 120–140s |

If either of these runs on the event loop, `/ping` becomes unreachable for that entire duration. RunPod's health checker sees repeated connection timeouts (`context deadline exceeded`), not 204 responses, and kills the pod before the engine finishes.

### What this looks like in logs

```
13:17:51  INFO: Waiting for application startup.
13:17:51  INFO: Started server process [6581]
                                               ← /ping unreachable for 4 minutes
13:18:49  ERRO healthChecker err: context deadline exceeded
13:19:49  ERRO healthChecker err: context deadline exceeded
13:20:49  ERRO healthChecker err: context deadline exceeded
13:21:44  INFO vLLM engine initialized
13:21:49  ERRO healthChecker err: context deadline exceeded   ← RunPod gives up
13:21:50  INFO: Application startup complete.
13:21:50  INFO: Application shutdown complete.               ← SIGTERM received
13:21:50  ERROR [Errno 98] address already in use            ← restart fails
```

The engine finishes loading 5 seconds before RunPod's final health check fires — but by then it's too late.

## The Fix: `run_in_executor`

Both blocking operations must run on a thread pool executor, off the event loop:

```python
# ✗ Blocks the event loop — /ping unresponsive for 4 minutes
model_args = ensure_model()
vllm_engine = vLLMEngine()

# ✓ Runs in a thread — event loop stays free, /ping returns 204 throughout
model_args = await asyncio.get_event_loop().run_in_executor(None, ensure_model)
vllm_engine = await asyncio.get_event_loop().run_in_executor(None, vLLMEngine)
```

With this in place:
1. Uvicorn starts, lifespan yields immediately
2. Boot task starts in a background thread
3. `/ping` returns 204 on every health check throughout the load
4. When the engine is ready, `_engines_ready = True`
5. `/ping` returns 200, RunPod marks the worker healthy and routes traffic

## Why This Isn't in RunPod's Docs

RunPod's official worker examples use the `runpod` Python SDK (`runpod.serverless.start(handler)`), which runs in its own blocking loop. The event loop issue only surfaces when building a custom FastAPI server that handles its own startup lifecycle. The 204/200 protocol is documented; the async constraint is not.

## Hub Test Strategy

RunPod Hub's test pipeline spins up a **fresh, isolated pod** from your Docker image for every test run. It does NOT hit your existing deployed serverless endpoint. Each test pod:

1. Pulls the image
2. Starts the container
3. Sends the test inputs
4. Tears the pod down

### Why health-only tests

This worker requires a 26B AWQ model (~14GB) which takes 2–4 minutes to download and another 2 minutes to load into VRAM. Completions tests would require the full model to be present and loaded before the test input is sent — this means:

- The test pod needs a 48GB+ VRAM GPU (L40S / A6000 / A100)
- Model download adds 4–6 minutes of cold start time
- HMAC authentication (`CpHmacMiddleware`) blocks unauthenticated completions requests — the Hub test runner sends no HMAC headers and `CP_INSTANCE_HMAC_SECRET` is not set in the test environment

`/health` is HMAC-exempt, responds immediately (no model needed), and proves the server started correctly. Completions correctness is tested separately against the deployed serverless endpoint where the model is pre-cached on the network volume and HMAC is configured.

### Why RTX 4090

A6000 (48GB) and L40S were unavailable in RunPod's test fleet across multiple retries. The RTX 4090 (24GB) is the most reliably available GPU. A 4090 is sufficient for a health-only test — no model is loaded.

### `.runpod/tests.json` current state

```json
{
  "tests": [{ "name": "health_check" }],
  "config": { "gpuTypeId": "NVIDIA GeForce RTX 4090" }
}
```

## Related

- `src/server.py` — `_boot_in_background()` where these calls live
- `docs/guides/runpod-ssh-dev-flow.md` — how to SSH into a test pod and verify `/ping` behavior manually
