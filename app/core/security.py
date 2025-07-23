"""
Security utilities for You Hoard
"""
from datetime import datetime, timedelta
from typing import Optional
import secrets
from passlib.context import CryptContext
from fastapi import HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityManager:
    """Handles authentication and security operations"""
    
    def __init__(self, db):
        self.db = db
        self.sessions = {}  # In-memory session storage (consider Redis for production)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password for storing"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a stored password against provided password"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def create_session(self, user_id: int) -> str:
        """Create a new session for a user"""
        session_token = secrets.token_urlsafe(32)
        self.sessions[session_token] = {
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
        }
        return session_token
    
    def get_session(self, session_token: str) -> Optional[dict]:
        """Get session data if valid"""
        session = self.sessions.get(session_token)
        if not session:
            return None
        
        if datetime.utcnow() > session["expires_at"]:
            # Session expired
            del self.sessions[session_token]
            return None
        
        return session
    
    def delete_session(self, session_token: str) -> None:
        """Delete a session"""
        self.sessions.pop(session_token, None)
    
    async def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate a user with username and password"""
        user = await self.db.execute_one(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        )
        
        if not user:
            return None
        
        if not self.verify_password(password, user["password_hash"]):
            return None
        
        return user
    
    async def create_user(self, username: str, password: str) -> int:
        """Create a new user"""
        # Check if user already exists
        existing = await self.db.execute_one(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        )
        
        if existing:
            raise ValueError("User already exists")
        
        # Create new user
        user_id = await self.db.insert("users", {
            "username": username,
            "password_hash": self.hash_password(password)
        })
        
        return user_id


class SessionBearer(HTTPBearer):
    """Custom authentication scheme using Bearer tokens for sessions"""
    
    def __init__(self, security_manager: SecurityManager, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self.security_manager = security_manager
    
    async def __call__(self, request: Request) -> Optional[dict]:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        
        if not credentials:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid authentication credentials"
                )
            return None
        
        session = self.security_manager.get_session(credentials.credentials)
        
        if not session:
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or expired session"
                )
            return None
        
        return session


def get_current_user(request: Request) -> dict:
    """Get current user from request state"""
    if not hasattr(request.state, "user"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return request.state.user 