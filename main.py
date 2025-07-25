"""
You Hoard - Main FastAPI Application
"""
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.core.config import settings
from app.core.database import Database
from app.api.endpoints import auth, videos, channels, subscriptions, downloads

# Create database tables
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db = Database(settings.DATABASE_PATH)
    await db.init_db()
    app.state.db = db
    yield
    # Shutdown
    pass

app = FastAPI(
    title="You Hoard",
    description="Personal YouTube archive application",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(channels.router, prefix="/api/channels", tags=["channels"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])

# Mount static files
static_path = "app/static"
if os.path.exists(static_path):
    app.mount("/app/static", StaticFiles(directory=static_path), name="static")

# Mount Svelte build files
dist_path = "app/static/dist"
if os.path.exists(dist_path):
    app.mount("/assets", StaticFiles(directory=f"{dist_path}/assets"), name="assets")

# Health check endpoint (must be before catch-all route)
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "You Hoard is running"}

# Serve the Svelte app for all non-API routes
@app.get("/{full_path:path}")
async def serve_svelte_app(request: Request, full_path: str):
    # If it's an API route, let FastAPI handle it normally
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # For all other routes, serve the Svelte app
    index_path = "app/static/dist/index.html"
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        # Fallback to development mode - serve from root
        fallback_path = "index.html"
        if os.path.exists(fallback_path):
            return FileResponse(fallback_path)
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 