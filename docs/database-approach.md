# Database Approach - Direct SQLite Access

### Using aiosqlite
```python
import aiosqlite
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db():
    async with aiosqlite.connect("you_hoard.db") as db:
        db.row_factory = aiosqlite.Row  # Dict-like row access
        yield db
```

### Query Patterns
```python
# Simple parameterized queries
async def get_video(video_id: int):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM videos WHERE id = ?", (video_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

# Bulk inserts with transactions
async def insert_videos(videos: list[dict]):
    async with get_db() as db:
        await db.executemany(
            """INSERT INTO videos (youtube_id, title, channel_id) 
               VALUES (?, ?, ?)""",
            [(v['youtube_id'], v['title'], v['channel_id']) for v in videos]
        )
        await db.commit()
```

### Database Helpers

We'll create a thin database layer in `core/database.py` with:

1. **Connection management**: Connection pooling and lifecycle
2. **Query builders**: Simple helpers for common patterns
3. **Type conversions**: JSON serialization/deserialization
4. **Migration system**: Version-controlled schema changes

### Example Database Module

```python
# core/database.py
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
    async def init_db(self):
        """Initialize database with schema"""
        async with aiosqlite.connect(self.db_path) as db:
            with open('schema.sql', 'r') as f:
                await db.executescript(f.read())
            await db.commit()
    
    async def execute(self, query: str, params=None):
        """Execute a single query"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params or ()) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def execute_one(self, query: str, params=None):
        """Execute query and return first result"""
        results = await self.execute(query, params)
        return results[0] if results else None
```
