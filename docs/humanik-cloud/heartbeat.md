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
| `status` | string | `booting`, `healthy`, `draining`, or `unhealthy` |
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
              shutdown signal   → status: draining (finish in-flight)
                                    ↓
              deregister        → removed from Redis
```

| Status | ALB Behavior |
|--------|-------------|
| `booting` | Visible but not routable — prevents ALB from spawning duplicates |
| `healthy` | Routable — receives traffic |
| `draining` | In-flight only — no new requests |
| `unhealthy` | Not routable |

## Load Tracking

The worker tracks concurrent requests via `increment_load()` / `decrement_load()` calls in the request handler. The ALB reads this value to make routing decisions (prefer instances with lower load).

## Termination Signals

When the worker shuts down (idle timeout, SIGTERM, or unhealthy), it publishes a message to Redis:

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

The control plane subscribes to this channel and destroys the pod via the RunPod API.

## Graceful Shutdown Sequence

1. Stop heartbeat interval
2. Stop idle timeout monitor
3. Publish termination signal to Redis
4. Deregister from Redis (delete hash + remove from active set)
5. Close Redis connection

## Without Humanik Cloud

When `NEXUS_TENANT_ID`, `NEXUS_SERVICE_ID`, `NEXUS_INSTANCE_ID`, or `NEXUS_REDIS_URL` are missing, the heartbeat system silently disables. No Redis connections are made, no errors are logged. The server runs as a standard standalone HTTP server.

## Implementation

| File | Role |
|------|------|
| `src/heartbeat/__init__.py` | Start/stop lifecycle, graceful shutdown |
| `src/heartbeat/config.py` | Reads env vars, builds Redis keys and routing JSON |
| `src/heartbeat/heartbeat_service.py` | Redis writes, status transitions, termination signals |
| `src/heartbeat/load_tracker.py` | Concurrent request counter, idle timeout monitor |
