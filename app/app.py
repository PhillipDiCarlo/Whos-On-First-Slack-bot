import os, json, time, yaml, paramiko
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler
import redis

# ---- Config / env ----
SLACK_BOT_TOKEN       = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET  = os.environ.get("SLACK_SIGNING_SECRET", "")
SLACK_APP_TOKEN       = os.environ["SLACK_APP_TOKEN"]  # xapp- for Socket Mode
REDIS_URL             = os.environ.get("REDIS_URL", "redis://redis:6379/0")
POLL_INTERVAL_SEC    = int(os.environ.get("POLL_INTERVAL_SEC", "15"))
HOLD_OCCUPIED_SEC    = int(os.environ.get("HOLD_OCCUPIED_SEC", "600"))
OFFLINE_AFTER_SEC    = int(os.environ.get("OFFLINE_AFTER_SEC", "600"))
SSH_KEY_PATH          = os.environ.get("SSH_KEY_PATH", "/run/secrets/ssh_key")
SSH_TIMEOUT           = int(os.environ.get("SSH_TIMEOUT", "6"))
PANEL_STATE_PATH      = os.environ.get("PANEL_STATE_PATH", "/data/panel.json")
INVENTORY_PATH        = os.environ.get("INVENTORY_PATH", "/config/inventory.yml")
# ---- Slack / Redis ----
app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
r = redis.from_url(REDIS_URL)

# Redis keys
def k_host(host): return f"hosts:{host}"
PANEL_KEY = "panel"  # stores {"channel":"C123","ts":"1700000000.0000"}

# Panel state helpers (Redis primary, file fallback)
def get_panel_state():
    try:
        raw = r.get(PANEL_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    # Fallback to file
    try:
        p = Path(PANEL_STATE_PATH)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            # Backfill Redis for future fast access
            try:
                r.set(PANEL_KEY, json.dumps(data))
            except Exception:
                pass
            return data
    except Exception:
        pass
    return None

def set_panel_state(data: dict):
    # Write to Redis
    try:
        r.set(PANEL_KEY, json.dumps(data))
    except Exception:
        pass
    # Write to file as backup
    try:
        p = Path(PANEL_STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

# Load inventory

def load_inventory_file():
    """Load inventory YAML from INVENTORY_PATH, with fallback to /app/inventory.yml.
    Supports mounting a custom file at /config/inventory.yml by setting INVENTORY_PATH accordingly.
    """
    primary = Path(INVENTORY_PATH)
    fallback = Path("/app/inventory.yml")
    tried = []
    for p in [primary, fallback] if primary != fallback else [primary]:
        tried.append(str(p))
        try:
            if p.exists():
                with p.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or []
                # Very lightweight validation
                if not isinstance(data, list):
                    raise ValueError("inventory must be a YAML list of host entries")
                return data
        except Exception as e:
            # Continue to fallback; at startup we can still run without inventory but commands will be limited
            print(f"[warn] Failed to load inventory from {p}: {e}")
            continue
    raise FileNotFoundError(f"Inventory file not found. Tried: {', '.join(tried)}")
# Load inventory
INVENTORY = load_inventory_file()
# INVENTORY format:
# - host: srv-01.local
#   user: watcher
#   port: 22
#   label: "Build Server"
def default_state(host, label=None):
    return {
        "host": host,
        "label": label or host,
        "status": "free",        # "occupied" | "free" | "offline"
        "last_users": [],
        "empty_streak": 0,       # (legacy, no longer used)
        "fail_streak": 0,        # (legacy, no longer used)
        "first_empty_ts": 0,     # epoch when we first saw “no users”
        "last_ok": 0,            # last successful poll epoch
        "last_update": 0
    }

def load_state(host, label=None):
    raw = r.get(k_host(host))
    s = json.loads(raw) if raw else default_state(host, label)
    if label and s.get("label") != label:
        s["label"] = label
        try:
            r.set(k_host(host), json.dumps(s), ex=60*60*24*14)
        except Exception:
            pass
    # backfill in case of older records
    if "first_empty_ts" not in s: s["first_empty_ts"] = 0
    if "last_ok" not in s: s["last_ok"] = 0
    return s

def save_state(s):
    s["last_update"] = int(time.time())
    r.set(k_host(s["host"]), json.dumps(s), ex=60*60*24*14)

def ssh_who(h):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=h["host"], username=h["user"], port=h.get("port",22),
        key_filename=SSH_KEY_PATH, timeout=SSH_TIMEOUT,
        allow_agent=True, look_for_keys=True
    )
    for cmd in ["who --ips", "who", "users"]:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=5)
        out = stdout.read().decode("utf-8","ignore").strip()
        if out:
            client.close()
            return cmd, out
    client.close()
    return None, ""

def parse_users(cmd, out):
    users = set()
    if cmd in ("who --ips","who"):
        for line in out.splitlines():
            parts = line.split()
            if parts:
                u = parts[0]
                if u not in {"gdm","lightdm","login"}:
                    users.add(u)
    elif cmd == "users":
        for u in out.split():
            if u not in {"gdm","lightdm","login"}:
                users.add(u)
    return sorted(users)

def render_panel_blocks(states):
    # sort: offline first? Usually we want occupied first.
    occupied = [s for s in states if s["status"]=="occupied"]
    free     = [s for s in states if s["status"]=="free"]
    offline  = [s for s in states if s["status"]=="offline"]

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    blocks = [
        {"type":"header","text":{"type":"plain_text","text":"Server Login Status"}},
        {"type":"context","elements":[{"type":"mrkdwn","text":f"*Last update:* {ts}"}]},
    ]

    def add_section(title, rows):
        if not rows: return
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*{title}*"}})
        for s in rows:
            label = s.get("label") or s["host"]
            if s["status"]=="occupied":
                users = ", ".join(s["last_users"])
                line = f"🟢 *{label}* — `{users}`"
            elif s["status"]=="free":
                line = f"⚪ {label}"
            else:
                line = f"🔴 {label} (offline)"
            blocks.append({"type":"section","text":{"type":"mrkdwn","text":line}})

    add_section("Occupied", occupied)
    add_section("Free", free)
    add_section("Offline", offline)
    return blocks

def update_panel():
    # gather states in inventory order
    states = []
    for h in INVENTORY:
        s = load_state(h["host"], h.get("label"))
        states.append(s)

    panel = get_panel_state()
    if not panel:
        return  # panel not created yet
    try:
        app.client.chat_update(
            channel=panel["channel"],
            ts=panel["ts"],
            blocks=render_panel_blocks(states),
            text="Server Login Status"
        )
    except Exception as e:
        # If message was deleted or channel changed, forget the panel
        # Best-effort: clear invalid panel so a new /servers_panel can recreate
        try:
            r.delete(PANEL_KEY)
        except Exception:
            pass
        try:
            Path(PANEL_STATE_PATH).unlink(missing_ok=True)
        except Exception:
            pass

def poll_once():
    now = int(time.time())
    any_dirty = False

    for h in INVENTORY:
        st = load_state(h["host"], h.get("label"))
        prior_status = st["status"]
        prior_users = list(st.get("last_users", []))

        try:
            # try SSH
            cmd, out = ssh_who(h)
            users = parse_users(cmd, out) if cmd else []
            st["last_ok"] = now  # success -> refresh last_ok

            if users:
                # new login(s)
                if prior_status != "occupied" or users != prior_users:
                    st["status"] = "occupied"
                    st["last_users"] = users
                    st["first_empty_ts"] = 0
                    any_dirty = True
                else:
                    # still occupied by same users; no change
                    st["first_empty_ts"] = 0
            else:
                # no users this poll
                if st["status"] == "occupied":
                    # start or continue the hold period
                    if st["first_empty_ts"] == 0:
                        st["first_empty_ts"] = now
                    elif now - st["first_empty_ts"] >= HOLD_OCCUPIED_SEC:
                        st["status"] = "free"
                        st["last_users"] = []
                        st["first_empty_ts"] = 0
                        any_dirty = True
                    # else: still within hold window -> remain occupied, no update
                elif st["status"] == "offline":
                    # came back online with no users; begin hold timer
                    if st["first_empty_ts"] == 0:
                        st["first_empty_ts"] = now
                    # don’t flip panel yet until hold elapses
                else:
                    # already free, nothing to do
                    pass

        except Exception:
            # SSH failed; decide offline only by last_ok age (time-based)
            # keep prior status until OFFLINE_AFTER_SEC passes
            if st["last_ok"] and (now - st["last_ok"] >= OFFLINE_AFTER_SEC):
                if st["status"] != "offline":
                    st["status"] = "offline"
                    st["first_empty_ts"] = 0
                    st["last_users"] = []
                    any_dirty = True
            elif st["last_ok"] == 0 and st["status"] != "offline":
                # never succeeded yet and unreachable for a while -> mark offline
                if now - st.get("last_update", now) >= OFFLINE_AFTER_SEC:
                    st["status"] = "offline"
                    any_dirty = True
            # else: within grace window -> no panel change

        save_state(st)

    if any_dirty:
        update_panel()

# Slash command: create (or move) the panel in the current channel
@app.command("/servers_panel")
def servers_panel(ack, body, respond):
    ack()
    channel = body["channel_id"]
    # If a panel exists elsewhere, we'll replace it with a new message here
    blocks = render_panel_blocks([load_state(h["host"], h.get("label")) for h in INVENTORY])
    res = app.client.chat_postMessage(channel=channel, text="Server Login Status", blocks=blocks)
    set_panel_state({"channel": channel, "ts": res["ts"]})
    respond("Panel created. I'll keep this message updated every few minutes.")

# Optional manual refresh
@app.command("/servers_refresh")
def servers_refresh(ack, respond):
    ack()
    poll_once()
    respond("Refreshed.")

# Scheduler
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    poll_once, "interval",
    seconds=POLL_INTERVAL_SEC,
    max_instances=1, coalesce=True
)

if __name__ == "__main__":
    scheduler.start()
    # initial populate
    try:
        poll_once()
    except Exception:
        pass
    # Run in Socket Mode (no public HTTP needed)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
