You're helping me test the cellular link on my delivery robot. Read all of this before doing anything.

## Setup

- **Robot:** Raspberry Pi 5 (user `sdteam22`). A Blues Notecard (cellular) is wired to it over I2C at address `0x17`. The Notecarrier
  has its own power supply and shares a ground with the Pi.
- **This Mac powers the Pi** through its USB-C port. The same cable is also a USB network link: the Pi is `192.168.77.1`, and the SSH
  alias `robot` in my `~/.ssh/config` points to it, with key login. **The Pi has no internet**, so anything that talks to Notehub
  (Blues' cloud) has to run on this Mac.
- **Data path:** this Mac → Notehub REST API (`commands.qi`) → LTE → Notecard → I2C → `receive_demo.py` on the Pi. The Pi replies with
  an ack on `acks.qo`.
- **On the Pi**, `~/testing/cellular_test/cellular_logger.sh` runs `receive_demo.py` in a detached tmux session called `cellular`. It
  starts by itself about 15 s after boot and restarts 5 s after a crash. Everything goes to
  `~/testing/cellular_test/logs/cellular_log.txt`.
- **Full reference:** `ssh robot cat testing/CELLULAR.md`. Read it if anything below is unclear.

## Get ready

1. **Check SSH:** `ssh -o BatchMode=yes robot 'hostname; ip -br addr show usb0; tmux ls'`. If it fails with a host-key error, ask me
   to run `ssh robot` once and answer "yes". Don't disable host-key checking.
2. **Copy the control panel:** `mkdir -p ~/robot-panel && scp 'robot:testing/cellular_test/control_panel/*' ~/robot-panel/`
3. **Notehub API key:** I've already saved my `NOTEHUB_API_KEY` on this Mac. **Ask me where it is**; don't search for it.
   - The panel reads `NOTEHUB_API_KEY` from the environment, or from a file given with `--env`. The default is `~/robot-panel/.env`,
     with a line `NOTEHUB_API_KEY=...`, mode 600.
   - **Never print, echo, cat or log the key**, never put it on a command line, never copy it to the Pi, and never repeat it to me.
     To check that it's present, use something like `grep -c '^NOTEHUB_API_KEY=.' FILE`.
   - The Pi's `~/testing/cellular_test/.env` holds an older token. Don't copy it or use it.
4. **Start the panel:** `python3 ~/robot-panel/panel.py [--env FILE]`, in the background. Its startup line must say
   `NOTEHUB_API_KEY set`. Then I open http://127.0.0.1:8765.
   - If a send fails with `CERTIFICATE_VERIFY_FAILED`, this Python has no CA certificates. For a python.org install, run
     `/Applications/Python 3.x/Install Certificates.command`.

## The panel's local API (you can use it too)

- `curl -s -X POST -H 'X-Panel: 1' -d '{"type":"ping"}' http://127.0.0.1:8765/api/send`: sends a command and returns its `id`.
  The `X-Panel: 1` header is required. Other types:
  - `{"type":"stop"}`
  - `{"type":"navigate","body":{"lat":40.4274,"lon":-86.9139}}`
  - `{"type":"route","body":{"destination":{"lat":..,"lon":..},"polyline":[[lon,lat],...]}}`. Polyline points are **[lon, lat]**.
  - The panel adds `id`, and adds `issuedAt` for `route`/`navigate`.
- `curl -s 'http://127.0.0.1:8765/api/state?since=0'`: log lines, link and Pi status, and every sent command with its stages:
  `http` (200 = queued in Notehub) → `received` (seen in the Pi log) → `result` (the Pi's answer, also queued as an ack) →
  `cloud_ack` (filled in only by `check-acks`).
- `POST /api/check-acks`: one Events API call. **At most once every 5 s.** Polling Notehub about once a second gets HTTP 429, and that
  also blocks sending commands.
- `POST /api/logger/start` and `POST /api/logger/stop`.

## Reading the Pi's log

Every line looks like `YYYY-MM-DD HH:MM:SSZ  message`. The time is UTC from the Notecard's network clock: the Pi's own clock may be
wrong because it has no NTP. You can read it directly with `ssh robot 'tail -n 100 ~/testing/cellular_test/logs/cellular_log.txt'`, or
follow it with `tail -F` over SSH.

**Healthy:**

- `===== receiver start ... =====`, then `card: dev:868531063312800  hub: connected (session open) {connected}`.
- `heartbeat: hub='connected (session open) {connected}' bars=N ...` every 60 s.
- For each command: `received: {...}`, then `raw: {...}`, then `result: {"id": ..., "ok": true, ...}`. A ping's result is `pong`;
  route, navigate and stop give `logged`. The handlers only print; nothing moves.
- The basement measured 1.5–3 s from send to received, at 1 bar with RSRP −106 to −117 dBm.

**Problems:**

| Log line or sign | Meaning |
|---|---|
| `receiver crashed: Exception('Failed to reset Notecard.')` | The Pi can't reach the card over I2C: wiring, ground or power. Ask me to check. |
| `{connected-closed}` in `hub=` | The cloud session dropped and inbound push stops. The receiver's watchdog forces `hub.sync` after 30 s, and reconnecting takes about 90 s. Note how often it happens. |
| `bars=0` or `bars=None` | No signal. |
| `notecard error:` or `I/O error` | Report it with context. |
| No `received:` line well after HTTP 200 | Look at the latest heartbeat (session, signal). The command waits in Notehub until the card connects. |
| Result `"error": "stale"` | `issuedAt` was too old when the card received it (route over 600 s, navigate over 60 s). Expected for anything queued while the card was offline. |
| `"duplicate": true` | The same `id` was received again. It's acked but not acted on. |
| Panel shows Power ≠ OK (`vcgencmd get_throttled` ≠ `0x0`) | The Pi saw undervoltage on Mac power. Tell me right away. |

## Rules

- **Treat the Pi as read-only while the logger runs.** Reading logs, `vcgencmd`, `uptime`, `dmesg` and `ip` is fine.
  - Don't run `notecard_link.py`, `send_demo.py`, `cloud_inject.py`, pytest hardware tests or `i2cdetect` while it runs: only one
    program may talk to the card at a time.
  - If you need direct card access, stop the logger first, and tell me.
- Don't edit code on the Pi, change its configuration, reboot it or touch `usb0` or networking without asking me. Losing the USB
  link loses SSH, and I'm upstairs with no other way in.
- These earlier test commands are still queued in Notehub and will arrive first once the card is online. They are not part of the test:
  - pings `5a3494ee` and `65c38679` (`65c38679` was sent twice; the second copy acks as a duplicate)
  - route `36112227`, which will ack `stale`

## Test plan

1. **Ethernet still plugged in** (baseline): send a ping. Expect `received` within a few seconds and the result `pong`. Then send
   navigate, route and stop, then check acks once.
2. **I unplug Ethernet:** repeat step 1. Results should be the same, since the cellular path doesn't use Ethernet.
3. **We move upstairs:** unplugging from the Mac powers the Pi off.
   - After I plug back in, wait for SSH. The logger starts about 15 s after boot, and the card may need a minute or two to open its
     session.
   - Watch for heartbeats showing `{connected}`.
   - Send about 10 pings, about 10 s apart.
   - Report: received rate, send-to-received time (min, median, max), bars, RSRP and SINR, any `{connected-closed}`, and the power
     status. Compare them to the basement numbers above.

Keep me posted in short updates. When something fails, quote the exact log lines.
