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
  GET  /ping                 — RunPod LB health check (204 loading, 200 ready)

Boot sequence:
  Uvicorn starts → /ping returns 204 immediately
  Background task:
    1. Start heartbeat (status: booting)
    2. Download model if needed (boot_model.py)
    3. Initialize vLLM engines (~2 min)
    4. Mark healthy → /ping returns 200, ALB starts routing
    5. Start idle timeout monitor
"""

import sys
import os
import json
import asyncio
import logging
import signal
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gemma-worker")

# ── Globals (initialized in background) ────────────────────────────
vllm_engine = None
openai_engine = None
_engines_ready = False


async def _boot_in_background():
    """Background boot: model download + vLLM init. Runs AFTER uvicorn starts
    so /ping is immediately accessible (returns 204 during loading)."""
    global vllm_engine, openai_engine, _engines_ready

    from heartbeat import (
        start_heartbeat, mark_healthy, graceful_shutdown,
        start_idle_timeout,
    )
    from heartbeat.config import is_heartbeat_enabled

    # Phase 1: Start heartbeat (status: booting) — no-op if NEXUS_* vars missing
    start_heartbeat()

    # Phase 1.5: Ensure model weights on volume
    # run_in_executor keeps the asyncio event loop free so /ping can respond
    # with 204 during the entire download — without this, the blocking download
    # freezes the event loop and RunPod's health checker times out.
    try:
        from boot_model import ensure_model
        model_args = await asyncio.get_event_loop().run_in_executor(None, ensure_model)

        if model_args.get("MODEL_NAME"):
            os.environ["MODEL_NAME"] = model_args["MODEL_NAME"]
            log.info(f"Model path: {model_args['MODEL_NAME']}")
        if model_args.get("TOKENIZER_NAME"):
            os.environ["TOKENIZER_NAME"] = model_args["TOKENIZER_NAME"]
            log.info(f"Tokenizer path: {model_args['TOKENIZER_NAME']}")
    except Exception as e:
        log.error(f"Model download failed: {e}\n{traceback.format_exc()}")
        if is_heartbeat_enabled():
            await graceful_shutdown("unhealthy")
        sys.exit(1)

    # Phase 2: Initialize vLLM engines
    # vLLMEngine() blocks for ~2 min while loading weights + compiling CUDA graphs.
    # run_in_executor keeps the event loop responsive throughout.
    try:
        from engine import vLLMEngine, OpenAIvLLMEngine

        log.info("Initializing vLLM engines...")
        vllm_engine = await asyncio.get_event_loop().run_in_executor(None, vLLMEngine)
        openai_engine = OpenAIvLLMEngine(vllm_engine)
        _engines_ready = True
        log.info("vLLM engines initialized successfully")
    except Exception as e:
        log.error(f"Engine startup failed: {e}\n{traceback.format_exc()}")
        if is_heartbeat_enabled():
            await graceful_shutdown("unhealthy")
        sys.exit(1)

    # Phase 3-4 only when running under Humanik Cloud
    if is_heartbeat_enabled():
        await mark_healthy()

        async def _idle_shutdown():
            await graceful_shutdown("idle-timeout")
            log.info("Idle shutdown signaled — waiting for external termination (SIGTERM)")

        start_idle_timeout(_idle_shutdown)
    else:
        log.info("Standalone mode — no heartbeat, no idle timeout")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: kick off background boot, yield immediately so uvicorn
    accepts connections. /ping returns 204 until boot completes."""
    boot_task = asyncio.create_task(_boot_in_background())
    yield
    # Shutdown
    log.info("Shutting down")
    from heartbeat import graceful_shutdown
    await graceful_shutdown("shutdown")


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="gemmaVllmWorker", lifespan=lifespan)

# HMAC middleware — gates all routes except health checks
from middleware.cp_hmac_auth import CpHmacMiddleware

app.add_middleware(CpHmacMiddleware, exempt_paths=["/health", "/ready", "/ping"])


# ── Health routes (no auth) ──────────────────────────────────────────

@app.get("/health")
async def health():
    from heartbeat import get_status, get_load
    return {"status": "ok", "heartbeat": get_status(), "load": get_load()}


@app.get("/ping")
async def ping():
    """RunPod LB health check.
    200 = healthy (ready to serve), 204 = initializing (model loading).
    RunPod measures cold start as time from first 204 to first 200."""
    if not _engines_ready:
        return JSONResponse(status_code=204, content=None)
    return JSONResponse(status_code=200, content={"status": "ok"})


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
    if not _engines_ready:
        return JSONResponse(status_code=503, content={"error": "Model loading"})
    await openai_engine._ensure_engines_initialized()
    result = await openai_engine._handle_model_request()
    return JSONResponse(content=result)


async def _handle_openai(request: Request, route: str):
    """Route an OpenAI-format request through the vLLM engine."""
    if not _engines_ready:
        return JSONResponse(status_code=503, content={"error": "Model loading, please retry"})

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
    """CUDA errors = worker is broken, signal CP and exit."""
    error_str = str(e)
    if "CUDA" in error_str or "cuda" in error_str:
        log.error("CUDA/GPU error detected — signaling CP and terminating")
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_fatal_shutdown())
        except RuntimeError:
            sys.exit(1)


async def _fatal_shutdown():
    """Signal unhealthy to CP, then exit."""
    from heartbeat import graceful_shutdown
    await graceful_shutdown("unhealthy")
    sys.exit(1)


# ── Entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 80))
    log.info(f"Starting gemmaVllmWorker on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
