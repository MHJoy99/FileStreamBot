# FileStreamBot Setup Notes

## Current live state

- Service name: `filestreambot-stream.service`
- Public status URL: `http://stream.mhjoygamershub.com:18180/status`
- Current host mode: direct public port on `18180`
- Current domain mode: `DNS only`, not Cloudflare proxy
- Firewall: `18180/tcp` is allowed in `ufw`
- Bot access: restricted to the owner Telegram ID via `AUTH_USERS`

## Why this setup was chosen

- The original WordOps/nginx path on `80/443` was behaving unpredictably for this subdomain.
- The direct port setup was the lowest-risk path that got the bot working without touching other sites more than necessary.
- The bot itself works correctly on the VPS and the direct file URLs respond from outside.

## Important files

- Bot env: `.env`
- Main entry: `FileStream/__main__.py`
- Stream route: `FileStream/server/stream_routes.py`
- Telegram download path: `FileStream/utils/custom_dl.py`

## Current `.env` shape

These values are intentionally not repeated here because the real secrets already live in `.env`.

Important non-secret runtime behavior:

- `FQDN=stream.mhjoygamershub.com`
- `HAS_SSL=False`
- `NO_PORT=False`
- `PORT=18180`
- `BIND_ADDRESS=0.0.0.0`
- `AUTH_USERS=<owner id only>`

## Service commands

Check status:

```bash
systemctl status filestreambot-stream.service --no-pager
```

Restart:

```bash
systemctl restart filestreambot-stream.service
```

Public health check:

```bash
curl --noproxy '*' -sS http://stream.mhjoygamershub.com:18180/status
```

## Known operational note

- Restarts can spend a bit too long in `deactivating (stop-sigterm)` before the new process comes up.
- The service does recover and becomes `active`, but this is worth tightening later in the systemd unit if more tuning is done.

## Safe next-step rule

- Prefer keeping this bot on the direct public port until there is a clear reason to revisit WordOps/nginx routing.
- Do not change unrelated nginx vhosts for this bot unless absolutely necessary.
