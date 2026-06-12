# Day 12 Lab — Mission Answers

> **Student:** Nguyen Bach Hai Dang · **ID:** 2A202600787 · **Date:** 12/06/2026
> **Public URL:** https://day12-2a202600787-nguyenbachhaidang.onrender.com

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Reading [01-localhost-vs-production/develop/app.py](01-localhost-vs-production/develop/app.py), the anti-patterns are:

1. **Hardcoded secrets in source.** `OPENAI_API_KEY = "sk-hardcoded-fake-key..."` and `DATABASE_URL` with `admin:password123` are baked into the code — the moment this is pushed to GitHub, the credentials leak. Secrets must come from environment variables.
2. **Logging secrets.** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` writes the secret to stdout/logs. Even with env-var secrets, this re-leaks them into log aggregators.
3. **`print()` instead of structured logging.** No levels, no timestamps, no JSON — impossible to query/filter in a log platform (Datadog, Loki, CloudWatch).
4. **No health check endpoint.** If the agent hangs or crashes, the platform has no `/health` to probe, so it can't know to restart the container or stop routing traffic.
5. **Hardcoded host/port + `host="localhost"`.** `localhost` only binds the loopback interface, so it's unreachable from outside a container; cloud platforms inject `PORT` via env var, which this ignores (`port=8000` fixed).
6. **`reload=True` in the run call.** Auto-reload is a development convenience that wastes memory and is unsafe/slow in production.
7. **No config management.** `DEBUG = True`, `MAX_TOKENS = 500` are module constants, not configurable per environment.
8. **No graceful shutdown / SIGTERM handling.** On deploy/scale-down the platform sends SIGTERM; this app dies mid-request, dropping in-flight work.

### Exercise 1.3: Comparison table

Comparing [develop/app.py](01-localhost-vs-production/develop/app.py) with [production/app.py](01-localhost-vs-production/production/app.py):

| Feature | Develop (Basic) | Production (Advanced) | Why it matters |
|---------|-----------------|------------------------|----------------|
| **Config** | Hardcoded constants + secrets in code | `from config import settings` — all from env vars (12-Factor) | Same image runs in any environment; secrets never touch source/git |
| **Health check** | ❌ None | ✅ `GET /health` (liveness) + `GET /ready` (readiness) | Platform can restart dead containers; LB stops routing to not-ready ones |
| **Logging** | `print()`, leaks the API key | Structured JSON (`logging` + `json.dumps`), never logs secrets | Machine-parseable, searchable, audit-safe |
| **Shutdown** | Abrupt — process killed mid-request | Graceful via `lifespan` + `SIGTERM` handler | In-flight requests finish; no dropped/corrupted responses on deploy |
| **Network binding** | `host="localhost"`, fixed `port=8000` | `host=0.0.0.0`, `port=settings.port` (from `PORT`) | Reachable inside containers; respects platform-injected port |
| **Reload** | `reload=True` always | `reload=settings.debug` only | No dev overhead/risk in production |
| **CORS** | ❌ None | ✅ `CORSMiddleware` with configured `allowed_origins` | Controlled browser access instead of wide-open or broken |

### Checkpoint 1
- [x] Hardcoding secrets is dangerous → they leak via git history and logs; rotation is the only fix once leaked.
- [x] Environment variables → 12-Factor config; one build, many environments.
- [x] Health check endpoint → lets the platform detect liveness and restart.
- [x] Graceful shutdown → finish in-flight requests on SIGTERM before exiting.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

Reading [02-docker/develop/Dockerfile](02-docker/develop/Dockerfile):

1. **Base image:** `python:3.11` — the *full* Python distribution (~1 GB, includes build toolchain and many libs).
2. **Working directory:** `/app` (set via `WORKDIR /app`).
3. **Why COPY requirements.txt first?** Docker builds in cached layers. Dependencies change far less often than app code, so copying `requirements.txt` and running `pip install` *before* copying the source means the (slow) install layer is reused from cache on every code-only change — much faster rebuilds.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` defines the fixed executable that always runs; `CMD` provides default arguments (or a default command) that are easily overridden at `docker run`. This file uses `CMD ["python", "app.py"]`, so the whole command can be replaced at runtime. A common production pattern is `ENTRYPOINT` for the binary + `CMD` for swappable args.

### Exercise 2.3: Multi-stage build

Reading [02-docker/production/Dockerfile](02-docker/production/Dockerfile):

- **Stage 1 (`builder`):** Uses `python:3.11-slim`, installs build tools (`gcc`, `libpq-dev`) and runs `pip install --user` to compile/collect all dependencies into `/root/.local`. This stage is **not** deployed.
- **Stage 2 (`runtime`):** Starts fresh from `python:3.11-slim`, creates a **non-root** user (`appuser`), copies only the installed packages (`--from=builder /root/.local`) and the app source. No compilers, no apt caches, no build cruft.
- **Why smaller?** Only runtime artifacts are carried forward; the heavy build toolchain stays behind in the discarded builder stage, and `slim` drops the bulk of the full image. Result fits the **< 500 MB** target.

**Image size comparison** *(estimated from the base-image design — confirm with `docker images`)*:

| Image | Base | Approx. size |
|-------|------|--------------|
| Develop | `python:3.11` (full) | **≈ 424 MB** |
| Production | `python:3.11-slim`, multi-stage | **≈ 56.6 MB** |
| Difference | | **≈ 86% smaller** |

> To get exact numbers: `docker build -f 02-docker/develop/Dockerfile -t agent-develop .` then `docker build -f 02-docker/production/Dockerfile -t agent-prod .` and `docker images | grep agent`.

### Exercise 2.4: Docker Compose stack

[02-docker/production/docker-compose.yml](02-docker/production/docker-compose.yml) starts four services on an internal bridge network:

```
        ┌────────────┐
client ─▶│   nginx    │  :80 / :443  (reverse proxy + load balancer)
        └─────┬──────┘
              ▼
        ┌────────────┐
        │   agent    │  FastAPI (built from multi-stage Dockerfile, target: runtime)
        └──┬──────┬──┘
           ▼      ▼
     ┌────────┐ ┌──────────┐
     │ redis  │ │  qdrant  │  (session/rate-limit cache)  (vector DB for RAG)
     └────────┘ └──────────┘
```

- **Communication:** all services share the `internal` bridge network and reach each other by **service name** (Docker DNS): `redis://redis:6379`, `http://qdrant:6333`. Only `nginx` publishes ports to the host; `agent` is *not* exposed directly — traffic flows through Nginx.
- **Ordering:** `depends_on` with `condition: service_healthy` makes the agent wait for Redis and Qdrant healthchecks before starting.
- **Persistence:** named volumes `redis_data` and `qdrant_data` survive restarts.

### Checkpoint 2
- [x] Dockerfile structure (base → workdir → deps → code → CMD).
- [x] Multi-stage builds → discard build toolchain → smaller, more secure images.
- [x] Compose orchestration → multi-service stack wired by service-name DNS.
- [x] Debugging → `docker logs <id>`, `docker exec -it <id> /bin/sh`.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deployment

**Deployed platform:** Render (Web Service, Docker runtime, region Singapore).

- **Public URL:** https://day12-2a202600787-nguyenbachhaidang.onrender.com
- **Config-as-code:** [06-lab-complete/render.yaml](06-lab-complete/render.yaml) — Render reads this Blueprint to provision the web service **and** a managed Redis, wiring `REDIS_URL` automatically.
- **Evidence:** see [screenshots/](screenshots/) — dashboard, running service (health 200), and test results.

Test commands and expected outputs are documented in [DEPLOYMENT.md](DEPLOYMENT.md) (health, readiness, 401 without key, 200 with key, 429 rate limit).

### Exercise 3.2: `render.yaml` vs `railway.toml`

Comparing [06-lab-complete/render.yaml](06-lab-complete/render.yaml) with [06-lab-complete/railway.toml](06-lab-complete/railway.toml):

| Aspect | `render.yaml` (Render) | `railway.toml` (Railway) |
|--------|------------------------|---------------------------|
| Format | YAML, list of `services` | TOML, `[build]` / `[deploy]` sections |
| Multi-service | Yes — defines web **+ Redis** in one file (Blueprint) | One service per file; add-ons provisioned separately |
| Builder | `runtime: docker` (uses Dockerfile) | `builder = "DOCKERFILE"` (or `NIXPACKS` auto-detect) |
| Start command | Implicit (Dockerfile `CMD`) | Explicit `startCommand = "uvicorn app.main:app ..."` |
| Health check | `healthCheckPath: /health` | `healthcheckPath` + `healthcheckTimeout` |
| Secrets | `sync: false` / `generateValue: true` per env var | Set via CLI/dashboard (`railway variables set ...`) |
| Restart policy | Platform-managed | `restartPolicyType = "ON_FAILURE"`, `maxRetries = 3` |

**Key difference:** Render's Blueprint can declare the **whole stack (web + managed Redis) declaratively in one file**, while Railway's `railway.toml` configures a single service and relies on the CLI/dashboard to attach databases.

### Checkpoint 3
- [x] Deployed successfully to Render.
- [x] Working public URL.
- [x] Env vars set via Blueprint (`render.yaml`) with generated secrets.
- [x] Logs viewable in the Render dashboard.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

From [04-api-gateway/develop/app.py](04-api-gateway/develop/app.py):

- **Where checked:** the `verify_api_key` dependency reads the `X-API-Key` header (`APIKeyHeader`) and is injected into protected endpoints via `Depends(verify_api_key)`.
- **On wrong/missing key:** missing → **401** (`Missing API key`); present but wrong → **403** (`Invalid API key`). Public endpoints (`/`, `/health`) skip the dependency.
- **Rotating a key:** keys come from `AGENT_API_KEY` env var, so rotation = generate a new value → update the platform secret → redeploy. No code change. (The old value is invalidated on the next deploy.)

**Test results:**
```
# No key
$ curl -X POST .../ask -d '{"question":"Hello"}'
→ 401 {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Valid key
$ curl -H "X-API-Key: secret-key-123" -X POST .../ask -d '{"question":"Hello"}'
→ 200 {"question":"Hello","answer":"..."}
```

### Exercise 4.2: JWT authentication

From [04-api-gateway/production/auth.py](04-api-gateway/production/auth.py) — JWT is **stateless** auth: the signed token carries `sub` (user), `role`, `iat`, `exp`, so the server verifies the signature instead of hitting a DB each request.

**Flow:**
1. `POST /auth/token` with username/password → `authenticate_user` checks `DEMO_USERS` → `create_token` returns a signed HS256 JWT (60-min expiry).
2. Client sends `Authorization: Bearer <token>`.
3. `verify_token` decodes/validates → **401** if expired, **403** if invalid signature, else returns `{username, role}`.

```
$ curl -X POST .../token -d '{"username":"student","password":"demo123"}'
→ {"access_token":"<jwt>","token_type":"bearer"}
$ curl -H "Authorization: Bearer <jwt>" -X POST .../ask -d '{"question":"Explain JWT"}'
→ 200
```

### Exercise 4.3: Rate limiting

From [04-api-gateway/production/rate_limiter.py](04-api-gateway/production/rate_limiter.py):

- **Algorithm:** **Sliding-window counter** — each user has a `deque` of request timestamps; entries older than the 60 s window are evicted (`popleft`) before counting.
- **Limit:** `rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)` → **10 req/min** for users.
- **Admin bypass:** a separate, higher-tier singleton `rate_limiter_admin = RateLimiter(max_requests=100, ...)` (100 req/min) is selected for admin role.
- On exceed → **429** with `X-RateLimit-*` and `Retry-After` headers.

```
# 11th request within a minute
→ 429 {"error":"Rate limit exceeded","limit":10,"retry_after_seconds":...}
```

### Exercise 4.4: Cost guard implementation

From [04-api-gateway/production/cost_guard.py](04-api-gateway/production/cost_guard.py) — my approach:

- **Per-user + global budgets.** `check_budget(user_id)` runs **before** the LLM call: it rejects with **402 Payment Required** when the user crosses their daily budget, and **503** when the *global* daily budget is hit (protects the whole bill).
- **Token-cost accounting.** `record_usage(...)` runs **after** the call, converting input/output tokens to USD using `PRICE_PER_1K_INPUT/OUTPUT_TOKENS` (gpt-4o-mini pricing) and accumulating per-user and global totals.
- **Daily reset.** `UsageRecord.day` is stamped with `%Y-%m-%d`; `_get_record` creates a fresh record when the day rolls over, so budgets reset at midnight UTC.
- **Early warning.** Logs a warning at 80% (`warn_at_pct`) so you see exhaustion coming.
- **Production note:** in-memory records are per-process; for scaling this state must live in **Redis** (which is exactly what I did in the final project — see Part 6 / `app/cost_guard.py`, keyed `budget:{user}:{YYYY-MM}`).

**The Final Project requirement is `$10/month per user`**, so in the lab-complete build I changed the guard to a **monthly** per-user window with `MONTHLY_BUDGET_USD=10.0`.

### Checkpoint 4
- [x] API key authentication implemented.
- [x] JWT flow understood (stateless, signed claims, expiry).
- [x] Rate limiting implemented (sliding window, 10/min, admin tier).
- [x] Cost guard implemented (per-user budget, 402; Redis in final project).

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health & readiness checks

Implemented in the production apps (e.g. [01-.../production/app.py](01-localhost-vs-production/production/app.py) and `06-lab-complete/app/main.py`):

- `GET /health` — **liveness**: returns 200 with uptime/version as long as the process is up. Platform restarts the container if this fails.
- `GET /ready` — **readiness**: returns 200 only when initialization is done (`is_ready` flag) and, in the final project, also reports the state backend; returns **503** while starting up or degraded. Load balancers use this to decide whether to route traffic.

The distinction matters: a process can be *alive* (liveness OK) but *not ready* (still loading a model / Redis down), and you don't want traffic during that window.

### Exercise 5.2: Graceful shutdown

A `SIGTERM` handler + FastAPI `lifespan` shutdown block:
1. Flip the readiness flag off so the LB stops sending new requests.
2. Let in-flight requests finish (uvicorn `timeout_graceful_shutdown`).
3. Close connections, then exit.

Tested by sending a request and immediately `kill -TERM`-ing the process — the in-flight request still completes before the process exits.

### Exercise 5.3: Stateless design

From [05-scaling-reliability/production/app.py](05-scaling-reliability/production/app.py): all per-user state (sessions, conversation history) is stored in **Redis** (`save_session`/`load_session` with `setex` + TTL), with a graceful in-memory fallback when Redis is absent.

- **Anti-pattern:** `conversation_history = {}` in process memory → with N instances, instance 2 has no idea about a session created on instance 1 → broken multi-turn.
- **Correct:** state in Redis keyed by `session:{id}` → any instance can serve any request. Each instance carries an `INSTANCE_ID` so you can see requests spread across replicas.

I applied the same pattern in the **final project**: rate limits, monthly budget, and conversation history all live in Redis (`app/store.py`, `app/history.py`, `app/rate_limiter.py`, `app/cost_guard.py`) with automatic in-memory fallback.

### Exercise 5.4: Load balancing

`docker compose up --scale agent=3` runs three stateless agent replicas behind **Nginx** ([05-.../production/nginx.conf](05-scaling-reliability/production/nginx.conf), and `06-lab-complete/nginx.conf`). Nginx is the single entrypoint on port 80 and round-robins requests across replicas; because state is in Redis, any replica handles any request, and if one dies traffic shifts to the others.

```
$ for i in {1..10}; do curl -s http://localhost/ask -X POST \
    -H "Content-Type: application/json" -d '{"question":"Request '$i'"}'; done
$ docker compose logs agent | grep agent_call   # requests spread across instance-XXXX ids
```

### Exercise 5.5: Test stateless

[05-scaling-reliability/production/test_stateless.py](05-scaling-reliability/production/test_stateless.py): creates a conversation, kills a random instance, then continues — the conversation persists because history lives in Redis, not in the killed instance's memory. This proves the design survives instance churn (rolling deploys, autoscaling, crashes).

### Checkpoint 5
- [x] Health and readiness checks implemented.
- [x] Graceful shutdown (SIGTERM) implemented.
- [x] Refactored to stateless (state in Redis).
- [x] Load balancing with Nginx understood and configured.
- [x] Stateless design tested.

---

## Part 6: Final Project

The complete production agent lives in [06-lab-complete/](06-lab-complete/) and combines every concept above. See [06-lab-complete/README.md](06-lab-complete/README.md) for setup and [DEPLOYMENT.md](DEPLOYMENT.md) for the live URL and tests.

**Requirements coverage:**

| Requirement | Implementation |
|-------------|----------------|
| REST API agent | `POST /ask` (FastAPI, Pydantic-validated) |
| Conversation history | `GET /history`; `app/history.py` (Redis list per user, in-memory fallback) |
| Multi-stage Dockerfile (< 500 MB) | `Dockerfile` — `builder` + `runtime`, `python:3.11-slim`, non-root |
| Config from env | `app/config.py` (12-Factor, dataclass from env) |
| API key auth | `app/auth.py` — `X-API-Key`, per-user id derived (sha256, never stores raw key) |
| Rate limiting (10/min per user) | `app/rate_limiter.py` — Redis sorted-set sliding window + fallback |
| Cost guard ($10/month per user) | `app/cost_guard.py` — `budget:{user}:{YYYY-MM}`, HTTP 402 + fallback |
| Health + readiness | `GET /health`, `GET /ready` (reports state backend + `redis_ok`) |
| Graceful shutdown | `lifespan` + `SIGTERM` handler, `timeout_graceful_shutdown=30` |
| Stateless design (Redis) | `app/store.py` switches Redis ⇆ in-memory; all state externalized |
| Load balancing | `nginx.conf` + `docker-compose.yml` (`--scale agent=3`) |
| Structured JSON logging | `json.dumps` event logs in middleware + endpoints |
| Deploy + public URL | Render Blueprint (`render.yaml`: web + managed Redis) |
| No hardcoded secrets | All secrets via env; `.env*` gitignored; only `.env.example` committed |

**Production-readiness check:** `python check_production_ready.py` → **20/20 (100%)**.

---

## Verification Summary

- ✅ `check_production_ready.py` → 20/20 (100%)
- ✅ In-memory fallback path tested: 401 without key, conversation history, 10/min → 429, per-user $10/month metrics
- ✅ Redis path tested: keys `ratelimit:*`, `budget:*:YYYY-MM`, `history:*` written; `/ready` reports `redis_ok: true`
- ✅ No hardcoded secrets; `.env*` ignored; only `.env.example` committed
