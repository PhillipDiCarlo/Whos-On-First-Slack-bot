# Whos-On-First-Slack-bot

A Slack bot that posts a live “who’s logged in” panel for your servers. Built in my own time (not affiliated with my employer).

## What this does

- Polls each host over SSH and parses login users (via `who --ips`, `who`, or `users`).
- Keeps per-host state in Redis and edits a single Slack message (“panel”) on every update.
- Remembers the panel location across restarts (Redis, with a JSON file fallback).

## Quick start on Windows (Docker Compose)

Prereqs:
- A Slack app with: Bot Token (xoxb-), App-Level Token for Socket Mode (xapp-), and a Signing Secret
- A private SSH key with access to read logins on each target host

1) Prepare the inventory
	- Create `config` next to `docker-compose.yml`.
	- Copy `config/inventory.yml.sample` to `config/inventory.yml`.
	- Edit hosts, users, and labels.

2) Add your SSH key
	- Put your private key at `./secrets/id_rsa` (Compose loads it as a Docker secret).
	- Ensure the corresponding public key is authorized on each host.

3) Provide Slack credentials and start
	- PowerShell (Windows):
	  ```powershell
	  $env:SLACK_BOT_TOKEN = "xoxb-..."; $env:SLACK_APP_TOKEN = "xapp-..."; $env:SLACK_SIGNING_SECRET = "..."
	  docker compose up -d --build
	  ```
	- Tip: You can also create a `.env` file (not committed) with those variables; Compose reads it automatically.

4) Place the panel in Slack
	- In your target channel, run `/servers_panel` once to create the panel message.
	- Later, use `/servers_refresh` to force an immediate poll.

## Run with a single Docker container (no Compose)

This app also needs Redis. The simplest approach is a small user-defined network so containers can talk by name.

1) Build the image
	```powershell
	docker build -t whos-on-first:local .
	```

2) Create a network and start Redis
	```powershell
	docker network create servers-net
	docker run -d --name redis --network servers-net redis:7-alpine
	```

3) Prepare config and key
	- Ensure `config/inventory.yml` exists (see sample).
	- Ensure `secrets/id_rsa` exists and is readable.

4) Run the bot container
	```powershell
	$env:SLACK_BOT_TOKEN = "xoxb-..."
	$env:SLACK_APP_TOKEN = "xapp-..."
	$env:SLACK_SIGNING_SECRET = "..."
	docker run -d --name servers-panel --network servers-net `
	  -e SLACK_BOT_TOKEN=$env:SLACK_BOT_TOKEN `
	  -e SLACK_APP_TOKEN=$env:SLACK_APP_TOKEN `
	  -e SLACK_SIGNING_SECRET=$env:SLACK_SIGNING_SECRET `
	  -e REDIS_URL=redis://redis:6379/0 `
	  -e INVENTORY_PATH=/config/inventory.yml `
	  -e SSH_KEY_PATH=/run/secrets/ssh_key `
	  -e PANEL_STATE_PATH=/data/panel.json `
	  -v "$PWD/config:/config" `
	  -v "$PWD/secrets/id_rsa:/run/secrets/ssh_key:ro" `
	  -v whosof_data:/data `
	  whos-on-first:local
	```

5) In Slack, run `/servers_panel` in your channel to create the message

## Inventory

- Default path inside the container: `/config/inventory.yml`
- You can mount a host file to that path (as shown above) or override via env: `INVENTORY_PATH=/some/other/path/inventory.yml`
- If your custom file is missing or invalid, the bot falls back to the built-in `/app/inventory.yml` bundled in the image.

Inventory file shape:

```yaml
- host: srv-01.local
  user: watcher
  port: 22
  label: "Build Server"
- host: srv-02.local
  user: watcher
  label: "QA Box"
```

## Persistence

- Panel message location (channel + ts) is stored in Redis as the source of truth.
- As a backup, it also writes `/data/panel.json`. Mounting a volume at `/data` keeps the panel location across restarts.

## Environment variables (current)

Required for Slack/Socket Mode:
- `SLACK_BOT_TOKEN` — Bot token (xoxb-)
- `SLACK_APP_TOKEN` — App-Level token (xapp-) for Socket Mode
- `SLACK_SIGNING_SECRET` — Recommended, even with Socket Mode

Connectivity and behavior:
- `REDIS_URL` — Redis connection string (default `redis://redis:6379/0`)
- `POLL_INTERVAL_SEC` — Poll interval in seconds (default `15`)
- `HOLD_OCCUPIED_SEC` — Keep host “occupied” this many seconds after last seen user (default `600`)
- `OFFLINE_AFTER_SEC` — Mark host “offline” if no successful poll for this many seconds (default `600`)
- `SSH_TIMEOUT` — SSH connect timeout in seconds (default `6`)
- `INVENTORY_PATH` — Defaults to `/config/inventory.yml`; falls back to `/app/inventory.yml`
- `SSH_KEY_PATH` — Defaults to `/run/secrets/ssh_key`
- `PANEL_STATE_PATH` — Defaults to `/data/panel.json`

Note: The compose file may include some legacy variable names; the app uses the variables listed above. If you want to customize timing, set the newer variables.

## Security notes

- Don’t commit real tokens or private keys. Prefer a local `.env` for tokens and mount secrets/keys as files.
- Ensure your SSH key is read-only and only authorized for what’s needed.

## Tips

- First run: use `/servers_panel` in the Slack channel where you want the panel.
- You can re-run `/servers_panel` in a different channel to move the panel there.
- Use `/servers_refresh` to trigger an immediate poll outside the normal interval.

