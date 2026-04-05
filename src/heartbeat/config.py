"""
Heartbeat Configuration

Reads identity and routing from environment variables injected
by Humanik Cloud control plane at pod creation time.
"""

import os
import json
import logging
import socket

log = logging.getLogger("heartbeat")

# ── Timing ───────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_S = 10   # Send heartbeat every 10 seconds
HEARTBEAT_TTL_S = 30        # Redis hash TTL (expires if no heartbeat)

# ── Identity (injected by Humanik Cloud at pod spawn) ────────────────
TENANT_ID = os.environ.get("NEXUS_TENANT_ID", "")
SERVICE_ID = os.environ.get("NEXUS_SERVICE_ID", "")
INSTANCE_ID = os.environ.get("NEXUS_INSTANCE_ID", "")
PROVIDER = os.environ.get("NEXUS_PROVIDER", "runpod")
REDIS_URL = os.environ.get("NEXUS_REDIS_URL", "")

# ── Provider routing ─────────────────────────────────────────────────
# RunPod pod ID — injected by control plane or read from RUNPOD_POD_ID
RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "")

# Region (RunPod sets RUNPOD_DC_ID, fallback to unknown)
REGION = os.environ.get("RUNPOD_DC_ID", os.environ.get("FLY_REGION", "unknown"))

# ── Idle timeout ─────────────────────────────────────────────────────
# Minutes of zero load before self-termination. 0 = persistent (never).
IDLE_TIMEOUT_MINUTES = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "20"))
IDLE_TIMEOUT_S = IDLE_TIMEOUT_MINUTES * 60
IDLE_CHECK_INTERVAL_S = 60


def get_pod_id() -> str:
    """Resolve pod ID from env or hostname."""
    if RUNPOD_POD_ID:
        return RUNPOD_POD_ID
    # RunPod pods use the pod ID as the hostname
    try:
        host = socket.gethostname()
        if host:
            log.info(f"Using hostname as pod ID: {host}")
            return host
    except Exception:
        pass
    return ""


def get_heartbeat_keys() -> dict:
    """Redis keys for this instance's heartbeat data."""
    return {
        "hash_key": f"machines:{SERVICE_ID}:{INSTANCE_ID}",
        "set_key": f"machines:{SERVICE_ID}:active",
    }


def get_provider_routing() -> str:
    """Provider routing JSON for ALB resolution."""
    return json.dumps({
        "provider": PROVIDER,
        "podId": get_pod_id(),
    })


def get_custom_metadata() -> str:
    """Custom metadata JSON (extensible)."""
    return json.dumps({})


def is_heartbeat_enabled() -> bool:
    """Check if all required identity vars are present."""
    enabled = bool(TENANT_ID and SERVICE_ID and INSTANCE_ID and REDIS_URL)
    if not enabled:
        missing = []
        if not TENANT_ID: missing.append("NEXUS_TENANT_ID")
        if not SERVICE_ID: missing.append("NEXUS_SERVICE_ID")
        if not INSTANCE_ID: missing.append("NEXUS_INSTANCE_ID")
        if not REDIS_URL: missing.append("NEXUS_REDIS_URL")
        log.warning(f"Heartbeat disabled — missing: {', '.join(missing)}")
    return enabled
