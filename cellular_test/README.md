# Notecard cellular bring-up test (throwaway)

Standalone test of a Blues Notecard Cell+WiFi (NOTE-MBGLW) on a Notecarrier X, attached to the Pi over **I2C**
(it was on USB first; see "Connecting the card"). Nothing here is wired into robot code, and **nothing drives motors**: command handlers only print.

**Start with [`../CELLULAR.md`](../CELLULAR.md)**: everything about the cellular link in one place (hardware, setup, config, troubleshooting, lessons).
**App team: the command/ack contract is in [`APP_INTEGRATION.md`](APP_INTEGRATION.md).**
The history of the bring-up is in [`BRINGUP_REPORT.md`](BRINGUP_REPORT.md).

```
 cloud_inject.py ──REST──▶ Notehub ──sync──▶ Notecard ──JSON/I2C──▶ receive_demo.py      (downlink, commands.qi)
 mqtt_watch.py ◀──MQTT── broker ◀──Route── Notehub ◀──sync── Notecard ◀── send_demo.py    (uplink, telemetry.qo / acks.qo)
```

The Notecard is **not a modem**. The Pi exchanges line-delimited JSON requests with it (`note.add`, `note.changes`, `hub.sync`, …),
and the card syncs Notes with Notehub by itself. The Pi has no IP path "through" the card.

## Install

```bash
cd cellular_test
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Tests (no hardware, no network)

```bash
.venv/bin/pytest            # hardware/network tests are skipped
RUN_HW=1 .venv/bin/pytest   # also run tests/test_hardware.py (needs the card, plus Notehub credentials for the API test)
```

`tests/fake_notecard.py` is a `FakeNotecard` that records every request and returns canned responses.

## Connecting the card

**I2C (current).** Notecarrier SDA/SCL/GND → Pi pin 3 (GPIO2, SDA) / pin 5 (GPIO3, SCL) / GND. Enable I2C in `raspi-config`,
then check that `17` shows up:

```bash
i2cdetect -y 1                       # Notecard is 0x17 on /dev/i2c-1
```

`open_card()` in `notecard_link.py` returns `open_i2c()` (python-periphery, `/dev/i2c-1`, `0x17`). Every script goes through it.

**USB serial (earlier).** Change `open_card()` to `return open_serial()`. Then:

```bash
ls /dev/ttyACM*                      # normally /dev/ttyACM0
dmesg | grep -iE "30a4|ttyACM"       # Blues USB vendor id is 30a4
groups | grep dialout                # your user needs dialout
```

To use a different port, set `NOTECARD_PORT=/dev/ttyACM1`. Over USB the card kept resetting on this Pi's weak supply (see Power).

A quick sanity check that prints `card.version`, `hub.status` and `card.wireless`:

```bash
.venv/bin/python notecard_link.py
```

### Power: check this first
The cellular radio draws current bursts. If the Pi can't supply them, the card USB-resets in the middle of a request.
Symptom: `card.version` works, but `hub.status` fails with `JSONDecodeError: Expecting value: line 2 column 1`. Check:

```bash
vcgencmd get_throttled               # anything other than 0x0 = undervoltage/throttling has happened
dmesg | grep -E "USB disconnect|Undervoltage"
```

Fix: use the official 5V/5A Pi 5 PSU (with a weaker PSU the Pi 5 caps USB current at 600 mA total), a powered USB hub,
or give the Notecarrier its own supply. Check what the PSU negotiated (want `5000`):

```bash
od -An -tu4 --endian=big /proc/device-tree/chosen/power/max_current
```

Over I2C the card no longer resets, but the Pi still logs undervoltage on a 3 A supply, and a dropped Notehub session happened
during those events (see "Fast inbound delivery").

## Running the demos

| Script | What it does |
|---|---|
| `receive_demo.py [--interval 1] [--once] [--no-ack]` | On start, applies `hub.set {"mode":"continuous","sync":true}`. Then polls `commands.qi` with `note.changes` (`delete:true`), validates, checks staleness and dedupes each command (`route`/`navigate`/`stop`/`ping`, print only), and posts one ack per command to `acks.qo`. A watchdog forces `hub.sync` if the Notehub session stays closed. |
| `send_demo.py [--seq N] [--wait 60]` | `note.add` a fake telemetry body to `telemetry.qo` with `sync:true`, then `hub.sync`, then watches `hub.sync.status`. |
| `cloud_inject.py ['<json>']` | Cloud → device: API key (or OAuth2 token), then `POST /v1/projects/{PROJECT_UID}/devices/{DEVICE_UID}/notes/commands.qi` with `{"body": <json>}`. With no argument it sends a ping. |
| `mqtt_watch.py` | Subscribes to your Route's broker and prints the events it receives. |

### Downlink round trip
```bash
# terminal 1 (Pi)
.venv/bin/python receive_demo.py

# terminal 2 (anywhere with internet)
# or put these in cellular_test/.env (gitignored); cloud_inject.py loads it
export NOTEHUB_API_KEY=...                                      # Notehub → user menu (top right) → API Access → Create New Token
export PROJECT_UID=app:xxxxxxxx-...                             # Notehub project UID
export DEVICE_UID=dev:868531063312800
# deprecated alternative to NOTEHUB_API_KEY: NOTEHUB_CLIENT_ID + NOTEHUB_CLIENT_SECRET (Project → Settings → OAuth)
.venv/bin/python cloud_inject.py '{"id":"abc","type":"navigate","body":{"lat":40.42,"lon":-86.91}}'
```
With immediate sync on (see "Fast inbound delivery"), the note reaches the Pi in about 2 s. Without it, the note waits for the
next inbound sync; to force one, run `hub.sync` (for example `send_demo.py`, or `link.sync()`).

### Uplink round trip
```bash
# terminal 1
export MQTT_HOST=test.mosquitto.org MQTT_PORT=1883 MQTT_TOPIC='delivery_robot/#'
.venv/bin/python mqtt_watch.py
# terminal 2 (Pi)
.venv/bin/python send_demo.py --seq 1
```

## Notehub credentials (`.env`)

`cloud_inject.py` and `tests/test_hardware.py` read `cellular_test/.env` (gitignored, mode 600). Real environment variables win.

| Variable | Where it comes from |
|---|---|
| `NOTEHUB_API_KEY` | Personal access token: Notehub → user menu (top right) → **API Access** → Create New Token |
| `PROJECT_UID` | Notehub → project → Settings; starts with `app:` |
| `DEVICE_UID` | `card.version` / `hub.get` on the card: `dev:868531063312800` |
| `NOTEHUB_CLIENT_ID` / `NOTEHUB_CLIENT_SECRET` | Deprecated alternative to the API key: project → Settings → **OAuth**. Only used if `NOTEHUB_API_KEY` is empty. |

There is no "Programmatic API access" menu in Notehub; that name was wrong in an earlier version of this README.

## Fast inbound delivery

By default the card only checks Notehub for inbound notes now and then: a command waited **more than 150 s**. With

```json
{"req": "hub.set", "mode": "continuous", "sync": true}
```

the card keeps a Notehub session open and Notehub pushes each new inbound note right away: **1.5–2.8 s** from the POST to the Pi
receiving it, and about 5–6.5 s for the full round trip including the ack in the Events API. It costs some extra power and data (accepted).
The card stores the setting. `receive_demo.py` re-applies it on every start (`NotecardLink.enable_immediate_sync()`),
so a replacement or factory-reset card is covered too.

This only works while `hub.status` shows `connected (session open) {connected}`. If it shows `connected {connected-closed}`,
pushes stop. `receive_demo.py`'s `SessionWatchdog` forces a `hub.sync` after 30 s closed, retrying every 2 min. A reconnect can take
about 90 s because the modem power-cycles.

## Creating the Notehub outbound MQTT Route

Source: [Routing Data to Cloud: MQTT](https://dev.blues.io/guides-and-tutorials/routing-data-to-cloud/mqtt/)

1. Notehub → your project → **Routes** → **Create Route** → **MQTT**.
2. **Broker URL**: `scheme://host`, where scheme is one of `mqtt`, `mqtts`, `tcp`, `ws`, `wss`.
   For local testing use `mqtt://test.mosquitto.org`. The broker must be reachable from the internet;
   a Mosquitto on the Pi's LAN is not reachable by Notehub unless you expose it.
3. **Port**: `1883` (the default; `8883` for `mqtts`).
4. **Username / Password**: leave blank for test.mosquitto.org. Certificate / Private Key only if your broker needs client certs.
5. **Topic**: `delivery_robot/[device]/telemetry`. Notehub substitutes `[device]` → `dev:868531063312800`
   (and `[product]` → ProductUID). Subscribe with `MQTT_TOPIC='delivery_robot/+/telemetry'` or `delivery_robot/#`.
6. **Filters → Notefiles**: select `telemetry.qo` and `acks.qo` (or leave "all").
7. Save. To verify, open **Events**, click a `telemetry.qo` event, and check the **Route log** tab for a green check.

By default the full Notehub event JSON is published, and `mqtt_watch.py` prints its `device`, `file` and `body`.
test.mosquitto.org is public: anyone can read the topic, so use it only for fake test data.

## Downlink "purely over MQTT"? Not supported by Notehub

The task asked for Notehub's MQTT API endpoint, topic format and auth. I checked the docs (2026-09-25):
the [Notehub API reference](https://dev.blues.io/api-reference/notehub-api/) lists only REST APIs
(Authorization, Billing Account, Device, Event, Jobs, Monitor, Organization, Project, Route, Usage), and the
[Notehub walkthrough](https://dev.blues.io/notehub/notehub-walkthrough/) ("Sending Data from Notehub to Notecard") lists only
the **Notehub UI** or the **Notehub REST API** (inbound Notes or environment variables). MQTT appears only as an
**outbound** Route type. **Notehub has no documented inbound MQTT broker/topic for sending notes to a device.**

To drive downlink from MQTT anyway, run a small bridge: subscribe to your own broker (for example `delivery_robot/<device>/commands`),
and for each message call `cloud_inject.access_token()` + `cloud_inject.inject_note()`, which is the same REST call as above.
