"""
Database management for You Hoard using aiosqlite
"""
import json
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
import aiosqlite
from pathlib import Path


class Database:
    """Database connection and query management"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    @asynccontextmanager
    async def get_db(self):
        """Get database connection context manager"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row  # Dict-like row access
            yield db
    
    async def init_db(self):
        """Initialize database with schema"""
        schema_path = Path(__file__).parent.parent.parent / "schema.sql"
        
        async with self.get_db() as db:
            # Check if database already has tables
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='videos'"
            ) as cursor:
                if await cursor.fetchone():
                    return  # Database already initialized
            
            # Load and execute schema
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    await db.executescript(f.read())
                await db.commit()
    
    async def execute(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Execute a query and return all results"""
        async with self.get_db() as db:
            async with db.execute(query, params or ()) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def execute_one(self, query: str, params: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Execute query and return first result"""
        results = await self.execute(query, params)
        return results[0] if results else None
    
    async def execute_many(self, query: str, params_list: List[tuple]) -> None:
        """Execute query multiple times with different parameters"""
        async with self.get_db() as db:
            await db.executemany(query, params_list)
            await db.commit()
    
    async def insert(self, table: str, data: Dict[str, Any]) -> int:
        """Insert data and return last row id"""
        columns = ', '.join(data.keys())
        placeholders = ', '.join('?' * len(data))
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        async with self.get_db() as db:
            cursor = await db.execute(query, tuple(data.values()))
            await db.commit()
            return cursor.lastrowid
    
    async def update(self, table: str, data: Dict[str, Any], where: str, where_params: tuple) -> int:
        """Update data and return affected rows"""
        set_clause = ', '.join(f"{k} = ?" for k in data.keys())
        query = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = tuple(data.values()) + where_params
        
        async with self.get_db() as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.rowcount
    
    async def delete(self, table: str, where: str, params: tuple) -> int:
        """Delete data and return affected rows"""
        query = f"DELETE FROM {table} WHERE {where}"
        
        async with self.get_db() as db:
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor.rowcount
    
    # JSON field helpers
    @staticmethod
    def json_encode(data: Any) -> str:
        """Encode data as JSON for storage"""
        return json.dumps(data) if data is not None else None
    
    @staticmethod
    def json_decode(data: str) -> Any:
        """Decode JSON data from storage"""
        return json.loads(data) if data else None
    
    async def get_videos(self, limit: int = 50, offset: int = 0, 
                        channel_id: Optional[int] = None,
                        status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get videos with optional filtering"""
        query = "SELECT * FROM videos WHERE 1=1"
        params = []
        
        if channel_id:
            query += " AND channel_id = ?"
            params.append(channel_id)
        
        if status:
            query += " AND download_status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        return await self.execute(query, tuple(params))
    
    async def get_channels(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get channels with pagination"""
        query = """
            SELECT c.*, COUNT(v.id) as video_count
            FROM channels c
            LEFT JOIN videos v ON c.id = v.channel_id
            GROUP BY c.id
            ORDER BY c.name
            LIMIT ? OFFSET ?
        """
        return await self.execute(query, (limit, offset)) 