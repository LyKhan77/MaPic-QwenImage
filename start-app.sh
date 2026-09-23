#!/bin/bash
#
# MaPic — menjalankan stack lewat Docker Compose.
#
# Sejak migrasi ke Docker (2026-09-23) skrip ini tidak lagi menyalakan service
# sendiri: ComfyUI, facade, backend, dan frontend semuanya container yang dikelola
# docker compose di deploy/docker/. Menyalakan service secara manual akan bentrok
# di port 5151 dan VRAM.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$ROOT/deploy/docker"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker tidak ditemukan di PATH." >&2
    exit 1
fi

cd "$COMPOSE_DIR"

if [ ! -f .env ]; then
    echo "Peringatan: $COMPOSE_DIR/.env belum ada."
    echo "Salin dari .env.example lalu isi VITE_API_URL dan kredensial Supabase anon."
    echo "Lanjut tanpa file itu: image frontend akan memakai nilai default."
    echo
fi

echo "Menjalankan stack MaPic (build bila image belum ada)..."
docker compose up -d

echo
docker compose ps

cat <<'EOF'

Alamat
  Frontend  : http://<ip-server>:5151
  Backend   : http://<ip-server>:8281/api
  ComfyUI   : http://127.0.0.1:8188  (debug; dari komputer lain pakai SSH tunnel)

Perintah lanjutan
  docker compose logs -f comfyui     log satu layanan
  docker compose ps                  status + healthcheck
  docker compose down                hentikan semua (model tetap di host)

Mode pengembangan frontend (hot reload) — jalankan terpisah, jangan bersamaan
dengan container frontend karena portnya sama:
  cd frontend && VITE_API_URL=http://localhost:8281/api npm run dev -- --port 5152
EOF
