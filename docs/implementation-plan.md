# You Hoard Implementation Plan

## Overview

This document outlines the implementation plan for You Hoard, a self-hosted YouTube archiving application. The plan is organized into phases, starting with core infrastructure and progressively adding features.

## 📈 **Current Status: Backend Scaffolding Complete**

**✅ Completed:** Full backend API with authentication, video/channel/subscription management, download queue, and database schema.

**⚠️ Pending:** APScheduler integration for automatic subscription checking.

**🔄 Next:** Frontend development (Phase 5).

## Implementation Phases

- **Phase 1**: Core Foundation ✅ **COMPLETED**
- **Phase 2**: Basic Downloading ✅ **COMPLETED**
- **Phase 3**: Channel Management ✅ **COMPLETED**
- **Phase 4**: Subscription System ⚠️ **IN PROGRESS** (scheduler pending)
- **Phase 5**: Frontend Development 🔄 **NEXT**
- **Phase 6**: Advanced Features
- **Phase 7**: Polish & Testing

## Phase 1: Core Foundation ✅ **COMPLETED**

### Goals
Establish the basic project structure, database, and API framework.

### Tasks ✅ **ALL COMPLETED**

1. **Project Setup** ✅
   - ✅ Initialize Python UV project with `pyproject.toml`
   - ✅ Set up project directory structure
   - ✅ Create `.gitignore` and `README.md`
   - ✅ Configure development environment

2. **Database Layer** ✅
   - ✅ Implement SQLite database connection using aiosqlite for async operations
   - ✅ Create database schema based on DESIGN.md using raw SQL
   - ✅ Write database migration scripts
   - ✅ Create database initialization script with proper indexes

3. **Core Application Structure** ✅
   - ✅ Set up FastAPI application structure
   - ✅ Implement basic configuration management (`core/config.py`)
   - ✅ Create database session management (`core/database.py`)
   - ✅ Set up logging infrastructure

4. **Basic Authentication** ✅
   - ✅ Implement simple password storage with bcrypt hashing
   - ✅ Create server-side session management (using secure cookies)
   - ✅ Build login/logout endpoints
   - ✅ Add authentication middleware for protected routes

### Dependencies ✅ **CONFIGURED**
- Python 3.11+
- FastAPI
- aiosqlite (async SQLite driver)
- Pydantic
- passlib (for password hashing)

## Phase 2: Basic Downloading ✅ **COMPLETED**

### Goals
Implement core video downloading functionality using yt-dlp.

### Tasks ✅ **ALL COMPLETED**

1. **Downloader Core** ✅
   - ✅ Create yt-dlp wrapper class (`core/downloader.py`)
   - ✅ Implement progress tracking callbacks
   - ✅ Handle download errors and retries
   - ✅ Create file organization logic per DESIGN.md structure

2. **Video Management API** ✅
   - ✅ Implement `/api/videos` endpoints (CRUD operations)
   - ✅ Add video by URL endpoint
   - ✅ Video metadata extraction and storage
   - ✅ File path management

3. **Download Queue** ✅
   - ✅ Create queue management system
   - ✅ Implement download worker (async/background)
   - ✅ Progress tracking and status updates
   - ✅ Error handling and retry logic

## Phase 3: Channel Management ✅ **COMPLETED**

### Goals
Add channel discovery and management capabilities.

### Tasks ✅ **ALL COMPLETED**

1. **Channel Discovery** ✅
   - ✅ Extract channel info when adding videos
   - ✅ Create or update channel records automatically
   - ✅ Download channel metadata and thumbnails

2. **Channel API** ✅
   - ✅ Implement `/api/channels` endpoints
   - ✅ Channel listing with pagination
   - ✅ Channel detail view with associated videos
   - ✅ Channel metadata update endpoint

3. **Channel Organization** ✅
   - ✅ Ensure proper file structure for channels
   - ✅ Store channel metadata JSON files
   - ✅ Handle channel name changes gracefully

## Phase 4: Subscription System ⚠️ **IN PROGRESS**

### Goals
Implement automated content checking and downloading for subscribed channels.

### Tasks ⚠️ **MOSTLY COMPLETED**

1. **Subscription Management** ✅
   - ✅ Create subscription CRUD endpoints
   - ✅ Channel and playlist subscription support
   - ✅ Per-subscription quality and download preferences
   - ✅ Enable/disable functionality

2. **Scheduled Checking** ⚠️ **PENDING**
   - ❌ Implement cron-based scheduler (using APScheduler)
   - ✅ Check for new videos per subscription schedule (manual endpoint)
   - ✅ Queue new videos automatically
   - ✅ Track last check timestamps

3. **Subscription Settings** ✅
   - ✅ Quality preferences per subscription
   - ✅ Subtitle and audio track preferences
   - ✅ Comment downloading options
   - ✅ Custom check frequencies

### **TODO: Add APScheduler integration for automatic checking**

## Phase 5: Frontend Development

### Goals
Create a clean, functional web interface for all features.

### Tasks

1. **Base Layout**
   - Create responsive navigation structure
   - Implement authentication flow (login page)
   - Set up static file serving
   - Create base template structure

2. **Core Pages**
   - **Home Dashboard**: Stats, recent downloads, quick actions
   - **Videos Page**: Grid view, search, filters, bulk operations
   - **Channels Page**: Channel cards, subscription management
   - **Downloads Page**: Queue view, progress bars, controls

3. **Interactive Features**
   - Real-time download progress (WebSocket or SSE)
   - Drag-and-drop for adding videos
   - Inline video player
   - Tag management UI

### Frontend Stack
- Vanilla JavaScript (no framework initially)
- Modern CSS with Grid/Flexbox
- Minimal dependencies
- Progressive enhancement approach

## Phase 6: Advanced Features

### Goals
Add quality-of-life features and optimizations.

### Tasks

1. **Tagging System**
   - Implement tag CRUD endpoints
   - Video and channel tagging
   - Tag-based filtering in UI
   - Bulk tagging operations

2. **Search & Filtering**
   - Full-text search implementation
   - Advanced filters (date, duration, quality)
   - Saved search queries
   - Sort options

3. **Settings Management**
   - Settings page UI
   - Storage path configuration
   - Default preferences
   - Cleanup policies

4. **Additional Features**
   - Export functionality (to CSV/JSON)
   - Bulk operations (delete, re-download)
   - Storage usage analytics
   - Download history and logs viewer

## Phase 7: Polish & Testing

### Goals
Ensure reliability, performance, and user experience.

### Tasks

1. **Testing**
   - Write integration tests for API endpoints
   - Test download error scenarios
   - Verify file organization
   - Load testing for concurrent operations

2. **Error Handling**
   - Comprehensive error messages
   - User-friendly error display
   - Retry mechanisms
   - Graceful degradation

3. **Performance Optimization**
   - Database query optimization
   - Pagination implementation
   - Caching where appropriate
   - Minimize API calls

4. **Documentation**
   - API documentation (OpenAPI/Swagger)
   - User guide
   - Deployment instructions
   - Configuration guide

## Implementation Tips

### Start Simple
1. Begin with single video downloads
2. Add complexity incrementally
3. Test each phase thoroughly before moving on

### Key Libraries
- **yt-dlp**: Core downloading functionality
- **FastAPI**: Web framework
- **aiosqlite**: Async SQLite driver (no ORM overhead)
- **APScheduler**: Cron scheduling
- **Pydantic**: Data validation

### Development Workflow
1. Implement backend endpoints first
2. Test with curl/Postman
3. Build minimal UI to test functionality
4. Iterate on UI/UX

### Common Pitfalls to Avoid
- Over-engineering early (keep it simple)
- Ignoring error cases
- Not sanitizing file paths
- Forgetting about concurrent access
- Rate limiting issues with YouTube

## MVP Definition

The Minimum Viable Product should include:
- User authentication
- Add videos by URL
- Download videos with progress tracking
- View downloaded videos
- Basic channel organization
- Simple web UI

Everything else can be added iteratively based on user needs.

## Future Considerations

- Plugin system for other platforms
- Docker containerization
- Multi-user support
- Mobile app API
- Advanced transcoding options
- Webhook integrations

## Getting Started

1. Set up development environment with Python 3.11+
2. Install UV package manager
3. Create project structure per DESIGN.md
4. Start with Phase 1, Task 1
5. Commit frequently and test continuously

Remember: The goal is a simple, reliable YouTube archiver. Don't over-complicate! 