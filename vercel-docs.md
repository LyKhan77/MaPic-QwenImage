# MaPic Vercel + Cloudflare Tunnel — Troubleshooting Guide

## Architecture Overview

```
User Browser
    |
    +--> Vercel CDN (https://mapic-glm.vercel.app)
    |       Serves React SPA (static files)
    |
    +--> Cloudflare Edge --> Tunnel --> Local Backend :8181
            (https://<tunnel-url>.trycloudflare.com)
                                              |
                                              +--> GLM-Image Server :30000
```

**Three services must be running locally:**
1. GLM-Image Server (`:30000`) — managed by systemd `mapic-glm.service`
2. Backend FastAPI (`:8181`) — started via `start-app.sh`
3. Cloudflare Tunnel (`cloudflared`) — exposes backend to the internet

**One service runs remotely:**
4. Frontend SPA — deployed on Vercel

### Current URLs (Updated: 2026-05-12)

| Service | URL | Notes |
|---------|-----|-------|
| Frontend (Vercel) | `https://mapic-glm.vercel.app` | Permanent, never changes |
| Backend tunnel | `https://gives-fame-award-tony.trycloudflare.com` | **Changes on every restart** |
| Backend health | `https://gives-fame-award-tony.trycloudflare.com/api/health` | Check if backend is alive |
| Backend local | `http://localhost:8181/api/health` | Local check without tunnel |
| GLM-Image local | `http://localhost:30000/health` | Inference server, local only |
| Vercel dashboard | `https://vercel.com/lees-projects-80730ffd/mapic-glm` | Settings, env vars, logs |
| GitHub repo | `https://github.com/LyKhan77/MaPic-GLM` | Connected to Vercel (auto-deploy) |

> **Important:** When the tunnel is restarted, the `*.trycloudflare.com` URL will change. After restarting, update `VITE_API_URL` in Vercel and redeploy. See "Tunnel URL changed" section below.

---

## Quick Health Check

```bash
# Check all local services
curl -s http://localhost:30000/health | python3 -m json.tool   # GLM-Image Server
curl -s http://localhost:8181/api/health                        # Backend
systemctl status mapic-glm                                      # systemd service
pgrep -a cloudflared                                            # Tunnel process

# Check tunnel
TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cloudflared-tunnel.log | head -1)
curl -s "$TUNNEL_URL/api/health"

# Check the tunnel is hitting the CORRECT backend (not ProtoScale or other services)
curl -s "$TUNNEL_URL/openapi.json" | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['title'])"
# Expected output: "Mapic API"
```

---

## Problem: Frontend shows "Failed to connect" or "Offline"

### 1. Tunnel is not running

```bash
# Check if cloudflared process exists
pgrep -a cloudflared
```

**Fix:**
```bash
nohup cloudflared tunnel --url http://127.0.0.1:8181 > /tmp/cloudflared-tunnel.log 2>&1 &
sleep 5
grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cloudflared-tunnel.log | head -1
```

### 2. Tunnel URL changed (trycloudflare.com URLs are temporary)

Every restart generates a new URL. The Vercel deployment still points to the old URL.

**Fix:**
```bash
# Get the new tunnel URL
NEW_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cloudflared-tunnel.log | head -1)
echo "New tunnel URL: $NEW_URL"

# Update Vercel env var
cd ~/project_cv/MaPic/frontend
echo "$NEW_URL/api" | vercel env rm VITE_API_URL production --yes 2>/dev/null
echo "$NEW_URL/api" | vercel env add VITE_API_URL production

# Redeploy (VITE_ vars are baked at build time)
vercel --prod
```

### 3. Backend is not running

```bash
curl -s http://localhost:8181/api/health
```

**Fix:**
```bash
cd ~/project_cv/MaPic
bash start-app.sh
```

### 4. VITE_API_URL env var is wrong in Vercel

Check in Vercel dashboard: https://vercel.com -> mapic-glm -> Settings -> Environment Variables

Expected value format: `https://something.trycloudflare.com/api` (must include `/api` suffix)

**Fix:** Update via CLI or dashboard, then redeploy.

---

## Problem: CORS errors in browser console

Symptom: `Access-Control-Allow-Origin` errors, API calls blocked.

### 1. Vercel URL not in CORS_ORIGINS

The backend must explicitly allow the Vercel origin.

**Check:** `backend/config.py` default includes `https://mapic-glm.vercel.app`.
Or set via env: `CORS_ORIGINS=http://localhost:5151,...,https://mapic-glm.vercel.app`

**Fix:**
```bash
# Option A: Set env var
export CORS_ORIGINS="http://localhost:5151,http://localhost:5152,https://mapic-glm.vercel.app"

# Option B: Edit config.py default value (already done)

# Restart backend for change to take effect
```

### 2. Verify CORS is working

```bash
curl -sv -X OPTIONS \
  -H "Origin: https://mapic-glm.vercel.app" \
  -H "Access-Control-Request-Method: GET" \
  https://<tunnel-url>.trycloudflare.com/api/health 2>&1 | grep "access-control-allow-origin"
# Expected: access-control-allow-origin: https://mapic-glm.vercel.app
```

---

## Problem: Tunnel hits wrong backend (ProtoScale or other service)

This happened because `~/.cloudflared/config.yml` had a hardcoded ingress pointing to `localhost:8077` (ProtoScale). The `--url` flag can be overridden by this config file.

**Check:**
```bash
cat ~/.cloudflared/config.yml
curl -s https://<tunnel-url>/openapi.json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['title'])"
# WRONG: "ProtoScale-AI Backend"
# CORRECT: "Mapic API"
```

**Fix:**
```bash
# Edit the ingress to point to MaPic backend
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: d9bc0ea9-c99c-4e58-b7bf-563383931945
credentials-file: /home/gspe-ai3/.cloudflared/d9bc0ea9-c99c-4e58-b7bf-563383931945.json

ingress:
  - service: http://localhost:8181
EOF

# Restart tunnel
kill $(pgrep -f "cloudflared tunnel")
nohup cloudflared tunnel --url http://127.0.0.1:8181 > /tmp/cloudflared-tunnel.log 2>&1 &
```

---

## Problem: Vercel deployment fails

### Build errors

```bash
# Check build logs
vercel logs --output json

# Common issues:
# - TypeScript errors: run `npx tsc --noEmit` locally first
# - Missing env vars: VITE_ vars must be set BEFORE build
```

### Redeploy

```bash
cd ~/project_cv/MaPic/frontend
vercel --prod
```

---

## Problem: Supabase auth not working on Vercel

The frontend needs `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` baked into the build.

**Check:** Vercel dashboard -> mapic-glm -> Settings -> Environment Variables

Both must be set for **Production** environment. After adding, redeploy:

```bash
cd ~/project_cv/MaPic/frontend && vercel --prod
```

Also verify the Supabase dashboard has `https://mapic-glm.vercel.app` in **Authentication > URL Configuration > Site URL** and **Redirect URLs**.

---

## Cloudflare Tunnel — Full Reference

### Quick Tunnel (temporary, free, no domain)

```bash
# Start
nohup cloudflared tunnel --url http://127.0.0.1:8181 > /tmp/cloudflared-tunnel.log 2>&1 &
sleep 5
grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cloudflared-tunnel.log | head -1

# Stop
kill $(pgrep -f "cloudflared tunnel")

# Check logs
tail -50 /tmp/cloudflared-tunnel.log
```

### Named Tunnel (stable, requires domain + Cloudflare account)

```bash
# Login to Cloudflare (one-time)
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create mapic-backend

# Route DNS (api.yourdomain.com -> tunnel)
cloudflared tunnel route dns mapic-backend api.yourdomain.com

# Run the tunnel
cloudflared tunnel run mapic-backend

# List tunnels
cloudflared tunnel list

# Delete a tunnel
cloudflared tunnel delete mapic-backend
```

### Config file: `~/.cloudflared/config.yml`

```yaml
tunnel: <tunnel-id>
credentials-file: /home/gspe-ai3/.cloudflared/<tunnel-id>.json

ingress:
  - service: http://localhost:8181
```

**Important:** If this file exists, the `--url` flag may be ignored. The `ingress` rule determines where traffic goes. Always verify the ingress points to `localhost:8181`.

### Set up as systemd service (auto-start on boot)

```bash
sudo tee /etc/systemd/system/cloudflared-mapic.service << 'EOF'
[Unit]
Description=Cloudflare Tunnel for MaPic Backend
After=network.target

[Service]
Type=simple
User=gspe-ai3
ExecStart=/usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8181
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cloudflared-mapic
sudo systemctl start cloudflared-mapic
```

For a named tunnel, change ExecStart to:
```
ExecStart=/usr/local/bin/cloudflared tunnel run mapic-backend
```

---

## Vercel CLI — Quick Reference

```bash
# Login
vercel login

# Deploy to production
cd ~/project_cv/MaPic/frontend && vercel --prod

# List env vars
vercel env ls

# Add env var
echo "value" | vercel env add VAR_NAME production

# Remove env var
vercel env rm VAR_NAME production --yes

# View project info
vercel project ls

# Rename project
vercel project rename <old-name> <new-name>

# Set up domain alias
vercel alias <deployment-url> <name>.vercel.app

# View deployment logs
vercel logs
```

---

## Files Changed for Vercel Deployment

| File | Change |
|------|--------|
| `frontend/src/lib/api.ts` | `API_URL` reads `VITE_API_URL` env var with localhost fallback |
| `frontend/vercel.json` | SPA rewrite rule for client-side routing |
| `frontend/.gitignore` | Added `.vercel` directory |
| `backend/config.py` | Added `https://mapic-glm.vercel.app` to CORS_ORIGINS default |
| `~/.cloudflared/config.yml` | Ingress points to `localhost:8181` (was `8077`) |

---

## Checklist: Fresh Machine Setup

1. Start local services: `bash start-app.sh` (or systemd)
2. Start tunnel: `nohup cloudflared tunnel --url http://127.0.0.1:8181 > /tmp/cloudflared-tunnel.log 2>&1 &`
3. Get tunnel URL: `grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cloudflared-tunnel.log | head -1`
4. Update Vercel env var `VITE_API_URL` to `<tunnel-url>/api`
5. Redeploy: `cd frontend && vercel --prod`
6. Verify: open `https://mapic-glm.vercel.app` in browser
