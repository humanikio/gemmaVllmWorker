# Heartbeat System

The worker sends periodic heartbeats to Redis so the Humanik Cloud ALB (Application Load Balancer) can discover instances, track their health, and make routing decisions.

## How It Works

Every 10 seconds, the worker writes a Redis hash with instance metadata and sets a 30-second TTL. If the worker stops heartbeating (crash, network issue), the key expires and the ALB stops routing to it.

## Redis Data Structure

**Hash key**: `machines:{serviceId}:{instanceId}`
**TTL**: 30 seconds (refreshed every heartbeat)

| Field | Type | Description |
|-------|------|-------------|
| `instanceId` | string | Unique instance identifier |
| `serviceId` | string | Service this instance belongs to |
| `tenantId` | string | Tenant owner |
| `providerRouting` | JSON string | `{"provider":"runpod","podId":"abc123"}` — how to reach this instance |
| `load` | string | Current concurrent request count |
| `lastHeartbeat` | string | Unix millisecond timestamp |
| `status` | string | `booting`, `healthy`, `draining`, `paused`, or `unhealthy` |
| `region` | string | Datacenter region |
| `startedAt` | string | Instance boot time (Unix ms) |
| `customMetadata` | JSON string | Extensible metadata |

**Set key**: `machines:{serviceId}:active`
Active instance membership set for quick lookups. No TTL — cleaned up on deregister or key expiry.

## Status Lifecycle

```
Pod created → heartbeat starts → status: booting
                                    ↓
              vLLM engine loaded → status: healthy (ALB routes traffic)
                                    ↓
              idle timeout       → signal CP → CP calls stopPod
                                    ↓
              CP sets status     → status: paused (24h TTL, no heartbeats)
                                    ↓
              next request       → CP calls resumePod → status: booting → healthy
```

| Status | ALB Behavior | TTL |
|--------|-------------|-----|
| `booting` | Visible but not routable — prevents duplicate spawns | coldStartTimeoutMs (900s) |
| `healthy` | Routable — receives traffic | 30s (heartbeat refreshed) |
| `draining` | In-flight only — no new requests | 30s |
| `paused` | Not routable — resumable on next request | 24h (no heartbeats) |
| `unhealthy` | Not routable | 30s |

## Load Tracking

The worker tracks concurrent requests via `increment_load()` / `decrement_load()` calls in the request handler. The ALB reads this value to make routing decisions (prefer instances with lower load).

## Termination Signals

When the worker shuts down, it publishes a message to Redis:

**Channel**: `instance:terminate:{serviceId}`

```json
{
  "instanceId": "inst_a1b2c3d4e5f6",
  "serviceId": "svc_gemma",
  "tenantId": "tenant_abc",
  "podId": "abc123xyz",
  "provider": "runpod",
  "reason": "idle-timeout"
}
```

The control plane subscribes to this channel and acts based on `reason`:

| Reason | CP Action |
|--------|-----------|
| `idle-timeout` | `stopPod` (pause, keep disk) + set Redis status='paused' |
| `shutdown` | `destroyPod` (full termination) + remove from Redis |
| `unhealthy` | `destroyPod` (full termination) + remove from Redis |

## Graceful Shutdown Sequence

Shutdown behavior depends on the reason:

### idle-timeout (RunPod pause)
1. Set `_shutdown_signaled = True` (guards against duplicate signals)
2. Stop heartbeat interval
3. Stop idle timeout monitor
4. Publish termination signal (reason=idle-timeout)
5. Do NOT deregister — CP needs the hash intact to transition to 'paused'
6. Wait for SIGTERM from RunPod (after CP calls stopPod)
7. SIGTERM arrives → lifespan exit calls `graceful_shutdown("shutdown")`
8. Guard detects `_shutdown_signaled` → skips signal/deregister, closes Redis

### shutdown / unhealthy (full termination)
1. Set `_shutdown_signaled = True`
2. Stop heartbeat interval
3. Stop idle timeout monitor
4. Publish termination signal
5. Deregister from Redis (delete hash + remove from active set)
6. Close Redis connection

### Why the shutdown guard exists

After idle-timeout, RunPod stops the container (SIGTERM). Uvicorn catches SIGTERM and runs the lifespan exit, which calls `graceful_shutdown("shutdown")` a second time. Without the guard, this would publish a `shutdown` signal to the CP, causing it to destroy the pod that was just paused. The `_shutdown_signaled` flag prevents this double-signal.

## Without Humanik Cloud

When `NEXUS_TENANT_ID`, `NEXUS_SERVICE_ID`, `NEXUS_INSTANCE_ID`, or `NEXUS_REDIS_URL` are missing, the heartbeat system silently disables. No Redis connections are made, no errors are logged. The server runs as a standard standalone HTTP server.

## Implementation

| File | Role |
|------|------|
| `src/heartbeat/__init__.py` | Start/stop lifecycle, graceful shutdown, shutdown guard |
| `src/heartbeat/config.py` | Reads env vars, builds Redis keys and routing JSON |
| `src/heartbeat/heartbeat_service.py` | Redis writes, status transitions, termination signals |
| `src/heartbeat/load_tracker.py` | Concurrent request counter, idle timeout monitor |
