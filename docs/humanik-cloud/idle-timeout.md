# Idle Timeout & Scale-to-Zero

The worker monitors request load and self-terminates after a configurable idle period. This enables scale-to-zero on Humanik Cloud — pods are destroyed when not in use and recreated on demand.

## How It Works

1. Every 60 seconds, the idle monitor checks: is `load == 0` and has it been idle for longer than `IDLE_TIMEOUT_MINUTES`?
2. If yes: initiates graceful shutdown → signals control plane → control plane destroys the pod
3. If no: logs current idle time and continues monitoring

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `IDLE_TIMEOUT_MINUTES` | `20` | Minutes of zero load before self-termination |

**Special values**:
- `0` = persistent mode (never auto-terminate). Useful for always-on endpoints.
- Any positive integer = scale-to-zero after that many idle minutes.

## Cost Impact

| Strategy | GPU Cost | Idle Cost |
|----------|----------|-----------|
| Running continuously (L40S) | $0.86/hr | $0.86/hr |
| Stopped pod (warm standby) | $0/hr | ~$0.01/hr (disk only) |
| Deleted pod (full scale-to-zero) | $0/hr | $0/hr |
| **Idle timeout (20 min default)** | $0.86/hr while active | ~$0.29 per idle cycle then $0 |

## Boot Time After Scale-to-Zero

When traffic arrives after the pod has been terminated:

| Scenario | Time |
|----------|------|
| Stopped pod (warm standby) — start | ~2 min (engine load only) |
| New pod (cold start, image cached) | ~5 min (image extract + engine load) |
| New pod (cold start, first pull) | ~15 min (image pull + engine load) |

**Recommendation**: Keep 1-2 pods in stopped state ($0.01/hr each) for fast ~2 min restarts. Let the idle timeout handle scale-down, and the control plane restart stopped pods on demand rather than creating new ones.

## Without Humanik Cloud

Idle timeout is disabled when Humanik Cloud env vars are missing. The server runs indefinitely until manually stopped. This is the expected behavior for development and standalone deployments.

## Implementation

- **Monitor**: `src/heartbeat/load_tracker.py` — `start_idle_timeout()`, `_idle_monitor()`
- **Integration**: `src/server.py` — starts monitor in lifespan after engine init, triggers `graceful_shutdown("idle-timeout")`
