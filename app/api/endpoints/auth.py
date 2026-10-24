"""Initial account setup and session management."""

import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.database import Database
from app.core.security import SecurityManager, require_same_origin, session_token

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class SetupRequest(LoginRequest):
    username: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class AuthStatus(BaseModel):
    authenticated: bool
    username: str | None = None
    setup_required: bool = False


def get_security_manager(db: Database = Depends(get_db)) -> SecurityManager:
    return SecurityManager(db)


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        "session_token",
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=settings.SESSION_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    security_manager: SecurityManager = Depends(get_security_manager),
) -> LoginResponse:
    require_same_origin(request)
    user = await security_manager.authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = await security_manager.create_session(user["id"])
    set_session_cookie(response, token, request)
    return LoginResponse(token=token, username=user["username"])


@router.post("/login-form", response_model=LoginResponse)
async def login_form(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    security_manager: SecurityManager = Depends(get_security_manager),
) -> LoginResponse:
    return await login(
        LoginRequest(username=username, password=password), request, response, security_manager
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    security_manager: SecurityManager = Depends(get_security_manager),
) -> dict[str, str]:
    require_same_origin(request)
    token = session_token(request)
    if token:
        await security_manager.delete_session(token)
    response.delete_cookie("session_token")
    return {"message": "Logged out successfully"}


@router.get("/status", response_model=AuthStatus)
async def auth_status(
    request: Request,
    db: Database = Depends(get_db),
    security_manager: SecurityManager = Depends(get_security_manager),
) -> AuthStatus:
    token = session_token(request)
    session = await security_manager.get_session(token) if token else None
    if not session:
        users = await db.execute_one("SELECT COUNT(*) AS count FROM users")
        return AuthStatus(authenticated=False, setup_required=users["count"] == 0)
    user = await db.execute_one("SELECT username FROM users WHERE id = ?", (session["user_id"],))
    return AuthStatus(authenticated=user is not None, username=user["username"] if user else None)


@router.post("/setup")
async def initial_setup(
    login_data: SetupRequest,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    security_manager: SecurityManager = Depends(get_security_manager),
) -> dict[str, str | int]:
    require_same_origin(request)
    users = await db.execute_one("SELECT COUNT(*) AS count FROM users")
    if users["count"]:
        raise HTTPException(status_code=409, detail="Setup already completed")
    password_hash = await asyncio.to_thread(security_manager.hash_password, login_data.password)
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute("SELECT COUNT(*) AS count FROM users")
        if (await cursor.fetchone())["count"]:
            raise HTTPException(status_code=409, detail="Setup already completed")
        cursor = await conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (login_data.username, password_hash),
        )
        user_id = cursor.lastrowid
        await conn.commit()
    token = await security_manager.create_session(user_id)
    set_session_cookie(response, token, request)
    return {"message": "Setup completed", "user_id": user_id}
