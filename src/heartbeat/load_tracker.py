"""
Load Tracker

Tracks concurrent request count for heartbeat reporting.
Also handles idle timeout for auto-scaling (scale-to-zero).
"""

import asyncio
import logging
import time
from typing import Callable, Awaitable, Optional

from heartbeat.config import IDLE_TIMEOUT_S, IDLE_CHECK_INTERVAL_S, IDLE_TIMEOUT_MINUTES

log = logging.getLogger("heartbeat")

_current_load = 0
_last_activity = time.time()
_idle_task: Optional[asyncio.Task] = None
_shutdown_callback: Optional[Callable[[], Awaitable[None]]] = None


def increment_load() -> None:
    global _current_load, _last_activity
    _current_load += 1
    _last_activity = time.time()


def decrement_load() -> None:
    global _current_load, _last_activity
    _current_load -= 1
    if _current_load < 0:
        _current_load = 0
    _last_activity = time.time()


def get_load() -> int:
    return _current_load


def touch_activity() -> None:
    global _last_activity
    _last_activity = time.time()


async def _idle_monitor() -> None:
    """Background loop that checks for idle timeout."""
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL_S)

        idle_time = time.time() - _last_activity
        idle_minutes = int(idle_time / 60)

        if _current_load == 0 and idle_time >= IDLE_TIMEOUT_S:
            log.info(f"[idleTimeout] Idle for {idle_minutes} min with no load, initiating shutdown...")
            stop_idle_timeout()
            if _shutdown_callback:
                try:
                    await _shutdown_callback()
                except Exception as e:
                    log.error(f"[idleTimeout] Shutdown callback failed: {e}")
            return
        elif _current_load == 0:
            log.info(f"[idleTimeout] Idle for {idle_minutes} min (threshold: {IDLE_TIMEOUT_MINUTES} min)")


def start_idle_timeout(on_shutdown: Callable[[], Awaitable[None]]) -> None:
    global _idle_task, _shutdown_callback
    _shutdown_callback = on_shutdown

    if IDLE_TIMEOUT_S == 0:
        log.info("[idleTimeout] Disabled (persistent mode: IDLE_TIMEOUT_MINUTES=0)")
        return

    log.info(f"[idleTimeout] Started (timeout: {IDLE_TIMEOUT_MINUTES} min)")
    _idle_task = asyncio.get_event_loop().create_task(_idle_monitor())


def stop_idle_timeout() -> None:
    global _idle_task
    if _idle_task and not _idle_task.done():
        _idle_task.cancel()
        _idle_task = None
        log.info("[idleTimeout] Stopped")
