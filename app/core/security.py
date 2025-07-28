"""
Security utilities for YouHoard
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
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password for storing"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a stored password against provided password"""
        return pwd_context.verify(plain_password, hashed_password)
    
    async def create_session(self, user_id: int) -> str:
        """Create a new session for a user"""
        session_token = secrets.token_urlsafe(32)
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
        await self.db.insert("sessions", {
            "token": session_token,
            "user_id": user_id,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat()
        })
        return session_token
    
    async def get_session(self, session_token: str) -> Optional[dict]:
        """Get session data if valid"""
        session = await self.db.execute_one(
            "SELECT * FROM sessions WHERE token = ?",
            (session_token,)
        )
        if not session:
            return None
        
        expires_at = datetime.fromisoformat(session["expires_at"])
        if datetime.utcnow() > expires_at:
            # Session expired
            await self.db.delete("sessions", "token = ?", (session_token,))
            return None
        
        return {
            "user_id": session["user_id"],
            "created_at": datetime.fromisoformat(session["created_at"]),
            "expires_at": expires_at
        }
    
    async def delete_session(self, session_token: str) -> None:
        """Delete a session"""
        await self.db.delete("sessions", "token = ?", (session_token,))
    
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
        
        session = await self.security_manager.get_session(credentials.credentials)
        
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