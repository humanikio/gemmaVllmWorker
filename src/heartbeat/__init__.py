"""
Heartbeat Module

Sends periodic heartbeats to Redis for Humanik Cloud ALB instance discovery.
Port of hos-openClaw/src/heartbeat/ to Python.
"""

import asyncio
import logging

from heartbeat.config import is_heartbeat_enabled, HEARTBEAT_INTERVAL_S
from heartbeat.heartbeat_service import (
    send_heartbeat,
    mark_healthy,
    start_draining,
    deregister,
    signal_termination,
    close_redis,
    get_status,
)
from heartbeat.load_tracker import (
    increment_load,
    decrement_load,
    get_load,
    touch_activity,
    start_idle_timeout,
    stop_idle_timeout,
)

log = logging.getLogger("heartbeat")

_heartbeat_task: asyncio.Task | None = None


async def _heartbeat_loop() -> None:
    """Background loop that sends heartbeats every HEARTBEAT_INTERVAL_S."""
    while True:
        await send_heartbeat()
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


def start_heartbeat() -> None:
    """Start the heartbeat loop. No-op if env vars are missing."""
    global _heartbeat_task

    if not is_heartbeat_enabled():
        return

    # Must use get_running_loop() — called from inside an async lifespan,
    # get_event_loop() can return a stale/different loop in Python 3.10+
    loop = asyncio.get_running_loop()
    loop.create_task(send_heartbeat())
    _heartbeat_task = loop.create_task(_heartbeat_loop())

    log.info(f"Heartbeat started (interval: {HEARTBEAT_INTERVAL_S}s)")


def stop_heartbeat() -> None:
    """Stop the heartbeat loop."""
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        _heartbeat_task = None
        log.info("Heartbeat stopped")


async def graceful_shutdown(reason: str = "shutdown") -> None:
    """Graceful shutdown sequence.

    For idle-timeout (RunPod pause):
      1. Stop heartbeat
      2. Signal CP (reason=idle-timeout) — CP will call stopPod + pauseInstance
      3. Do NOT deregister — CP needs the hash (providerRouting) to set status='paused'
      4. Leave Redis connection open until SIGTERM arrives from RunPod

    For shutdown/unhealthy (full termination):
      1. Stop heartbeat
      2. Signal CP (reason=shutdown/unhealthy) — CP will call destroyPod
      3. Deregister from Redis (stops routing immediately)
      4. Close Redis connection
    """
    stop_heartbeat()
    stop_idle_timeout()

    if is_heartbeat_enabled():
        await signal_termination(reason)

        if reason != "idle-timeout":
            # Full termination — deregister and close
            await deregister()
            await close_redis()
        else:
            # Pause — leave hash intact for CP to transition to 'paused'
            log.info("Skipping deregister (idle-timeout: CP will transition to paused)")

    log.info(f"Graceful shutdown complete (reason: {reason})")
