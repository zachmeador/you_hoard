#!/bin/sh
set -e

# YouTube changes often; this lets a container pick up a newer yt-dlp without a new image.
if [ "${YTDLP_UPDATE_ON_START:-0}" = "1" ]; then
    uv pip install --quiet --python /opt/venv/bin/python --upgrade "yt-dlp[default,deno]" \
        || echo "yt-dlp update failed; continuing with the installed version" >&2
fi

exec "$@"
