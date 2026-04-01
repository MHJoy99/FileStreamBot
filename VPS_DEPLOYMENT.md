# FileStreamBot VPS Deployment Guide

This guide is for deploying this repo on a fresh Ubuntu VPS with `systemd`.

It follows the current working pattern used by this project:

- Python virtualenv
- `.env` in the repo root
- direct public port exposure
- `systemd` service for auto-start and restart

If you want the simplest reliable setup, use the direct-port method first. You can put it behind nginx or Cloudflare later.

## What this bot needs

- A VPS with a public IP
- A domain or subdomain pointing to the VPS, or the VPS IP itself
- Python 3.11+ with `venv`
- MongoDB connection string
- Telegram bot token
- Telegram API ID and API hash
- A file log channel and a user log channel

## Important Telegram setup

Before starting the bot:

- Add the main bot to `FLOG_CHANNEL` as admin
- Add the main bot to `ULOG_CHANNEL` as admin
- If you use `MULTI_TOKEN1`, `MULTI_TOKEN2`, or any extra Telegram session/client, make sure those clients can also access `FLOG_CHANNEL`

If an extra client cannot access `FLOG_CHANNEL`, link generation and stream delivery can become partially degraded.

## 1. Prepare the VPS

```bash
apt update
apt install -y git curl ufw python3 python3-venv python3-pip
```

Optional but useful:

```bash
apt install -y nano
```

## 2. Clone the project

This guide uses `/root/FileStreamBot` to match the current live setup.

```bash
cd /root
git clone https://github.com/avipatilpro/FileStreamBot.git
cd FileStreamBot
```

## 3. Create the virtualenv and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create the `.env` file

Create `/root/FileStreamBot/.env`:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456789:your_bot_token
OWNER_ID=123456789

DATABASE_URL=mongodb://127.0.0.1:27017
SESSION_NAME=FileStream

FLOG_CHANNEL=-1001234567890
ULOG_CHANNEL=-1001234567890

FQDN=stream.example.com
HAS_SSL=False
NO_PORT=False
PORT=18180
BIND_ADDRESS=0.0.0.0

AUTH_USERS=123456789
WORKERS=6
SLEEP_THRESHOLD=60

ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_this_to_a_strong_password
WEB_SESSION_SECRET=change_this_to_a_long_random_secret
WEB_SESSION_TTL=2592000

UPDATES_CHANNEL=Telegram
FORCE_SUB=False
```

## 5. Recommended optional env vars

Add these only if you need them:

```env
USER_SESSION_STRING=your_user_session_string
MULTI_TOKEN1=123456789:extra_bot_token_or_session_string
MULTI_TOKEN2=123456789:extra_bot_token_or_session_string

START_PIC=https://example.com/start.jpg
FILE_PIC=https://example.com/files.jpg
VERIFY_PIC=https://example.com/verify.jpg

BUNDLE_FALLBACK_CHAT=-1001234567890
TMDB_API_KEY=your_tmdb_api_key
TMDB_READ_ACCESS_TOKEN=your_tmdb_read_access_token
```

Notes:

- `USER_SESSION_STRING` is needed for full Telegram history scanning features
- `MULTI_TOKEN*` improves concurrent serving, but every extra client must be able to read `FLOG_CHANNEL`
- `HAS_SSL=True` should only be used if the public URL is really HTTPS
- `NO_PORT=True` should only be used when the service is exposed on standard `80/443`

## 6. Test the bot manually first

From the repo root:

```bash
source .venv/bin/activate
python -m FileStream
```

You should see startup output and a URL line.

Stop it with `Ctrl+C` after confirming it starts.

## 7. Create the `systemd` service

Create `/etc/systemd/system/filestreambot-stream.service`:

```ini
[Unit]
Description=FileStreamBot
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/FileStreamBot
ExecStart=/root/FileStreamBot/.venv/bin/python -m FileStream
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
systemctl daemon-reload
systemctl enable filestreambot-stream.service
systemctl start filestreambot-stream.service
```

## 8. Open the firewall port

If you are using the direct public port method:

```bash
ufw allow 18180/tcp
ufw enable
```

If `ufw` is already enabled, only the first command is needed.

## 9. Check service health

Check process status:

```bash
systemctl status filestreambot-stream.service --no-pager
```

Check recent logs:

```bash
journalctl -u filestreambot-stream.service -n 100 --no-pager
```

Check the bot status endpoint:

```bash
curl --noproxy '*' -sS http://stream.example.com:18180/status
```

If `FQDN` is not set yet, test with the server IP:

```bash
curl --noproxy '*' -sS http://YOUR_SERVER_IP:18180/status
```

## 10. Verify bot behavior in Telegram

After deployment, test these:

1. Send `/start` to the bot
2. Send a file to the bot in private chat
3. Confirm the bot replies with stream/download buttons
4. Open the generated link in a browser
5. Visit `/admin/login` and confirm the admin panel loads

Example URLs:

- `http://stream.example.com:18180/status`
- `http://stream.example.com:18180/admin/login`

## Common problems

### Bot starts but does not reply with a link after file upload

Check:

- Is the bot admin in `FLOG_CHANNEL`?
- Is the bot admin in `ULOG_CHANNEL`?
- Are extra `MULTI_TOKEN*` clients able to access `FLOG_CHANNEL`?

Useful command:

```bash
journalctl -u filestreambot-stream.service -n 200 --no-pager
```

### Stream links are generated with the wrong host or wrong scheme

Check:

- `FQDN`
- `HAS_SSL`
- `NO_PORT`
- `PORT`

These values control the public links the bot sends.

### Admin login works but is not secure

If you use direct HTTP on a public port:

- the admin website works
- but login is not encrypted in transit

For secure admin login, move the service behind HTTPS later and then set:

```env
HAS_SSL=True
```

### `/status` works locally but not from outside

Check:

- firewall rule for the chosen port
- VPS provider firewall/security group
- DNS record points to the correct IP
- the service is listening on `0.0.0.0`

## Updating the bot later

```bash
cd /root/FileStreamBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart filestreambot-stream.service
```

Then verify:

```bash
systemctl status filestreambot-stream.service --no-pager
journalctl -u filestreambot-stream.service -n 50 --no-pager
```

## Current recommended deployment style for this repo

For the least risky setup on a new VPS:

- keep the bot on a direct public port like `18180`
- use `FQDN=your-subdomain`
- use `HAS_SSL=False` unless HTTPS is really configured
- use `AUTH_USERS` if you want to limit who can use the bot
- add only those extra Telegram clients that can access `FLOG_CHANNEL`

Once the bot is stable, you can later move it behind nginx and HTTPS if needed.
