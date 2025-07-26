## Current Subscription System Flow

Here's how the subscription functionality works now, end-to-end:

### 1. **Subscription Creation**
- User provides YouTube channel/playlist URL
- System extracts channel metadata using `yt-dlp`
- Creates/finds channel record in database
- Creates subscription with user preferences:
  - Quality preference (now defaults to 720p as you just changed)
  - Auto-download enabled/disabled
  - Check frequency (cron expression, default hourly)
  - Additional settings (comments, subtitles, etc.)
- If enabled, adds to APScheduler for automatic checking

### 2. **Automatic Monitoring** 
- APScheduler runs subscription checks based on each subscription's cron schedule
- For each check:
  - Fetches latest ~20 videos from the channel/playlist via `yt-dlp` 
  - Compares against existing videos in database (by YouTube ID)
  - **New videos found** → adds to `videos` table with metadata
  - **If `auto_download=true`** → automatically queues for download with:
    - Priority = 1 (higher than manual additions)
    - Quality = subscription's preference (720p default)
  - Updates subscription record with `last_check` time and `new_videos_count`

### 3. **User Interface Integration**
- Lists subscriptions with real next check times (using APScheduler's cron parsing)
- Shows count of new videos found in last check
- Manual check button for immediate checking
- Pause/resume controls
- Individual subscription settings

### 4. **Download Integration**
- New subscription videos automatically flow into the download queue
- Uses existing download system (progress tracking, file organization, etc.)
- User doesn't need to manually queue subscription content

## Key Benefits of Current Design

1. **Fully Automated**: Set and forget - users get new content automatically
2. **Flexible Scheduling**: Each subscription can have its own check frequency
3. **Quality Control**: Per-subscription quality preferences 
4. **Optional Auto-download**: Can monitor without downloading if desired
5. **Real-time Status**: Shows actual next check times and recent activity

The system now bridges the gap between "I want to follow this channel" and "I have the videos on my drive" with zero manual intervention required.

What aspects would you like to dive deeper into or improve?