"""
gemmaVllmWorker — FastAPI server for Gemma 4 MoE inference.

Standalone HTTP server that integrates with Humanik Cloud control plane
via HMAC auth and Redis heartbeat.

Endpoints:
  POST /v1/chat/completions  — OpenAI-compatible chat (streaming + non-streaming)
  POST /v1/completions       — OpenAI-compatible completions
  GET  /v1/models            — List available models
  GET  /health               — Health check (no auth)
  GET  /ready                — Readiness check (no auth)

Boot sequence:
  1. Start heartbeat (status: booting) — ALB sees us but won't route yet
  2. Initialize vLLM engines (~2 min)
  3. Mark healthy — ALB starts routing traffic
  4. Start idle timeout monitor
"""

import sys
import os
import json
import logging
import signal
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gemma-worker")

# ── Globals (initialized in lifespan) ────────────────────────────────
vllm_engine = None
openai_engine = None
_engines_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot sequence: heartbeat → engine init → mark healthy → idle timeout."""
    global vllm_engine, openai_engine, _engines_ready

    from heartbeat import (
        start_heartbeat, mark_healthy, graceful_shutdown,
        start_idle_timeout, increment_load, decrement_load,
    )

    # Phase 1: Start heartbeat (status: booting)
    start_heartbeat()

    # Phase 2: Initialize vLLM engines
    try:
        from engine import vLLMEngine, OpenAIvLLMEngine

        log.info("Initializing vLLM engines...")
        vllm_engine = vLLMEngine()
        openai_engine = OpenAIvLLMEngine(vllm_engine)
        _engines_ready = True
        log.info("vLLM engines initialized successfully")
    except Exception as e:
        log.error(f"Engine startup failed: {e}\n{traceback.format_exc()}")
        await graceful_shutdown("unhealthy")
        sys.exit(1)

    # Phase 3: Mark healthy — ALB starts routing traffic
    await mark_healthy()

    # Phase 4: Start idle timeout monitor
    async def _idle_shutdown():
        await graceful_shutdown("idle-timeout")
        sys.exit(0)

    start_idle_timeout(_idle_shutdown)

    yield

    # Shutdown
    log.info("Shutting down")
    await graceful_shutdown("shutdown")


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="gemmaVllmWorker", lifespan=lifespan)

# HMAC middleware — gates all routes except health checks
from middleware.cp_hmac_auth import CpHmacMiddleware

app.add_middleware(CpHmacMiddleware, exempt_paths=["/health", "/ready"])


# ── Health routes (no auth) ──────────────────────────────────────────

@app.get("/health")
async def health():
    from heartbeat import get_status, get_load
    return {"status": "ok", "heartbeat": get_status(), "load": get_load()}


@app.get("/ready")
async def ready():
    from heartbeat import get_status
    if not _engines_ready:
        return JSONResponse(status_code=503, content={"status": "loading", "heartbeat": get_status()})
    return {"status": "ready", "heartbeat": get_status()}


# ── OpenAI-compatible routes ─────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _handle_openai(request, "/v1/chat/completions")


@app.post("/v1/completions")
async def completions(request: Request):
    return await _handle_openai(request, "/v1/completions")


@app.get("/v1/models")
async def models():
    await openai_engine._ensure_engines_initialized()
    result = await openai_engine._handle_model_request()
    return JSONResponse(content=result)


async def _handle_openai(request: Request, route: str):
    """Route an OpenAI-format request through the vLLM engine."""
    from heartbeat import increment_load, decrement_load, touch_activity

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    is_stream = body.get("stream", False)

    from utils import JobInput
    job_input = JobInput({
        "openai_route": route,
        "openai_input": body,
    })

    increment_load()
    touch_activity()
    try:
        if is_stream:
            return StreamingResponse(
                _stream_response(job_input, decrement_load),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            try:
                return await _non_stream_response(job_input)
            finally:
                decrement_load()
    except Exception:
        decrement_load()
        raise


async def _non_stream_response(job_input):
    """Collect the full response and return as JSON."""
    try:
        result = None
        async for batch in openai_engine.generate(job_input):
            result = batch

        if result is None:
            return JSONResponse(status_code=500, content={"error": "No response generated"})

        if isinstance(result, dict) and "error" in result:
            return JSONResponse(status_code=400, content=result)

        return JSONResponse(content=result)
    except Exception as e:
        log.error(f"Inference error: {e}\n{traceback.format_exc()}")
        _check_cuda_fatal(e)
        return JSONResponse(status_code=500, content={"error": str(e)})


async def _stream_response(job_input, on_complete=None):
    """Yield SSE chunks from the vLLM engine."""
    try:
        async for batch in openai_engine.generate(job_input):
            if isinstance(batch, dict) and "error" in batch:
                yield f"data: {json.dumps(batch)}\n\n"
                return

            if isinstance(batch, str):
                yield batch
            elif isinstance(batch, list):
                for chunk in batch:
                    if isinstance(chunk, str):
                        yield chunk
                    else:
                        yield f"data: {json.dumps(chunk)}\n\n"
            else:
                yield f"data: {json.dumps(batch)}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as e:
        log.error(f"Streaming error: {e}\n{traceback.format_exc()}")
        _check_cuda_fatal(e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    finally:
        if on_complete:
            on_complete()


def _check_cuda_fatal(e: Exception):
    """CUDA errors = worker is broken, exit to let orchestrator replace it."""
    error_str = str(e)
    if "CUDA" in error_str or "cuda" in error_str:
        log.error("Terminating worker due to CUDA/GPU error")
        sys.exit(1)


# ── Entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    log.info(f"Starting gemmaVllmWorker on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
