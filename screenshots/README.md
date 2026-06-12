# Screenshots

Add these three after deploying to Render:

| File | What to capture |
|------|-----------------|
| `dashboard.png` | Render dashboard showing the service **Live** (green) |
| `running.png`   | Browser/terminal hitting `/health` → 200 `{"status":"ok"}` |
| `test.png`      | Terminal output of the `/ask` test (401 without key, 200 with key, 429 on rate limit) |

Referenced by `DEPLOYMENT.md`.
