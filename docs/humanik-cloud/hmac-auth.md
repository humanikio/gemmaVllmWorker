# HMAC Authentication

The worker gates all inference endpoints behind HMAC-SHA256 signature verification. Only the Humanik Cloud control plane (which holds the shared secret) can sign valid requests. This prevents direct access to the pod's public URL.

## How It Works

1. Control plane constructs the message: `{timestamp}.{method}.{path}`
2. Signs it with `CP_INSTANCE_HMAC_SECRET` using HMAC-SHA256
3. Sends the signature and timestamp as headers
4. Worker reconstructs the same message, generates expected signature, and compares

## Headers

| Header | Value | Example |
|--------|-------|---------|
| `x-hmac-signature` | Hex-encoded HMAC-SHA256 | `a1b2c3d4e5f6...` |
| `x-hmac-timestamp` | Unix timestamp (milliseconds) | `1775406503000` |

## Message Format

```
{timestamp}.{method}.{path}
```

Example for a POST to `/v1/chat/completions`:
```
1775406503000.POST./v1/chat/completions
```

Body is excluded from the signature — proxy services cannot parse the body without consuming the stream needed for forwarding.

## Security Features

- **Replay protection**: Requests older than 5 minutes are rejected
- **Timing-safe comparison**: Uses `hmac.compare_digest()` to prevent timing attacks
- **Exempt paths**: `/health` and `/ready` bypass HMAC (needed for load balancer probes)

## Endpoints

| Endpoint | Auth |
|----------|------|
| `GET /health` | No auth |
| `GET /ready` | No auth |
| `POST /v1/chat/completions` | HMAC required |
| `POST /v1/completions` | HMAC required |
| `GET /v1/models` | HMAC required |

## Testing with curl

```bash
# Generate signature
TIMESTAMP=$(python3 -c "import time; print(int(time.time() * 1000))")
SECRET="your-shared-secret"
MESSAGE="${TIMESTAMP}.POST./v1/chat/completions"
SIGNATURE=$(echo -n "$MESSAGE" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

# Send request
curl -s https://<pod-url>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-hmac-signature: ${SIGNATURE}" \
  -H "x-hmac-timestamp: ${TIMESTAMP}" \
  -d '{"model":"gemma-4-26b-moe","messages":[{"role":"user","content":"Hello"}],"max_tokens":50}'
```

## Without HMAC

If `CP_INSTANCE_HMAC_SECRET` is not set, the middleware returns `500 Server Configuration Error` on all protected routes. For standalone use without Humanik Cloud, either:
1. Set `CP_INSTANCE_HMAC_SECRET` to any value and sign your own requests
2. Remove the `CpHmacMiddleware` line from `server.py`

## Implementation

- **Middleware**: `src/middleware/cp_hmac_auth.py`
- **Pattern**: Ported from `hos-openClaw/src/middleware/cpHmacAuth.ts`
