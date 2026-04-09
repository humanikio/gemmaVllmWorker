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

## Related

- `src/server.py` — `_boot_in_background()` where these calls live
- `docs/guides/runpod-ssh-dev-flow.md` — how to SSH into a test pod and verify `/ping` behavior manually
