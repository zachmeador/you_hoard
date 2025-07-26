#!/usr/bin/env python3
"""Setup script for You Hoard development environment"""

import subprocess
import httpx
import asyncio
from pathlib import Path

async def setup():
    """Set up fresh development environment"""
    
    # Check if database already exists (contains user auth data)
    db_path = Path("you_hoard.db")
    has_existing_db = db_path.exists()
    
    if has_existing_db:
        print("📊 Existing database detected (you_hoard.db)")
        print("🔄 App will automatically perform recovery on startup")
    
    # Install dependencies
    print("📦 Installing dependencies...")
    subprocess.run(["uv", "sync"], check=True)
    
    # Create storage directories
    storage_path = Path("storage")
    storage_path.mkdir(exist_ok=True)
    (storage_path / "temp").mkdir(exist_ok=True)
    (storage_path / "channels").mkdir(exist_ok=True)
    print("📁 Created storage directories")
    
    # Start app in background
    print("🚀 Starting app...")
    app_process = subprocess.Popen([
        "uv", "run", "uvicorn", "main:app", 
        "--host", "0.0.0.0", "--port", "8000"
    ])
    
    # Wait for app to start
    print("⏳ Waiting for app to start...")
    for _ in range(10):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/api/health")
                if response.status_code == 200:
                    break
        except:
            pass
        await asyncio.sleep(1)
    
    # Create admin user (only if no existing database)
    if not has_existing_db:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/auth/setup",
                    json={"username": "admin", "password": "admin"}
                )
                if response.status_code == 200:
                    print("👤 Created admin user (admin/admin)")
                else:
                    print(f"⚠️  Setup endpoint returned: {response.status_code}")
        except Exception as e:
            print(f"❌ Failed to create admin user: {e}")
    else:
        print("👤 Skipping admin user creation (existing database found)")
    
    app_process.terminate()
    app_process.wait()
    
    print("✅ Setup complete! Run 'npm run dev' to start development")

if __name__ == "__main__":
    asyncio.run(setup()) 