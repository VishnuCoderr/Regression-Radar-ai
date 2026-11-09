# Production Deployment Guide — Regression Radar

This guide provides instructions for deploying Regression Radar to production environments, including Docker containers, Kubernetes, cloud platforms, and standalone servers.

---

## 1. Architecture Overview

Regression Radar operates as a unified service or separated frontend/backend topology:

```
[ Client / Browser / GitHub Webhook ]
                  │
                  ▼ (Port 80 / 443 via Reverse Proxy)
┌────────────────────────────────────────────────────────┐
│               Regression Radar Service                 │
│                                                        │
│  ┌─────────────────────────┐  ┌──────────────────────┐ │
│  │   FastAPI Backend (ASGI)│  │ React SPA Frontend   │ │
│  │   - Analysis Engines    │  │ (Compiled Static     │ │
│  │   - Git Subprocess      │  │  Assets via          │ │
│  │   - GitHub REST Client  │  │  FastAPI /assets)    │ │
│  │   - In-Memory LRU Cache │  │                      │ │
│  │   - CI Gate Evaluator   │  │                      │ │
│  └─────────────────────────┘  └──────────────────────┘ │
│                                                        │
│   Volume: /app/data (Persistence & Diagnostic Caches)  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Quick Start: Docker Compose

The fastest way to deploy Regression Radar is using Docker Compose:

```bash
# 1. Clone repository
git clone https://github.com/your-org/regression-radar.git
cd regression-radar

# 2. Configure environment
cp .env.example .env
# Edit .env with your GITHUB_TOKEN and CORS_ORIGINS

# 3. Build and launch
docker compose up -d --build

# 4. Verify deployment
curl -f http://localhost:8000/health/ready
```

Access the UI at `http://localhost:8000`.

---

## 3. Environment Variables Reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `PORT` | Integer | `8000` | HTTP listening port |
| `RR_HOST` | String | `0.0.0.0` | Bind IP address |
| `CORS_ORIGINS` | Comma-separated | `http://localhost:5173,...` | Allowed CORS origins |
| `GITHUB_TOKEN` | String (Secret) | None | GitHub token for API access |
| `GEMINI_API_KEY` | String (Secret) | None | Optional API key for AI summaries |
| `LOG_LEVEL` | String | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | String | `text` | `text` or `json` (for log collectors) |
| `STORAGE_PATH` | String / Path | `data` | Directory for persistent cache/reports |
| `SERVE_STATIC_UI` | Boolean | `true` | Serve React SPA from backend |
| `WEIGHTS_CONFIG` | Path | None | Path to custom weights TOML |

---

## 4. Production Health Checks & Probes

Regression Radar exposes dedicated liveness and readiness endpoints conforming to standard Kubernetes probe specifications:

### Liveness Probe (`GET /health/live` or `GET /health`)
- Verifies that the FastAPI process is running and responding to HTTP requests.
- Returns `HTTP 200` with `{"status": "healthy", "version": "0.1.0"}`.

### Readiness Probe (`GET /health/ready`)
- Verifies that critical runtime dependencies are functional:
  1. `git` binary is installed and executable on the system PATH.
  2. Persistent storage directory is writable.
  3. In-memory cache subsystems are operational.
- Returns `HTTP 200` with full diagnostic details when ready:
  ```json
  {
    "status": "ready",
    "version": "0.1.0",
    "git_available": true,
    "git_version": "git version 2.45.0",
    "storage_writable": true,
    "cache_entries": 3,
    "uptime_seconds": 124.5
  }
  ```
- Returns `HTTP 503 Service Unavailable` if Git is missing or storage is unwritable.

---

## 5. Security & Hardening Checklist

1. **Non-Root Container:** The production `Dockerfile` drops root privileges and runs as `appuser:appuser`.
2. **CORS Isolation:** Ensure `CORS_ORIGINS` is restricted to authorized domains in production; avoid wildcard `*`.
3. **Secret Protection:** Never embed `GITHUB_TOKEN` or `GEMINI_API_KEY` into image layers or commit them to version control. Pass them at runtime via Kubernetes Secrets or Docker Compose environment files.
4. **Untrusted Code Execution:** Regression Radar performs pure static Git metadata and diff parsing. It never executes code from analyzed repositories.
5. **Correlation Tracing:** Every HTTP request receives a unique `X-Request-ID` header, returned in error payloads and logged to facilitate end-to-end distributed tracing.

---

## 6. Kubernetes Deployment Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: regression-radar
  labels:
    app: regression-radar
spec:
  replicas: 2
  selector:
    matchLabels:
      app: regression-radar
  template:
    metadata:
      labels:
        app: regression-radar
    spec:
      containers:
        - name: regression-radar
          image: your-registry/regression-radar:latest
          ports:
            - containerPort: 8000
          env:
            - name: CORS_ORIGINS
              value: "https://radar.yourdomain.com"
            - name: GITHUB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: radar-secrets
                  key: github-token
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
```
