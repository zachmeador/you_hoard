"""
You Hoard - Main FastAPI Application
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Database
from app.core.scheduler import SubscriptionScheduler
from app.core.security import SessionBearer, SecurityManager
from app.api.endpoints import videos, channels, subscriptions, downloads, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    db = Database(settings.DATABASE_PATH)
    await db.init_db()
    app.state.db = db
    
    # Start subscription scheduler
    scheduler = SubscriptionScheduler(db)
    await scheduler.start()
    app.state.scheduler = scheduler
    
    yield
    
    # Shutdown
    if hasattr(app.state, 'scheduler'):
        await app.state.scheduler.stop()


# Create FastAPI application
app = FastAPI(
    title="You Hoard",
    description="Self-hosted YouTube archiving application",
    version="0.1.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include API routers
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(channels.router, prefix="/api/channels", tags=["channels"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])


# Authentication dependency for frontend routes
async def get_current_user(request: Request):
    """Check if user is authenticated for frontend routes"""
    # Get session token from cookie
    session_token = request.cookies.get("session_token")
    
    if not session_token:
        # Redirect to login if no session cookie
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    
    # Use the same security manager instance as the API endpoints
    if not hasattr(request.app.state, 'security_manager'):
        request.app.state.security_manager = SecurityManager(request.app.state.db)
    
    security_manager = request.app.state.security_manager
    session = security_manager.get_session(session_token)
    
    if not session:
        # Redirect to login if invalid session
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    
    return session


# Frontend Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user = Depends(get_current_user)):
    """Home dashboard page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/logout")
async def logout(request: Request):
    """Logout and redirect to login"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")  # Match the cookie name from auth endpoints
    return response


@app.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, user = Depends(get_current_user)):
    """Videos page"""
    return templates.TemplateResponse("videos.html", {"request": request})


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request, user = Depends(get_current_user)):
    """Channels page"""
    return templates.TemplateResponse("channels.html", {"request": request})


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, user = Depends(get_current_user)):
    """Subscriptions page"""
    return templates.TemplateResponse("subscriptions.html", {"request": request})


@app.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request, user = Depends(get_current_user)):
    """Downloads page"""
    return templates.TemplateResponse("downloads.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user = Depends(get_current_user)):
    """Settings page"""
    return templates.TemplateResponse("settings.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 