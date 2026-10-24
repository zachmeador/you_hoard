"""One local account: scrypt password hashes and server-side sessions."""

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request

from app.config import config
from app.db import Database, iso, now, utcnow

COOKIE = "youhoard_session"
SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    encode = base64.b64encode
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p)
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: Database, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = iso(utcnow() + timedelta(days=config.SESSION_DAYS))
    await db.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, now(), expires),
    )
    await db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
    return token


async def delete_session(db: Database, token: str) -> None:
    await db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


async def session_user(db: Database, token: str) -> dict | None:
    return await db.fetch_one(
        """SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ?""",
        (_token_hash(token), now()),
    )


def request_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header:
        scheme, _, token = header.partition(" ")
        return token if scheme.lower() == "bearer" and token else None
    return request.cookies.get(COOKIE)


def require_same_origin(request: Request) -> None:
    """Reject cross-site requests that ride on the session cookie."""
    origin = request.headers.get("Origin")
    if origin is None:
        if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")
        return
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
    if origin.split("://", 1)[-1].rstrip("/") != host:
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


async def current_user(request: Request) -> dict:
    token = request_token(request)
    user = await session_user(request.app.state.db, token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Please log in")
    if "Authorization" not in request.headers and request.method not in ("GET", "HEAD"):
        require_same_origin(request)
    return user
