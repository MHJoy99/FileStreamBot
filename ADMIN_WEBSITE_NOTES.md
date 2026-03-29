# Admin Website Notes

## What It Does

- Private owner login at `/admin/login`
- Dashboard at `/admin`
- Select files across pages with browser-persistent selection
- Create one public `.m3u` playlist link from selected files
- Export all saved files as `.m3u`
- Export all direct links as `.txt`

## PotPlayer Flow

1. Log in to the dashboard.
2. Select the files you want in the playlist.
3. Click `Create Playlist Link`.
4. Copy the generated `/playlist/<token>.m3u` URL.
5. Paste that single URL into PotPlayer or VLC.

## Login Config

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `WEB_SESSION_SECRET`
- `WEB_SESSION_TTL`

## Important Note

The current site is running on plain HTTP over port `18180`, not HTTPS. The dashboard works, but the login is not encrypted in transit until we move this service behind HTTPS.
