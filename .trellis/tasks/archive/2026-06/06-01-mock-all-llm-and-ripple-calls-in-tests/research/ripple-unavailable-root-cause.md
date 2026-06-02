# Research: Ripple Engine Unavailable Root Cause

- **Query**: Why does "Ripple 引擎暂不可用" appear? Investigate Ripple CAS engine connectivity.
- **Scope**: internal
- **Date**: 2026-06-01

## Findings

### Root Cause: Network Isolation Between Containers

The `xhs-growth` container and `ripple-service` container are on **different networks** and cannot communicate.

| Container | Network Mode | Network | IP |
|---|---|---|---|
| `xhs-growth` | `slirp4netns` (rootless) | None (no bridge network) | N/A |
| `ripple-service` | `bridge` | `xhs-net` | `10.89.1.2` |

The `xhs-growth` container was started with `slirp4netns` network mode (default for rootless podman), which gives it **no access to any podman bridge networks**. The `ripple-service` container is on the `xhs-net` bridge network.

### Configuration Mismatch

| Setting | `.env` (host) | Container env (xhs-growth) |
|---|---|---|
| `RIPPLE_BASE_URL` | `http://127.0.0.1:8081` | `http://ripple-service:8080` |
| `RIPPLE_ENABLED` | `true` | `true` |
| `RIPPLE_API_TOKEN` | (empty) | (empty) |

The container's `RIPPLE_BASE_URL` is set to `http://ripple-service:8080` (Docker DNS name), but DNS resolution fails because the containers are not on the same network.

### Health Check Flow

1. `RippleService` is a singleton (`__new__` pattern), `_health_status` starts as `is_healthy=False` (line 19 of `ripple_service.py`)
2. When `predict_spread()` or `validate_pmf()` is called, it checks `self.is_healthy()` first (lines 255, 304)
3. If not healthy, `_get_service()` in `integration.py` (line 29-30) calls `health_check()` once
4. `health_check()` tries `GET {base_url}/healthz` with 5s timeout (line 107)
5. From inside the container, `http://ripple-service:8080/healthz` fails with `ConnectError: [Errno -2] Name or service not known`
6. Health status remains `is_healthy=False`
7. All subsequent calls return fallback data with `ripple_fallback: True`

### Frontend Display

The `RipplePanel.vue` component (line 30-34) detects fallback state by checking:
```typescript
const isFallback = computed(() => {
  if (!hasPrediction.value) return false
  const p = props.prediction
  return p.viral_probability === 0 && p.estimated_reach === 0 && p.confidence === 0
})
```

When fallback data is returned, all three values are 0, so `isFallback` is `true`, and the amber notice "Ripple 引擎暂不可用，以下为默认预测值" is displayed (line 106-109).

### Verification Tests

From the host machine, the Ripple service is reachable:
```
curl http://127.0.0.1:8081/healthz -> 200 OK
{"status":"ok","service":"ripple-http-sse","ts":"2026-06-01T07:48:38.455140+00:00"}
```

From inside the `xhs-growth` container, both URLs fail:
```
http://ripple-service:8080/healthz -> ConnectError: Name or service not known
http://127.0.0.1:8081/healthz -> ConnectError: All connection attempts failed
```

### System Health Endpoint

The `/api/system/health` endpoint (`system.py` line 55-71) has a `_check_ripple()` function that only checks env var configuration, not actual connectivity. It considers the service "configured" if `base_url` is set and either `api_token` is set or the URL contains "127.0.0.1"/"localhost". The container URL `http://ripple-service:8080` does NOT contain those strings, and `api_token` is empty, so the system health check would report `status: "warning"` even though the env var is set.

### Files Found

| File Path | Description |
|---|---|
| `backend/services/ripple_service.py` | RippleService singleton with health check, retry, fallback |
| `backend/tools/ripple/integration.py` | Integration layer calling RippleService |
| `backend/config/settings.py` | RippleSettings with env_prefix="RIPPLE_" |
| `backend/api/routes/system.py` | System health check (config-only, no connectivity test) |
| `backend/api/app.py` | FastAPI app with lifespan (no Ripple health check on startup) |
| `frontend/src/components/RipplePanel.vue` | Frontend panel showing fallback notice |
| `frontend/src/locales/zh-CN.json:256` | "Ripple 引擎暂不可用，以下为默认预测值" |
| `.env` | RIPPLE_BASE_URL=http://127.0.0.1:8081 |
| `Dockerfile` | Container build (no network config) |

### Code Patterns

1. **Singleton pattern**: `RippleService.__new__` ensures one instance, but `_health_status` is a class variable initialized to `is_healthy=False` and never reset on app startup
2. **Lazy health check**: Health check only runs when a tool is first called, not at app startup
3. **Fallback detection**: Frontend uses heuristic (all zeros) rather than explicit `ripple_fallback` flag from state

## Caveats / Not Found

- No `docker-compose.yml` or `podman-compose.yml` found in the repo; containers appear to be started manually
- The `xhs-net` network exists but has **zero connected containers** according to `podman network inspect xhs-net` (the `ripple-service` container shows it in its config but the network shows no containers -- possible podman inspect inconsistency)
- The `xhs-growth` container uses `slirp4netns` which is the default for rootless podman; this mode cannot join bridge networks
- The fix requires either: (a) joining `xhs-growth` to `xhs-net` bridge network, or (b) using `--network host` mode for `xhs-growth`, or (c) using the host-mapped port `127.0.0.1:8081` with `--network host`
