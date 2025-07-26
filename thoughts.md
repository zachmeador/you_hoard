## what's this doc

the user's ramblings on the project. if you're reading this, make sure the project is aligning with the user. the user is often dumb and not paying attention, and would like assistance in this matter.

## what

here's what i'm thinking: a tube archivist like project that doesn't suck

backend: fastapi, sqlite, that youtube dler library, and whatever's needed to let users scrape their own youtube accounts (and making the auth not be a pain in the ass)

it's meant to be ran by a single user as a lan web app. it has very simple username and pass auth.

## philsophy

keep it simple. tubearchivist is using elasticsearch and redis? bro

## things the user configs:

platform source: for now just youtube, but could make extensible for other sites for later on

user can schedule youhoard to watch channels and/or playlists for new content

user can specify the encoding settings and such, passed down to the dler library

user can specify in subscription settings to store comments

user can specify in subscription settings to get certain subtitles or audio tracks

all of these things can also be configured for individual videos (except obviously not watch, doesn't apply)

user can add tags to subscriptions, videos, or channels

## backend

simple source file management, with all videos being contained within a channel directory. channel directory begins with the channel id (guessing there's a youtube id number? if not, then this app makes one), then channel dirs contain video files also named with their id (internal app id) followed by a cleaned cut string of their title. this should make it fairly easy to also add as a plex/jellyfin source

lean on downloading libraries for as much as possible in the video fetching

a sqlite db will be for all metadata and app data persistence. 

videos are naturally de-duped, by their source id (likely youtube id). you can't add 

## api spec

basic crud stuff

## frontend

dirt simple but information dense, with all configs being done through the frontend.

need to scaffold out the page structure:
- home page: nav bar, search bar, shows latest fetches, log for watch schedules, log for latest video fetches
- 