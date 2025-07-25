"""
Authentication endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

from app.core.database import Database
from app.core.security import SecurityManager


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class AuthStatus(BaseModel):
    authenticated: bool
    username: Optional[str] = None


def get_db(request: Request) -> Database:
    """Get database from app state"""
    return request.app.state.db


def get_security_manager(request: Request) -> SecurityManager:
    """Get security manager from app state"""
    if not hasattr(request.app.state, 'security_manager'):
        request.app.state.security_manager = SecurityManager(request.app.state.db)
    return request.app.state.security_manager


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Login with username and password (API version)
    """
    user = await security_manager.authenticate_user(
        login_data.username,
        login_data.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # Create session
    token = security_manager.create_session(user['id'])
    
    return LoginResponse(
        token=token,
        username=user['username']
    )


@router.post("/login-form")
async def login_form(
    username: str = Form(...),
    password: str = Form(...),
    request: Request = None,
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Login with form data and set session cookie
    """
    user = await security_manager.authenticate_user(username, password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # Create session
    token = security_manager.create_session(user['id'])
    
    # Create response that redirects to home
    response = RedirectResponse(url="/", status_code=302)
    
    # Set session cookie
    response.set_cookie(
        key="session_token",
        value=token,
        max_age=86400 * 30,  # 30 days
        httponly=True,
        secure=False
    )
    
    return response


@router.post("/logout")
async def logout(
    request: Request,
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Logout and invalidate session
    """
    # Try Authorization header first (for API clients)
    auth_header = request.headers.get("Authorization", "")
    token = None
    
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Try session cookie (for web frontend)
        token = request.cookies.get("session_token")
    
    if token:
        security_manager.delete_session(token)
    
    return {"message": "Logged out successfully"}


@router.get("/status", response_model=AuthStatus)
async def auth_status(
    request: Request,
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Check authentication status
    """
    # Try Authorization header first (for API clients)
    auth_header = request.headers.get("Authorization", "")
    token = None
    
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Try session cookie (for web frontend)
        token = request.cookies.get("session_token")
    
    if not token:
        return AuthStatus(authenticated=False)
    
    session = security_manager.get_session(token)
    
    if not session:
        return AuthStatus(authenticated=False)
    
    # Get user info
    db = get_db(request)
    user = await db.execute_one(
        "SELECT username FROM users WHERE id = ?",
        (session['user_id'],)
    )
    
    return AuthStatus(
        authenticated=True,
        username=user['username'] if user else None
    )


@router.post("/setup")
async def initial_setup(
    login_data: LoginRequest,
    request: Request,
    db: Database = Depends(get_db),
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Initial setup - create first user (only works if no users exist)
    """
    # Check if any users exist
    existing = await db.execute_one("SELECT COUNT(*) as count FROM users")
    
    if existing and existing['count'] > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup already completed"
        )
    
    try:
        # Create first user
        user_id = await security_manager.create_user(
            login_data.username,
            login_data.password
        )
        
        return {"message": "Setup completed", "user_id": user_id}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) 