# Whos-On-First-Slack-bot
A Slack bot designed to show in a slack channel who is logged into each given server. Designed in my own time for the company I currently work for. (Not associated or owned by said company)

## Quick start (Docker)

Prereqs:
- A Slack app with the Bot Token (xoxb-), App Token (xapp- for Socket Mode), and signing secret
- SSH key that can read each target host's login sessions (e.g., paramiko over who/users)

1) Copy the sample inventory and customize it:

	 - Create a `config` folder next to `docker-compose.yml`
	 - Copy `config/inventory.yml.sample` to `config/inventory.yml`
	 - Edit hosts, users, and labels to match your servers

2) Provide Slack credentials and run:

	 - PowerShell (Windows):
		 ```powershell
		 $env:SLACK_BOT_TOKEN = "xoxb-..." ; $env:SLACK_APP_TOKEN = "xapp-..." ; $env:SLACK_SIGNING_SECRET = "..."
		 docker compose up -d --build
		 ```

3) Provide the SSH key

	 This compose file expects a Docker secret named `ssh_key` from `./secrets/id_rsa`.
	 Put your private key there, and ensure the corresponding public key is authorized on each host.

4) In Slack, run the slash command in your target channel:

	 - `/servers_panel` — creates the status panel (the bot remembers this message across restarts)
	 - `/servers_refresh` — triggers an immediate poll

## Customizing the inventory

- Default path inside the container: `/config/inventory.yml`
- You can mount a host file to that path (as in `docker-compose.yml`) or override via env:
	- `INVENTORY_PATH=/some/other/path/inventory.yml`
- If the custom file is missing or invalid, the bot falls back to the built-in `/app/inventory.yml` bundled in the image.

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

- Panel message location (channel + ts) is stored in Redis and backed up to `/data/panel.json`.
- Compose mounts a named volume at `/data`, so the bot keeps updating the same message after restarts.

## Environment variables

- SLACK_BOT_TOKEN — required
- SLACK_APP_TOKEN — required (Socket Mode)
- SLACK_SIGNING_SECRET — optional for Socket Mode, recommended
- REDIS_URL — defaults to `redis://redis:6379/0`
- POLL_MINUTES — interval minutes (default 10)
- LOGOUT_DEBOUNCE — empty polls before “free” (default 2)
- OFFLINE_THRESHOLD — failed polls before “offline” (default 2)
- INVENTORY_PATH — defaults to `/config/inventory.yml`; falls back to `/app/inventory.yml`
- SSH_KEY_PATH — defaults to `/run/secrets/ssh_key`
- PANEL_STATE_PATH — defaults to `/data/panel.json`

## Build the image locally

```powershell
docker build -t whos-on-first:local .
```

Run it without compose (example):

```powershell
docker run --rm -it \
	-e SLACK_BOT_TOKEN=$env:SLACK_BOT_TOKEN \
	-e SLACK_APP_TOKEN=$env:SLACK_APP_TOKEN \
	-e SLACK_SIGNING_SECRET=$env:SLACK_SIGNING_SECRET \
	-v "$PWD/config:/config" \
	-v whosof_data:/data \
	-v "$PWD/secrets/id_rsa:/run/secrets/ssh_key:ro" \
	--name servers-panel \
	whos-on-first:local
```

Note: On first run, use `/servers_panel` in your Slack channel to place the panel message.
