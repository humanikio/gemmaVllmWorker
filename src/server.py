"""
gemmaVllmWorker — FastAPI server for Gemma 4 MoE inference.

Replaces the RunPod serverless handler with a standalone HTTP server
that integrates with Nexus control plane via HMAC auth.

Endpoints:
  POST /v1/chat/completions  — OpenAI-compatible chat (streaming + non-streaming)
  POST /v1/completions       — OpenAI-compatible completions
  GET  /v1/models            — List available models
  GET  /health               — Health check (no auth)
  GET  /ready                — Readiness check (no auth)
"""

import sys
import os
import json
import logging
import multiprocessing
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
    """Initialize vLLM engines on startup, cleanup on shutdown."""
    global vllm_engine, openai_engine, _engines_ready

    try:
        from engine import vLLMEngine, OpenAIvLLMEngine

        log.info("Initializing vLLM engines...")
        vllm_engine = vLLMEngine()
        openai_engine = OpenAIvLLMEngine(vllm_engine)
        _engines_ready = True
        log.info("vLLM engines initialized successfully")
    except Exception as e:
        log.error(f"Engine startup failed: {e}\n{traceback.format_exc()}")
        sys.exit(1)

    yield

    log.info("Shutting down")


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="gemmaVllmWorker", lifespan=lifespan)

# HMAC middleware — gates all routes except health checks
from middleware.cp_hmac_auth import CpHmacMiddleware

app.add_middleware(CpHmacMiddleware, exempt_paths=["/health", "/ready"])


# ── Health routes (no auth) ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    if not _engines_ready:
        return JSONResponse(status_code=503, content={"status": "loading"})
    return {"status": "ready"}


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

    if is_stream:
        return StreamingResponse(
            _stream_response(job_input),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(job_input)


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


async def _stream_response(job_input):
    """Yield SSE chunks from the vLLM engine."""
    try:
        async for batch in openai_engine.generate(job_input):
            if isinstance(batch, dict) and "error" in batch:
                yield f"data: {json.dumps(batch)}\n\n"
                return

            if isinstance(batch, str):
                # raw_openai_output mode — already SSE formatted
                yield batch
            elif isinstance(batch, list):
                # list of SSE strings
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
