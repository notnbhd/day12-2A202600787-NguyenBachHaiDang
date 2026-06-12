# Deployment Information

> **Student:** Nguyen Bach Hai Dang · **ID:** 2A202600787

## Public URL

```
https://<your-service>.onrender.com      ← FILL IN after deploy
```

## Platform

**Render** — Web Service, Docker runtime, region Singapore.
Root directory: `06-lab-complete/`

## Test Commands

### 1. Health Check (no auth)
```bash
curl https://<your-service>.onrender.com/health
# Expected 200:
# {"status":"ok","version":"1.0.0","environment":"production", ...}
```

### 2. Readiness probe
```bash
curl https://<your-service>.onrender.com/ready
# Expected 200: {"ready": true}
```

### 3. Auth required (no key → 401)
```bash
curl -i -X POST https://<your-service>.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Hello"}'
# Expected: HTTP/1.1 401 Unauthorized
```

### 4. API test (with key → 200)
```bash
curl -X POST https://<your-service>.onrender.com/ask \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is deployment?"}'
# Expected 200: {"question":"...","answer":"...","model":"gpt-4o-mini","timestamp":"..."}
```

### 5. Rate limiting (eventually → 429)
```bash
for i in $(seq 1 25); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST https://<your-service>.onrender.com/ask \
    -H "X-API-Key: YOUR_AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"question":"test"}'
done
# Expected: 200 ... then 429 after the per-minute limit (default 20/min)
```

## Environment Variables Set on Render

| Key | Value | Notes |
|-----|-------|-------|
| `ENVIRONMENT` | `production` | Disables /docs, enforces secret validation |
| `APP_VERSION` | `1.0.0` | |
| `AGENT_API_KEY` | *(generated / secret)* | Required — used in `X-API-Key` header |
| `JWT_SECRET` | *(generated / secret)* | Required in production |
| `RATE_LIMIT_PER_MINUTE` | `20` | |
| `DAILY_BUDGET_USD` | `5.0` | Cost guard |
| `OPENAI_API_KEY` | *(empty)* | Empty → uses mock LLM (no real cost) |
| `PORT` | `8000` | Match the port the container listens on |

> Copy your real `AGENT_API_KEY` from Render → Service → Environment.

## Screenshots

- ![Deployment dashboard](screenshots/dashboard.png)
- ![Service running / health 200](screenshots/running.png)
- ![Test results (auth + rate limit)](screenshots/test.png)
