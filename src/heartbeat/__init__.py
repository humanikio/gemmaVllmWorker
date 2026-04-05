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

    # Send initial heartbeat immediately, then start loop
    loop = asyncio.get_event_loop()
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

    1. Stop sending heartbeats
    2. Signal termination to control plane
    3. Deregister from Redis
    4. Close Redis connection
    """
    stop_heartbeat()
    stop_idle_timeout()

    if is_heartbeat_enabled():
        await signal_termination(reason)
        await deregister()
        await close_redis()

    log.info(f"Graceful shutdown complete (reason: {reason})")
