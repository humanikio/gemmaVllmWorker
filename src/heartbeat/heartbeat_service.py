"""
Heartbeat Service

Sends periodic heartbeats to Redis for ALB instance discovery.
Follows the same pattern as hos-openClaw/src/heartbeat/heartbeatService.ts.
"""

import json
import logging
import time

import redis.asyncio as aioredis

from heartbeat.config import (
    REDIS_URL,
    TENANT_ID,
    SERVICE_ID,
    INSTANCE_ID,
    PROVIDER,
    REGION,
    HEARTBEAT_TTL_S,
    get_heartbeat_keys,
    get_provider_routing,
    get_custom_metadata,
)
from heartbeat.load_tracker import get_load

log = logging.getLogger("heartbeat")

_start_time = int(time.time() * 1000)
_current_status = "booting"
_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Lazy Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def send_heartbeat() -> None:
    """Send a single heartbeat to Redis (atomic pipeline)."""
    keys = get_heartbeat_keys()
    r = await _get_redis()

    try:
        pipe = r.pipeline()

        # 1. Set all hash fields
        pipe.hset(keys["hash_key"], mapping={
            "instanceId": INSTANCE_ID,
            "serviceId": SERVICE_ID,
            "tenantId": TENANT_ID,
            "providerRouting": get_provider_routing(),
            "customMetadata": get_custom_metadata(),
            "load": str(get_load()),
            "lastHeartbeat": str(int(time.time() * 1000)),
            "status": _current_status,
            "region": REGION,
            "startedAt": str(_start_time),
        })

        # 2. Set TTL (30 seconds)
        pipe.expire(keys["hash_key"], HEARTBEAT_TTL_S)

        # 3. Add to active set
        pipe.sadd(keys["set_key"], INSTANCE_ID)

        await pipe.execute()
        log.info(f"Heartbeat sent: load={get_load()}, status={_current_status}")
    except Exception as e:
        log.error(f"Heartbeat failed: {e}")


async def mark_healthy() -> None:
    """Mark instance as healthy (boot complete, ready to serve requests)."""
    global _current_status
    _current_status = "healthy"
    keys = get_heartbeat_keys()

    try:
        r = await _get_redis()
        await r.hset(keys["hash_key"], "status", "healthy")
        log.info("Marked as healthy (ready to serve requests)")
    except Exception as e:
        log.error(f"Failed to mark healthy: {e}")


async def start_draining() -> None:
    """Mark instance as draining (graceful shutdown)."""
    global _current_status
    _current_status = "draining"
    keys = get_heartbeat_keys()

    try:
        r = await _get_redis()
        await r.hset(keys["hash_key"], "status", "draining")
        log.info("Marked as draining")
    except Exception as e:
        log.error(f"Failed to mark draining: {e}")


async def deregister() -> None:
    """Remove instance from Redis (full shutdown)."""
    keys = get_heartbeat_keys()

    try:
        r = await _get_redis()
        await r.delete(keys["hash_key"])
        await r.srem(keys["set_key"], INSTANCE_ID)
        log.info("Deregistered from Redis")
    except Exception as e:
        log.error(f"Failed to deregister: {e}")


async def signal_termination(reason: str) -> None:
    """Signal termination to control plane via Redis pub/sub.

    Channel: instance:terminate:{serviceId}
    Reasons: idle-timeout, shutdown, unhealthy
    """
    channel = f"instance:terminate:{SERVICE_ID}"
    message = json.dumps({
        "instanceId": INSTANCE_ID,
        "serviceId": SERVICE_ID,
        "tenantId": TENANT_ID,
        "podId": json.loads(get_provider_routing()).get("podId", ""),
        "provider": PROVIDER,
        "reason": reason,
    })

    try:
        r = await _get_redis()
        await r.publish(channel, message)
        log.info(f"Termination signal sent: reason={reason}, channel={channel}")
    except Exception as e:
        log.error(f"Failed to signal termination: {e}")
        raise


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


def get_status() -> str:
    return _current_status
