# Authentication Approach

## Session-Based Authentication

We'll use FastAPI's built-in session support with secure cookies:

```python
# core/auth.py
from fastapi import Cookie, HTTPException, Depends
from typing import Optional
import secrets
import bcrypt

# In-memory sessions (or stored in SQLite)
sessions = {}

class Auth:
    def __init__(self, password_hash: str):
        self.password_hash = password_hash
    
    def verify_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode('utf-8'), 
            self.password_hash.encode('utf-8')
        )
    
    def create_session(self) -> str:
        session_id = secrets.token_urlsafe(32)
        sessions[session_id] = {"authenticated": True}
        return session_id
    
    def verify_session(self, session_id: str) -> bool:
        return session_id in sessions

# Dependency for protected routes
async def require_auth(session_id: Optional[str] = Cookie(None)):
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401)
    return session_id
```

### Initial Setup

On first run, the app will:
1. Check if a password is configured
2. If not, prompt to set one via CLI or web interface
3. Store the bcrypt hash in the database or config file

```python
# First-run setup
async def initial_setup():
    if not await has_password_configured():
        print("Welcome to You Hoard!")
        password = getpass("Set your password: ")
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        await save_password_hash(password_hash)
```

### Login Flow

1. User visits `/login`
2. Enters password
3. Server verifies password against stored hash
4. Creates session and sets secure cookie
5. Redirects to home page

```python
@app.post("/api/auth/login")
async def login(password: str, response: Response):
    if not auth.verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    session_id = auth.create_session()
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,  # JavaScript can't access
        secure=True,    # HTTPS only (disable for local dev)
        samesite="lax"  # CSRF protection
    )
    return {"status": "logged in"}
```

### Protected Routes

```python
@app.get("/api/videos", dependencies=[Depends(require_auth)])
async def get_videos():
    # This route requires authentication
    return await fetch_videos()
```

## Security Considerations

Even though it's self-hosted:

1. **Always hash passwords**: Never store plaintext
2. **Use secure cookies**: httponly, secure flags
3. **Session expiration**: Clear old sessions periodically
4. **HTTPS recommended**: Even on LAN for session security

## Alternative: No Authentication

For truly private LAN use, you could even skip authentication:

```python
# config.py
REQUIRE_AUTH = False  # Set via environment variable

# In middleware
if not REQUIRE_AUTH:
    return  # Skip all auth checks
```

This aligns with the "keep it simple" philosophy while maintaining the option for basic security when needed. 