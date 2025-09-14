# Whos-On-First-Slack-bot

A Slack bot that posts a live “who’s logged in” panel for your servers. Built in my own time (not affiliated with my employer).

## What this does

- Polls each host over SSH and parses login users (via `who --ips`, `who`, or `users`).
- Keeps per-host state in Redis and edits a single Slack message (“panel”) on every update.
- Remembers the panel location across restarts (Redis, with a JSON file fallback).


## Quick start (Docker Compose)

**Prereqs**

- A Slack app with: Bot Token (xoxb-), App-Level Token for Socket Mode (xapp-), and a Signing Secret.
- SSH key that can read logins on each target host.

### 1) Put 3 files in a folder

Place these in the same directory:

- `docker-compose.yml`
- `.env`
- `inventory.yml`

> Optional: add `id_rsa` (private key) if you don’t want to rely on your system’s ssh-agent.

### 2) Configure `.env` and `inventory.yml`

**`.env` (example)**

```env
SLACK_BOT_TOKEN=xoxb-***
SLACK_APP_TOKEN=xapp-***
SLACK_SIGNING_SECRET=***

# Optional tuning
POLL_INTERVAL_SEC=15
HOLD_OCCUPIED_SEC=600
OFFLINE_AFTER_SEC=600
SSH_TIMEOUT=6
# REDIS_URL=redis://redis:6379/0  # default
```

These names match what the app reads at runtime.

**`inventory.yml` (example)**

```yaml
- host: srv-01.local
  user: watcher
  port: 22
  label: "Build Server"
- host: srv-02.local
  user: watcher
  label: "QA Box"
```

By default the app looks for this at `/config/inventory.yml` and falls back to `/app/inventory.yml` if missing.

### 3) Start it

```bash
docker compose pull
docker compose up -d
```

### 4) Create the Slack panel

In your target channel, run:

```
/servers_panel
```

Use `/servers_refresh` any time to force an immediate poll.

---

## Docker Compose example

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped

  bot:
    # Option A (recommended): pull a published image
    image: ghcr.io/YOUR_ORG/whos-on-first-bot:latest
    # Option B: build locally instead (uncomment and comment out image:)
    # build: .
    depends_on:
      - redis
    restart: unless-stopped
    env_file: .env
    environment:
      REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
      INVENTORY_PATH: /config/inventory.yml
      SSH_KEY_PATH: /run/secrets/ssh_key
      PANEL_STATE_PATH: /data/panel.json
    volumes:
      - ./inventory.yml:/config/inventory.yml:ro
      - bot_data:/data
    secrets:
      - ssh_key
    # (Optional) Use host ssh-agent instead of a key file (Linux/macOS):
    # volumes:
    #   - ${SSH_AUTH_SOCK}:/ssh-agent
    # environment:
    #   SSH_AUTH_SOCK: /ssh-agent

volumes:
  bot_data:

secrets:
  ssh_key:
    file: ./id_rsa   # optional: drop your private key next to the three files
```

> Note: older compose examples used variables like `POLL_MINUTES` and `OFFLINE_THRESHOLD`. The app uses `POLL_INTERVAL_SEC`, `HOLD_OCCUPIED_SEC`, and `OFFLINE_AFTER_SEC` instead — set those in `.env`. 

---

## Inventory

- Default in-container path: `/config/inventory.yml` (bind-mounted from your `inventory.yml`).
- If your custom file is missing/invalid, the app falls back to `/app/inventory.yml` inside the image.

---

## Persistence

- Panel location (channel + `ts`) is stored in Redis; a JSON backup lives at `/data/panel.json`. The compose file keeps `/data` on a named volume so restarts won’t lose the panel.

---

## Environment variables

**Required (Slack / Socket Mode)**

- `SLACK_BOT_TOKEN` — Bot token (xoxb-)
- `SLACK_APP_TOKEN` — App-Level token (xapp-)
- `SLACK_SIGNING_SECRET` — Recommended even in Socket Mode

**Connectivity & behavior**

- `REDIS_URL` — default `redis://redis:6379/0`
- `POLL_INTERVAL_SEC` — default `15`
- `HOLD_OCCUPIED_SEC` — default `600`
- `OFFLINE_AFTER_SEC` — default `600`
- `SSH_TIMEOUT` — default `6`
- `INVENTORY_PATH` — default `/config/inventory.yml`
- `SSH_KEY_PATH` — default `/run/secrets/ssh_key`
- `PANEL_STATE_PATH` — default `/data/panel.json`

---

## Security notes

- Don’t commit real tokens or private keys.
- Prefer a local `.env` for tokens; mount the private key as a file (Docker secret).
- Ensure the key is read-only and scoped appropriately.

---

## Tips

- Re-run `/servers_panel` in a different channel to “move” the panel there.
- `/servers_refresh` triggers an immediate poll outside the interval.