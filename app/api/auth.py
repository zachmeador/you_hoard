"""First-run setup, login and logout."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.auth import (
    COOKIE,
    create_session,
    delete_session,
    hash_password,
    request_token,
    require_same_origin,
    session_user,
    verify_password,
)
from app.config import config
from app.db import Database

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class NewAccount(Credentials):
    username: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    password: str = Field(min_length=8, max_length=1024)


def set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("X-Forwarded-Proto", request.url.scheme) == "https",
    )


@router.get("/status")
async def status(request: Request, db: Database = Depends(get_db)):
    token = request_token(request)
    user = await session_user(db, token) if token else None
    if user:
        return {"authenticated": True, "username": user["username"], "setup_required": False}
    users = await db.fetch_value("SELECT count(*) FROM users")
    return {"authenticated": False, "username": None, "setup_required": users == 0}


@router.post("/setup")
async def setup(
    account: NewAccount, request: Request, response: Response, db: Database = Depends(get_db)
):
    require_same_origin(request)
    password_hash = await asyncio.to_thread(hash_password, account.password)
    async with db.transaction() as conn:
        cursor = await conn.execute("SELECT count(*) FROM users")
        if (await cursor.fetchone())[0]:
            raise HTTPException(status_code=409, detail="Setup is already complete")
        cursor = await conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (account.username, password_hash),
        )
        user_id = cursor.lastrowid
    set_cookie(response, request, await create_session(db, user_id))
    return {"username": account.username}


@router.post("/login")
async def login(
    credentials: Credentials, request: Request, response: Response, db: Database = Depends(get_db)
):
    require_same_origin(request)
    user = await db.fetch_one(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (credentials.username.strip(),),
    )
    valid = user is not None and await asyncio.to_thread(
        verify_password, credentials.password, user["password_hash"]
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    token = await create_session(db, user["id"])
    set_cookie(response, request, token)
    return {"username": user["username"], "token": token}


@router.post("/logout")
async def logout(request: Request, response: Response, db: Database = Depends(get_db)):
    require_same_origin(request)
    if token := request_token(request):
        await delete_session(db, token)
    response.delete_cookie(COOKIE)
    return {"ok": True}
