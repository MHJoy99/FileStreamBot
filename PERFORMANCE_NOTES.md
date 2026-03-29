# FileStreamBot Performance Notes

## What has already been improved

- `tgcrypto` is installed in the bot venv.
- Direct `/dl/<id>` links are working with ranged responses.
- Video and audio are sent with `inline` disposition.
- Range parsing is more robust.
- The watch/download page no longer self-fetches the file size through another internal HTTP request.
- Multi-client initialization no longer crashes if one extra token fails.
- Streaming now uses `aiohttp.StreamResponse` instead of a generic body response.
- File-property caching now uses per-file locks to avoid duplicate work under concurrent hits.

## Current limits that still exist

- This bot is still relaying live from Telegram.
- Without storing files locally, it will never behave exactly like Google Drive or a CDN.
- Telegram `upload.GetFile` has a hard per-request size limit, so chunk-size tuning has a ceiling.
- External speed still depends on Telegram, the VPS network path, and the client/player behavior.

## Important reality check

What we can optimize:

- lower overhead
- better player compatibility
- faster Telegram crypto path
- cleaner ranged delivery

What we cannot promise without local caching:

- true “Google Drive type” serving speed
- fully stable max throughput on every request

## Best remaining upgrade paths without disk caching

### 1. Add more Telegram serving clients

Use extra `MULTI_TOKEN*` values or session strings so the system has more Telegram clients available.

This helps most when:

- multiple people stream at once
- multiple files are being served concurrently

### 2. Add a user session string

A user session can sometimes perform better than bot-only serving for Telegram media access.

This would require adding a valid session string in env.

### 3. Tighten service restarts

The bot sometimes takes too long to stop cleanly during restart.

If more tuning is done later, improve the systemd service with:

- shorter `TimeoutStopSec`
- explicit kill behavior

This is an ops improvement, not a media-speed improvement.

## Current stream-path code references

- `FileStream/server/stream_routes.py`
- `FileStream/utils/custom_dl.py`
- `FileStream/config.py`

## Summary

This repo is now in a better state for live Telegram relay, but the next major speed jump requires one of these:

- more Telegram clients/sessions
- local caching to disk
- a future move back to a clean `80/443 HTTPS` setup if desired
