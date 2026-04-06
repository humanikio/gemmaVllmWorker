# Idle Timeout & Scale-to-Zero

The worker monitors request load and signals the control plane after a configurable idle period. This enables scale-to-zero on Humanik Cloud — pods are paused (warm standby) or destroyed when not in use and resumed/recreated on demand.

## How It Works

1. Every 60 seconds, the idle monitor checks: is `load == 0` and has it been idle for longer than `IDLE_TIMEOUT_MINUTES`?
2. If yes: initiates graceful shutdown → signals control plane → CP pauses the pod
3. If no: logs current idle time and continues monitoring

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `IDLE_TIMEOUT_MINUTES` | `20` | Minutes of zero load before triggering pause |

**Special values**:
- `0` = persistent mode (never auto-terminate). Useful for always-on endpoints.
- Any positive integer = pause after that many idle minutes.

## Pause vs Destroy

The control plane decides what to do when it receives the idle-timeout signal:

| Action | When | GPU Cost | Resume Time |
|--------|------|----------|-------------|
| **Pause** (stopPod) | `maxPausedInstances` not reached | $0/hr (disk ~$0.01/hr) | ~2-3 min |
| **Destroy** (destroyPod) | `maxPausedInstances = 0` or at limit | $0/hr | ~15 min cold start |

The worker doesn't know whether it will be paused or destroyed — it just signals `idle-timeout` and waits for external termination. The CP reads `maxPausedInstances` from the service config manifest to decide.

## Idle Timeout → Pause Flow

```
Worker: load=0 for 20 min
  → graceful_shutdown("idle-timeout")
  → stop heartbeat, publish signal, set _shutdown_signaled=True
  → DO NOT deregister (hash stays for CP to transition to 'paused')
  → wait for SIGTERM

CP receives signal:
  → stopPod(podId) via RunPod API
  → pauseInstance() in Redis → status='paused', TTL=24h

RunPod stops container → SIGTERM to worker:
  → lifespan exit → graceful_shutdown("shutdown")
  → _shutdown_signaled=True → SKIP (no second signal)
  → close Redis, process exits
```

## Resume on Next Request

When a request arrives and the ALB finds a paused pod:

```
Request → ALB sees pausedCount=1, healthyCount=0
  → resumePod(podId) via RunPod API
  → Redis: paused → booting (TTL=warmStartTimeoutMs)
  → orchestrator polls every 2s (max warmStartTimeoutMs = 3 min)
  → pod boots, heartbeat starts, status=healthy
  → request routes through
```

## Cost Impact

| Strategy | GPU Cost | Idle Cost |
|----------|----------|-----------|
| Running continuously (L40S) | $0.86/hr | $0.86/hr |
| Paused pod (warm standby) | $0/hr | ~$0.01/hr (disk only) |
| Destroyed pod (full scale-to-zero) | $0/hr | $0/hr |
| **Idle timeout (20 min default)** | $0.86/hr while active | $0.29 per idle cycle then ~$0.01/hr paused |

## Scaling Policy (from manifest)

| Field | gemmaWorker | Description |
|-------|-------------|-------------|
| `maxInstances` | 2 | Max running pods (healthy + booting) |
| `maxPausedInstances` | 1 | Max stopped pods kept for warm resume |
| `coldStartTimeoutMs` | 900,000 (15 min) | Polling timeout for new pod |
| `warmStartTimeoutMs` | 180,000 (3 min) | Polling timeout for resumed pod |

Total possible RunPod pods at any time: `maxInstances + maxPausedInstances` = 3.

## Without Humanik Cloud

Idle timeout is disabled when Humanik Cloud env vars are missing. The server runs indefinitely until manually stopped. This is the expected behavior for development and standalone deployments.

## Implementation

- **Monitor**: `src/heartbeat/load_tracker.py` — `start_idle_timeout()`, `_idle_monitor()`
- **Shutdown**: `src/heartbeat/__init__.py` — `graceful_shutdown()`, `_shutdown_signaled` guard
- **Integration**: `src/server.py` — starts monitor in lifespan after engine init
