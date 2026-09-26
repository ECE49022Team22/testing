# Cellular (Blues Notecard): everything we know

The single reference for the robot's cellular link, so the next person doesn't have to rediscover it.
Last updated 2026-09-25. Code lives in [`cellular_test/`](cellular_test/).

| Doc | For |
|---|---|
| **This file** | Everything: hardware, setup, config, running, troubleshooting, lessons learned |
| [`cellular_test/APP_INTEGRATION.md`](cellular_test/APP_INTEGRATION.md) | The command/ack contract with the web app team (full field rules and error strings) |
| [`cellular_test/README.md`](cellular_test/README.md) | Script reference, MQTT route setup |
| [`cellular_test/BRINGUP_REPORT.md`](cellular_test/BRINGUP_REPORT.md) | Dated log of what was tried and measured |

---

## 1. What it is (read this first)

```
Web app ──HTTPS POST──▶ Notehub ──LTE──▶ Notecard ──I2C──▶ Raspberry Pi (receive_demo.py)
        (commands.qi)    (Blues cloud)                      │
Web app ◀── Events API / MQTT route ◀── Notehub ◀──LTE── Notecard ◀─┘ (acks.qo, telemetry.qo)
```

- **The Notecard is not a modem.** The Pi does not get an IP connection or internet through it. The Pi sends it small
  JSON requests (`note.add`, `note.changes`, `hub.sync`, …) and the card syncs **notes** (small JSON objects) with **Notehub**,
  Blues' cloud service, by itself.
- **Notefiles** are named queues. A `.qi` notefile goes **to** the device (inbound), a `.qo` notefile comes **from** the device (outbound).
  We use `commands.qi` (app → robot), `acks.qo` (robot → app replies) and `telemetry.qo` (robot → app data).
- **Downlink is HTTP only.** The app sends commands with the Notehub REST API. Notehub has **no inbound MQTT**: MQTT
  exists only as an *outbound* Route, which is fine for acks and telemetry.

## 2. Hardware

| Item | Value |
|---|---|
| Notecard | Blues **NOTE-MBGLW** (Cell + WiFi + GPS), firmware `notecard-11.3.1.17696`, board 5.13 |
| Carrier board | Notecarrier X |
| Device UID / IMEI | `dev:868531063312800` / `868531063312800` |
| SIM | built-in, ICCID `89011704274514370247` |
| Modem | Quectel `EG916QGLLGR01A05M04` |
| Network seen | AT&T LTE band 2; indoors 1 bar, RSRP −106 to −117 dBm, SINR 5–10 |
| Host | Raspberry Pi 5 Model B Rev 1.1 |

### Wiring (current: I2C)

| Notecarrier | Pi 5 header |
|---|---|
| SDA | pin 3 (GPIO2, SDA1) |
| SCL | pin 5 (GPIO3, SCL1) |
| GND | any GND |

- **Bus:** `/dev/i2c-1`. **Address:** `0x17`. `/boot/firmware/config.txt` has `dtparam=i2c_arm=on`.
- **Permissions:** the user must be in the `i2c` group (`/dev/i2c-1` is `root:i2c 660`). `sdteam22` already is.
- **Check:** `i2cdetect -y 1` should show `17`.
- **The bus is shared.** The BNO085 IMU is on the same bus at `0x4A` (see `imu.py`), and there's also an unidentified device at `0x6a`.
  If the BNO085 resets in the middle of a transfer it can hold SDA low and **jam the whole bus, including the Notecard**
  (`i2cdetect` hangs). `recover_bus()` in `imu.py` clears it. The Notecard itself has no SPI; it supports only I2C or serial.

### USB (earlier, don't use on this Pi)

The card also works over USB serial (`/dev/ttyACM0`, needs the `dialout` group; it enumerates as `30a4:0003` "Cygnet Test App",
which is harmless). **On this Pi it browned out:** the card USB-reset on every radio burst, so `card.version` worked but `hub.status`
returned an empty line (`JSONDecodeError: Expecting value: line 2 column 1`). To switch back anyway: `open_card()` → `return open_serial()`.

### Power (still unresolved)

- The cellular radio pulls current bursts. The Pi's current supply negotiates only **3000 mA**
  (`od -An -tu4 --endian=big /proc/device-tree/chosen/power/max_current`), which caps USB at 600 mA total, and the Pi logs
  `Undervoltage detected!` during radio activity (`vcgencmd get_throttled` = `0x50000` means it happened since boot).
- A "wall socket" adapter wasn't enough either: it also negotiated only 3000 mA.
- Over I2C the card keeps working, but the Notehub session drops (§7) were seen during undervoltage events.
- **Fix before deploying:** the official 27 W 5 V/5 A Pi 5 supply (should read `5000`), or a separate supply for the Notecarrier.
  After the fix, `vcgencmd get_throttled` should read `0x0` after a reboot.

## 3. Notehub (cloud) setup

| | |
|---|---|
| Project UID | `app:45ea1319-9f3d-4738-9ee1-55e662440586` |
| Product UID | `com.gmail.chensonny46:delivery_robot` (the project belongs to the `chensonny46@gmail.com` Notehub account; ask them for access) |
| Notehub host | `a.notefile.net` (the card), `https://api.notefile.net` (REST API) |
| Web UI | https://notehub.io |

### API credentials

- **Use a personal access token:** Notehub → **user menu (top right) → API Access → Create New Token**. Send it as
  `Authorization: Bearer <token>`.
- The older OAuth client ID/secret is **deprecated** (project **Settings → OAuth**). `cloud_inject.py` still supports it as a fallback.
- **There is no "Programmatic API access" menu.** An early doc said so by mistake; don't go looking for it.
- The token controls the whole project: keep it server-side, never in a browser or phone app.
- **The API path accepts a product UID or a project UID** (`/v1/projects/{projectOrProductUID}/…`).

### `cellular_test/.env`

Gitignored and mode 600. `cloud_inject.py` and `tests/test_hardware.py` load it; real environment variables win.

```
NOTEHUB_API_KEY=<personal access token>
PROJECT_UID=app:45ea1319-9f3d-4738-9ee1-55e662440586
DEVICE_UID=dev:868531063312800
NOTEHUB_CLIENT_ID=          # deprecated alternative, only used if NOTEHUB_API_KEY is empty
NOTEHUB_CLIENT_SECRET=
```

When printing `.env` for debugging, **mask every secret line**. The API key leaked into a chat transcript once that way.

### Rate limits

Polling the Events API **once a second** got `HTTP 429 Too Many Requests`, and while it was limited the next **command POST failed too**:
the limit covers the whole token. Poll every 3 s or slower with backoff, or use an MQTT route. The Events API also once returned an
empty, non-JSON 200 response; treat that as "no events yet". Notehub's exact limits weren't measured.

## 4. Notecard configuration (what's set on the card)

Check with `hub.get`. Current values:

```json
{"mode": "continuous", "sync": true, "product": "com.gmail.chensonny46:delivery_robot", "host": "a.notefile.net"}
```

- **`hub.set {"mode":"continuous","sync":true}` is essential.** Without `sync:true`, inbound commands waited **more than 150 s**
  (the card only checks inbound on its periodic schedule). With it, Notehub pushes each new note right away: **1.5–2.8 s**.
  It costs a bit more power and data; the team decided speed matters more.
- The card stores `hub.set` settings. `receive_demo.py` re-applies it on every start (`NotecardLink.enable_immediate_sync()`), so
  a replacement or factory-reset card is covered. Re-applying it does **not** cause a reconnect (checked).
- `inbound`, `outbound` and `duration` aren't set. `duration` (at least 15 min) would make continuous mode end and restart the session on a schedule.
- **GPS:** `card.location.mode` is `periodic` every 60 s (probably the factory default). That costs power; turn it off or slow it down if we don't need it.
  Notehub adds cell-tower and triangulated location to every event anyway (`tower_lat`/`tri_lat` fields).
- **Clock:** `card.time` gives network time (and location/timezone). `receive_demo.py` uses it for staleness checks, because a robot
  on cellular only may have no NTP. The card clock matched the Pi's NTP clock within about 1.5 s.

## 5. Software

### Install

```bash
cd ~/testing/cellular_test
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # note-python, pyserial, python-periphery, paho-mqtt>=2.0, requests, pytest
```

Tested with Python 3.13.5 and note-python 2.5.1 / python-periphery 2.4.2.

### Files in `cellular_test/`

| File | What it is |
|---|---|
| `notecard_link.py` | `open_card()` (**the one place that picks I2C or serial**), `NotecardLink` wrapper: `send_note`, `receive_notes` (drains with `delete:true`), `sync`, `hub_status`, `wireless_status`, `version`, `now` (card clock), `enable_immediate_sync`. Run it directly for a health check. |
| `receive_demo.py` | **The robot-side receiver.** Polls `commands.qi` every 1 s, validates, checks staleness, dedupes, dispatches (`route`/`navigate`/`stop`/`ping`, **print only**), acks each command to `acks.qo`. Includes `SessionWatchdog`. |
| `send_demo.py` | Uplink test: one fake note to `telemetry.qo` + `hub.sync`, then watches `hub.sync.status`. |
| `cloud_inject.py` | Cloud side: POSTs a packet to `commands.qi` with the Notehub API (reads `.env`). No argument = a `ping`. |
| `mqtt_watch.py` | Prints events from the MQTT broker a Notehub outbound Route publishes to (`MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC`, …). |
| `tests/` | pytest: `fake_notecard.py` stands in for the card; `test_hardware.py` needs the real card (`RUN_HW=1`). |

### Running the receiver

```bash
cd ~/testing/cellular_test
.venv/bin/python receive_demo.py              # Ctrl-C to stop
.venv/bin/python receive_demo.py --once       # one check, then exit
.venv/bin/python receive_demo.py --no-ack     # don't reply (the app will time out)
.venv/bin/python receive_demo.py --interval 2 # check every 2 s
```

A healthy start looks like this:

```
card: dev:868531063312800  hub: connected (session open) {connected}
polling commands.qi every 1.0s (Ctrl-C to stop)
```

- **Run only one program that talks to the card at a time.** The receiver deletes commands as it reads them, and two
  programs sharing the I2C connection can interfere with each other.
- It stops when the terminal closes. Use `tmux`/`screen` for tests; the robot needs a systemd service (not done yet).
- Commands sent while it isn't running wait on the card or in Notehub, and are handled when it starts (subject to staleness).

### Quick manual tests

```bash
.venv/bin/python notecard_link.py        # card.version, hub.status, card.wireless
.venv/bin/python cloud_inject.py         # sends a ping; the receiver should print "pong"
.venv/bin/python cloud_inject.py '{"id":"t1","type":"navigate","body":{"lat":40.42,"lon":-86.91}}'
.venv/bin/python send_demo.py --seq 1    # uplink telemetry note
.venv/bin/pytest -q                      # 66 unit tests, no hardware
RUN_HW=1 .venv/bin/pytest -q tests/test_hardware.py   # 4 tests against the real card and Notehub
```

## 6. Command contract (summary)

Full rules and every error string are in [`APP_INTEGRATION.md`](cellular_test/APP_INTEGRATION.md). The app builds packets in
`web/lib/robot-packet.ts`; change both sides together.

```
POST https://api.notefile.net/v1/projects/{PROJECT_UID}/devices/{DEVICE_UID}/notes/commands.qi
Authorization: Bearer <token>
{"body": {"id": "…", "type": "route", "issuedAt": "2026-09-25T20:31:00.000Z", "body": {…}}}
```

| type | body | stale after | Pi does today |
|---|---|---|---|
| `route` | `destination {lat, lon}` (required), `profile`, `distanceMeters`, `durationSeconds`, `polyline` (GeoJSON **`[lon, lat]`**) | 600 s (`issuedAt` required) | validate + log, result `logged` |
| `navigate` | `lat`, `lon` | 60 s, only if `issuedAt` is given | log, `logged` |
| `stop` | none | never | log, `logged` |
| `ping` | none | never | `pong` |

- **Every command gets exactly one ack** in `acks.qo`: `{"id", "type", "ok": true, "result"}` or `{"id", "type", "ok": false, "error"}`.
  That includes malformed, unknown and stale commands.
- **Duplicate `id`s** (the last 1000, kept in memory) aren't acted on again; the ack repeats the first result with `"duplicate": true`.
- The HTTP 200 from the POST means **queued in Notehub**, not delivered.
- **Coordinate trap:** `destination` uses named `lat`/`lon`, but polyline points are `[lon, lat]`. Swapped Indiana coordinates are still
  valid numbers, so the Pi can't detect that mistake.
- An 11 KB, 400-point route arrived intact, so packet size isn't a problem at that scale.

## 7. Timings measured (2026-09-25, 1 bar indoors)

| Path | Time |
|---|---|
| POST → Pi receives `ping` (with `sync:true`) | 1.5–2.8 s |
| POST → ack visible in Events API (`navigate`) | 4.9 s |
| POST → ack visible (`route`, 3 points / 400 points) | 6.4–6.6 s / 6.1 s |
| POST → Pi receives, **without** `sync:true` | more than 150 s (then needed a manual `hub.sync`) |
| Forced `hub.sync` from a closed session (modem power cycle + reconnect) | about 90–100 s |
| Outbound `hub.sync` of a test note after a modem restart | about 2 min |

## 8. Known problems and lessons

1. **The Notehub session closes by itself and doesn't reopen.** `hub.status` goes from `connected (session open) {connected}` to
   `connected {connected-closed}`. While it's closed, **inbound push stops** and commands wait in Notehub. We saw it during a
   test (with undervoltage at the same time), and again later with nothing running. Cause unknown; Blues' `hub.set` docs don't describe this state.
   - **Mitigation:** `SessionWatchdog` in `receive_demo.py` checks every 15 s and forces `hub.sync` after 30 s closed, retrying every 2 min.
     It only works **while the receiver runs**, and a reconnect takes about 90 s.
   - **To try next:** fix power first, then see if drops continue; try `hub.set` `duration`; set `inbound` as a fallback; ask Blues
     (discuss.blues.io) what `{connected-closed}` means with `sync:true`.
2. **Power:** see §2. It's the root of the USB failure and the prime suspect for the session drops.
3. **Weak indoor signal (1 bar):** expect slower delivery in basements. Commands queue in Notehub, and `issuedAt` stops the robot from acting on old routes.
4. **Notehub API rate limit:** see §3.
5. **Credentials menu:** personal access token under the user menu, not "Programmatic API access".
6. **Shared I2C bus:** a BNO085 fault can jam the bus the Notecard is on (§2).
7. **Unit tests must not read the real `.env`:** `cloud_inject.ENV_FILE` is patchable for that. A test broke once because of this.

## 9. Troubleshooting

| Symptom | Check / fix |
|---|---|
| `i2cdetect -y 1` doesn't show `17` | Wiring (SDA pin 3, SCL pin 5, GND), Notecarrier powered, `dtparam=i2c_arm=on`. |
| `i2cdetect` hangs | Bus jammed (often the BNO085): `recover_bus()` in `imu.py`, or power-cycle. |
| `Permission denied` on `/dev/i2c-1` | Add the user to the `i2c` group, then log in again. |
| Commands take minutes to arrive | `hub.get` must show `"sync": true`; `hub.status` must show `(session open)`. If it shows `{connected-closed}`, run `hub.sync` (or keep the receiver running so the watchdog does it). |
| POST returns 200 but nothing arrives | Receiver not running, session closed, or no signal (`card.wireless` → `bars`, `rsrp`). The command waits in Notehub; look under the device's **Notes** / **Events** in the Notehub UI. |
| Command arrives but the ack says `stale` | `issuedAt` older than the limit, or no timezone in `issuedAt` (`…Z` is required). |
| `HTTP 401` from Notehub | Wrong or expired token, or `.env` not loaded (run from `cellular_test/`, or check the variable names). |
| `HTTP 429` from Notehub | Polling too fast; back off (§3). |
| `missing env vars: …` | Fill in `cellular_test/.env`. |
| USB: `hub.status` → `JSONDecodeError … line 2 column 1` | Brownout; use I2C or fix power. |
| `Undervoltage detected!` in `dmesg` | Supply only negotiated 3 A; get a 5 A supply (§2). |

Useful card requests (from Python: `NotecardLink(open_card()).request({...})`):
`card.version`, `hub.get`, `hub.status`, `hub.sync`, `hub.sync.status`, `card.wireless`, `card.time`, `card.voltage`,
`card.location.mode`, `note.changes {"file":"commands.qi"}` (peek without `delete` so nothing is consumed).

## 10. Still to do

- [ ] Proper power: a 5 V/5 A supply or a separate Notecarrier supply, then re-check whether session drops continue.
- [ ] Find the root cause of `{connected-closed}` (see §8.1).
- [ ] Notehub outbound **MQTT (or webhook) route** for `acks.qo` / `telemetry.qo`; setup steps in `cellular_test/README.md`. Not tested end to end.
- [ ] systemd service for `receive_demo.py` on the robot (start at boot, restart on crash).
- [ ] Real handlers: `route`/`navigate`/`stop` still only print. Connect to `local_planner.py` and motor control.
- [ ] Real telemetry instead of `send_demo.py`'s fake body.
- [ ] Decide on the GPS mode (periodic 60 s now).
- [ ] Remember the last handled ids across restarts (dedupe is memory-only).
- [ ] Rotate the Notehub token (it was exposed in a chat transcript).
- [ ] Commit `cellular_test/` (not in git yet; `.env` is ignored).

## 11. History

- **2026-09-25, session 1 (USB):** code and tests written; card over USB answered `card.version`, but `hub.status` failed from brownouts
  (`get_throttled` = `0x50005`, 32 USB reconnects). A wall adapter didn't help (still 3 A).
- **2026-09-25, session 2 (I2C):** rewired to I2C `0x17`, everything answered; switched `open_card()` to I2C; added `.env` and
  personal-access-token auth; found and fixed the >150 s inbound delay with `sync:true`; implemented the app team's `route`
  contract with staleness and dedupe; found the session drop (added the watchdog) and the API rate limit; wrote `APP_INTEGRATION.md` and this file.

## 12. References

- [Notehub API intro: personal access tokens, OAuth deprecated](https://dev.blues.io/api-reference/notehub-api/api-introduction/)
- [Notecard `hub` requests: `hub.set` `sync`, `duration`, `inbound`/`outbound`](https://dev.blues.io/api-reference/notecard-api/hub-requests/latest/)
- [Notecard error and status codes](https://dev.blues.io/notecard/notecard-walkthrough/notecard-error-and-status-codes/)
- [Routing data to cloud: MQTT](https://dev.blues.io/guides-and-tutorials/routing-data-to-cloud/mqtt/)
- [Notehub API reference](https://dev.blues.io/api-reference/notehub-api/)
- [Notehub walkthrough](https://dev.blues.io/notehub/notehub-walkthrough/)
- [Understanding Notecard penalty boxes](https://dev.blues.io/guides-and-tutorials/notecard-guides/understanding-notecard-penalty-boxes/) (why repeated failed connects can back off)
