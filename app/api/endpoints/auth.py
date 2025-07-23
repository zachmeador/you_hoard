"""
Authentication endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
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
    Login with username and password
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


@router.post("/logout")
async def logout(
    request: Request,
    security_manager: SecurityManager = Depends(get_security_manager)
):
    """
    Logout and invalidate session
    """
    # Get token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
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
    # Get token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return AuthStatus(authenticated=False)
    
    token = auth_header[7:]
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