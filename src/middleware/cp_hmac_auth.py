"""
Control Plane HMAC Authentication Middleware

Verifies HMAC signatures on requests forwarded by the Nexus control plane.
Prevents direct access to the instance via its public URL.

Expected headers:
- x-hmac-signature: HMAC-SHA256 signature (hex encoded)
- x-hmac-timestamp: Unix timestamp (ms) when signature was created

Message format: "{timestamp}.{method}.{path}"
Body is excluded — proxy services cannot parse the body without
consuming the stream needed for forwarding.

Replay attack protection via 5-minute timestamp window.
Uses CP_INSTANCE_HMAC_SECRET (shared between control plane and all instances).

Follows hos-openClaw's cpHmacAuth.ts pattern exactly.
"""

import hmac
import hashlib
import os
import time
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

MAX_REQUEST_AGE_MS = 5 * 60 * 1000  # 5 minutes


async def verify_cp_hmac(request: Request):
    """Verify HMAC signature on an incoming request.

    Returns None if valid, or a JSONResponse error if invalid.
    Used by CpHmacMiddleware and can be called standalone.
    """
    signature = request.headers.get("x-hmac-signature")
    timestamp = request.headers.get("x-hmac-timestamp")

    if not signature or not timestamp:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Missing HMAC authentication headers"},
        )

    # Validate timestamp (replay protection)
    try:
        request_time = int(timestamp)
    except ValueError:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Invalid timestamp format"},
        )

    time_diff = abs(int(time.time() * 1000) - request_time)
    if time_diff > MAX_REQUEST_AGE_MS:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Request timestamp too old or in future"},
        )

    # Read shared secret
    secret = os.environ.get("CP_INSTANCE_HMAC_SECRET")
    if not secret:
        logging.error("[cpHmacAuth] CP_INSTANCE_HMAC_SECRET not set")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "message": "Server configuration error"},
        )

    # Reconstruct signed message: timestamp.method.path
    # Body is excluded because proxy services cannot parse
    # the body without consuming the stream needed for forwarding.
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    message = f"{timestamp}.{request.method}.{path}"

    # Generate expected signature
    expected_signature = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison (timing attack prevention)
    if not hmac.compare_digest(signature, expected_signature):
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Invalid HMAC signature"},
        )

    return None


class CpHmacMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that gates all requests behind CP HMAC auth.

    Exempt paths (health checks) can be configured to skip verification.
    """

    def __init__(self, app, exempt_paths: list[str] | None = None):
        super().__init__(app)
        self.exempt_paths = set(exempt_paths or [])

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        error_response = await verify_cp_hmac(request)
        if error_response is not None:
            return error_response

        return await call_next(request)
