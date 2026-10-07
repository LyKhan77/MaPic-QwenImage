"""Verifikasi token untuk endpoint API MaPic.

Endpoint pengguna memakai `require_user`: frontend mengirim
`Authorization: Bearer <access_token>`, backend memverifikasi tanda tangan token
lewat JWKS project (kunci asimetris ES256/RS256 yang dipakai Supabase), lalu
memakai claim `sub` sebagai identitas user. `user_id` yang dikirim klien di
body/URL tidak pernah dipercaya.

Endpoint service (`/api/service/*`) memakai `require_service_token`: Bearer token
mesin dari environment, dibandingkan constant-time, tanpa menyentuh JWKS.
"""

import secrets
from uuid import UUID

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

try:
    from backend.config import MAPIC_SERVICE_TOKEN, SUPABASE_URL
except ModuleNotFoundError:
    from config import MAPIC_SERVICE_TOKEN, SUPABASE_URL

ISSUER = f"{SUPABASE_URL.rstrip('/')}/auth/v1"

# Klien JWKS menyimpan kunci yang sudah diambil; `lifespan` membatasinya 1 jam
# supaya rotasi kunci Supabase ikut terbaca tanpa menambah latensi per request.
JWKS = PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def require_service_token(authorization: str | None = Header(default=None)) -> None:
    """Dependency FastAPI untuk route service: Bearer token mesin, bukan JWT user.

    Token dari environment backend (`MAPIC_SERVICE_TOKEN`), bukan JWT Supabase dan
    bukan service-role key Supabase. Kosong/tidak diset berarti endpoint service
    dimatikan sepenuhnya (fail closed, HTTP 503) — bukan akses anonim. JWT pengguna
    tidak pernah diterima di sini karena perbandingan string biasa.
    """
    # Spasi di ujung dibuang: `.env` yang salah edit (spasi/newline ikut tersalin)
    # tidak boleh membuat token mustahil cocok atau route tampak aktif padahal bukan.
    configured = MAPIC_SERVICE_TOKEN.strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Service API is disabled")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    presented = authorization.split(" ", 1)[1].strip()
    # Isi token tidak pernah bocor lewat waktu respons. Panjang token tidak
    # disamarkan: `compare_digest` constant-time hanya untuk panjang yang sama.
    if not secrets.compare_digest(presented.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid service token")


def require_user(authorization: str | None = Header(default=None)) -> UUID:
    """Dependency FastAPI: kembalikan user id dari token, atau HTTP 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        signing_key = JWKS.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=ISSUER,
        )
        return UUID(claims["sub"])
    except Exception as exc:
        # Semua kegagalan verifikasi (kunci tidak ketemu, tanda tangan salah,
        # token kedaluwarsa, claim kurang) diperlakukan sama: 401.
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
