"""Password hashing and persistent cookie/bearer sessions."""

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from passlib.context import CryptContext

from app.core.config import settings
from app.core.database import Database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityManager:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return pwd_context.verify(password, password_hash)
        except ValueError:
            return False

    async def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
        await self.db.insert(
            "sessions",
            {
                "token": token,
                "user_id": user_id,
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        )
        return token

    async def get_session(self, token: str) -> dict[str, Any] | None:
        session = await self.db.execute_one("SELECT * FROM sessions WHERE token = ?", (token,))
        if not session:
            return None
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            await self.delete_session(token)
            return None
        return {
            "user_id": session["user_id"],
            "created_at": datetime.fromisoformat(session["created_at"]),
            "expires_at": expires_at,
        }

    async def delete_session(self, token: str) -> None:
        await self.db.delete("sessions", "token = ?", (token,))

    async def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = await self.db.execute_one("SELECT * FROM users WHERE username = ?", (username,))
        if user and await asyncio.to_thread(self.verify_password, password, user["password_hash"]):
            return user
        return None


def session_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header is None:
        return request.cookies.get("session_token")
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")


async def get_auth(request: Request) -> dict[str, Any]:
    token = session_token(request)
    session = await SecurityManager(request.app.state.db).get_session(token) if token else None
    if not session:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    if not request.headers.get("Authorization") and request.method not in (
        "GET",
        "HEAD",
        "OPTIONS",
    ):
        require_same_origin(request)
    return session
