"""Verifikasi token Supabase untuk endpoint API MaPic.

Frontend mengirim `Authorization: Bearer <access_token>`. Backend memverifikasi
tanda tangan token lewat JWKS project (kunci asimetris ES256/RS256 yang dipakai
Supabase), lalu memakai claim `sub` sebagai identitas user. `user_id` yang
dikirim klien di body/URL tidak pernah dipercaya.
"""

from uuid import UUID

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

try:
    from backend.config import SUPABASE_URL
except ModuleNotFoundError:
    from config import SUPABASE_URL

ISSUER = f"{SUPABASE_URL.rstrip('/')}/auth/v1"

# Klien JWKS menyimpan kunci yang sudah diambil; `lifespan` membatasinya 1 jam
# supaya rotasi kunci Supabase ikut terbaca tanpa menambah latensi per request.
JWKS = PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


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
