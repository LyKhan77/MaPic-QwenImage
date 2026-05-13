# MaPic Vercel + Cloudflare Tunnel — Troubleshooting Guide

## Architecture Overview

```
User Browser
    |
    +--> Vercel CDN (https://mapic-glm.vercel.app)
    |       Serves React SPA (static files)
    |
    +--> Cloudflare Edge --> Named Tunnel --> Local Backend :8181
            (https://api.mapic-backend.site)
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
| Backend tunnel | `https://api.mapic-backend.site` | **Named tunnel — permanent URL** |
| Backend health | `https://api.mapic-backend.site/api/health` | Check if backend is alive |
| Backend local | `http://localhost:8181/api/health` | Local check without tunnel |
| GLM-Image local | `http://localhost:30000/health` | Inference server, local only |
| Vercel dashboard | `https://vercel.com/lees-projects-80730ffd/mapic-glm` | Settings, env vars, logs |
| GitHub repo | `https://github.com/LyKhan77/MaPic-GLM` | Connected to Vercel (auto-deploy) |
| Domain registrar | Hostinger (`mapic-backend.site`) | DNS managed by Cloudflare |

> **Status:** Named tunnel is active. `api.mapic-backend.site` is the permanent backend URL. Tunnel notification banner will never appear.

---

## Quick Health Check

```bash
# Check all local services
curl -s http://localhost:30000/health | python3 -m json.tool   # GLM-Image Server
curl -s http://localhost:8181/api/health                        # Backend
systemctl status mapic-glm                                      # systemd service
pgrep -a cloudflared                                            # Tunnel process

# Check tunnel
curl -s https://api.mapic-backend.site/api/health

# Check the tunnel is hitting the CORRECT backend (not ProtoScale or other services)
curl -s https://api.mapic-backend.site/openapi.json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['title'])"
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
cloudflared tunnel run mapic-backend
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

### 2. VITE_API_URL env var is wrong in Vercel

Check in Vercel dashboard: https://vercel.com -> mapic-glm -> Settings -> Environment Variables

Expected value: `https://api.mapic-backend.site/api`

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
  https://api.mapic-backend.site/api/health 2>&1 | grep "access-control-allow-origin"
# Expected: access-control-allow-origin: https://mapic-glm.vercel.app
```

---

## Problem: Tunnel hits wrong backend (ProtoScale or other service)

This happened because `~/.cloudflared/config.yml` had a hardcoded ingress pointing to `localhost:8077` (ProtoScale). The `--url` flag can be overridden by this config file.

**Check:**
```bash
cat ~/.cloudflared/config.yml
curl -s https://api.mapic-backend.site/openapi.json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['title'])"
# WRONG: "ProtoScale-AI Backend"
# CORRECT: "Mapic API"
```

**Fix:**
```bash
# Edit the ingress to point to MaPic backend
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: 1ca1d240-1072-4486-b97b-f12f0f973385
credentials-file: /home/gspe-ai3/.cloudflared/1ca1d240-1072-4486-b97b-f12f0f973385.json

ingress:
  - hostname: api.mapic-backend.site
    service: http://localhost:8181
  - service: http_status:404
EOF

# Restart tunnel
kill $(pgrep -f "cloudflared tunnel")
cloudflared tunnel run mapic-backend
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

## Frontend Update Workflow

Every time you push frontend changes to `vercel/conf`, Vercel auto-deploys. If it doesn't, or you need a manual deploy:

```bash
# 1. Verify build passes locally first
cd ~/project_cv/MaPic/frontend
npx tsc --noEmit && npx vite build

# 2a. Auto-deploy via git push (Vercel watches vercel/conf branch)
cd ~/project_cv/MaPic
git push origin vercel/conf

# 2b. Manual deploy (if auto-deploy fails or is disabled)
cd ~/project_cv/MaPic/frontend && vercel --prod
```

**Troubleshooting failed deployments:**

```bash
# Check deployment logs
vercel logs

# Check env vars are set (VITE_ vars must exist for build)
vercel env ls

# Force redeploy from CLI
vercel --prod

# If vercel CLI is not linked, re-link first
cd ~/project_cv/MaPic/frontend && vercel link --yes
```

**Production branch:** Set to `vercel/conf` in Vercel Dashboard > Settings > Git > Production Branch.

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
ExecStart=/usr/local/bin/cloudflared tunnel run mapic-backend
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cloudflared-mapic
sudo systemctl start cloudflared-mapic
```

For a named tunnel, the ExecStart is already set to `cloudflared tunnel run mapic-backend`.

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
| `~/.cloudflared/config.yml` | Named tunnel `mapic-backend` with `api.mapic-backend.site` hostname |

---

## Checklist: Fresh Machine Setup

1. Start local services: `bash start-app.sh` (or systemd)
2. Start named tunnel: `cloudflared tunnel run mapic-backend`
3. Verify: `curl -s https://api.mapic-backend.site/api/health`
4. Open `https://mapic-glm.vercel.app` in browser
