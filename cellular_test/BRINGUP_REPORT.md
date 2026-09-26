# Notecard cellular bring-up report — 2026-09-25

**Status (end of day): working over I2C.** App → Notehub → Notecard → Pi → ack takes about 5–6.5 s, including the app team's
`route` command. `pytest`: 66 passed, 4 hardware tests skipped; with `RUN_HW=1` all 4 hardware tests pass.
The contract for the app team is in [`APP_INTEGRATION.md`](APP_INTEGRATION.md).

Part A is the second session (I2C, working). Part B is the original USB attempt, kept as history.

# Part A: I2C, app integration

## A1. Rewired to I2C

The Notecarrier was moved from USB to the Pi's I2C bus (pin 3 SDA, pin 5 SCL). `i2cdetect -y 1` shows the card at `0x17`.
`open_card()` in `notecard_link.py` now returns `open_i2c()`.

- `card.version`, `hub.status` and `card.wireless` all answer: AT&T LTE band 2, 1 bar, RSRP −110 to −117 dBm.
- A test note to `i2c_test.qo` plus `hub.sync` completed.
- **Power is still short.** The PSU negotiates 3000 mA and the Pi logs `Undervoltage detected!` during radio bursts. Over I2C
  the card no longer resets (the USB resets were the Part B failure), but a 5 V/5 A supply or a separate Notecarrier supply is still needed.

## A2. Notehub credentials

- `cellular_test/.env` (gitignored, mode 600) holds `NOTEHUB_API_KEY`, `PROJECT_UID` and `DEVICE_UID`. `cloud_inject.py` loads it
  (`load_env_file()`); real environment variables win.
- Notehub has no "Programmatic API access" menu. The recommended credential is a **personal access token**
  (user menu → API Access). Client ID/secret still works but is deprecated (project Settings → OAuth). `cloud_inject.access_token()`
  uses the API key if it's set, otherwise OAuth.
- The hardware test `test_notehub_token` now does a read-only `GET …/devices/{DEVICE_UID}` with the key (HTTP 200).

## A3. Downlink latency: more than 150 s → about 2 s

- The first `cloud_inject.py` ping was queued (HTTP 200) but didn't reach the Pi in 150 s. The card was in `continuous` mode
  without `sync:true`, so it only picked up inbound notes on its periodic check. A manual `hub.sync` delivered it.
- `hub.set {"mode":"continuous","sync":true}` → pings arrive in **1.5 s, 1.5 s and 2.8 s**; `navigate` round trip with ack in the
  Events API: **4.9 s**. The card stores the setting; `receive_demo.py` re-applies it on start (`enable_immediate_sync()`).
- Default poll interval of `receive_demo.py` lowered from 5 s to 1 s (reading the card over I2C costs no radio time).

## A4. `route` command from the app team

Implemented in `receive_demo.py` to the app team's spec (see `APP_INTEGRATION.md`):

- **`route` handler:** validates `body.destination.lat/lon` and the optional `polyline` (GeoJSON `[lon, lat]`), and logs
  profile, distance, duration and polyline point count, start and end. Print only.
- **Staleness:** `route` must have `issuedAt` and is `stale` after 600 s; `navigate` is checked (60 s) only if `issuedAt` is given.
  "now" comes from the Notecard's network clock (`card.time`), falling back to the Pi clock.
- **Dedupe:** the last 1000 ids are kept in memory; a repeat isn't acted on but is acked again with `"duplicate": true`.
- **Every command is acked**, including malformed, unknown, stale and duplicate ones.

Tested against the real card:

| Test | Result |
|---|---|
| App team's own mock route (13 points), already waiting on the card | handled about 5.5 min after `issuedAt` (under the 10 min limit), `ok: true` |
| 400-point route, 11 KB packet | arrived intact; ack in Events API after **6.1 s** |
| Same 3-point route sent twice | acted on once; 2 acks, the second with `duplicate: true`; each after about 6.5 s |

## A5. Problems found

1. **Notehub session dropped.** Once, `hub.status` went to `connected {connected-closed}` and stayed there. A command sent then
   (the 400-point route) was not pushed, and it arrived only after a manual `hub.sync`, which power-cycled the modem (about 90 s).
   It happened during Pi undervoltage events, but the cause isn't proven, and Blues' `hub.set` docs don't describe what the card
   does when a session closes. Mitigation: `SessionWatchdog` in `receive_demo.py` forces `hub.sync` after 30 s closed, retrying every 2 min.
   Re-sending `hub.set` was checked and does **not** cause a reconnect.
2. **Notehub API rate limit.** Test polling of the Events API once a second led to `HTTP 429 Too Many Requests`, which also
   blocked the next command POST (the limit is per token). The app should poll every 3 s or slower with backoff, or use an MQTT route.
   The Events API also once returned an empty non-JSON 200; handle it as "no events yet".
3. **Token exposure.** A tool output in this session printed `NOTEHUB_API_KEY` in full into the assistant transcript (it didn't
   leave the Pi otherwise). Rotate the token in Notehub → API Access if that matters.

## A6. Not done yet

- A Notehub outbound MQTT (or webhook) route for `acks.qo` / `telemetry.qo`, which isn't tested end to end.
- Actual motion: handlers still only print.
- A proper power supply.
- Git: `cellular_test/` is still uncommitted.

# Part B: original USB attempt (history)

The code is written and `pytest` passes with no hardware (41 passed, 4 hardware tests skipped).
The Pi can talk to the card, but `hub.status` never succeeds because the Pi is short on power, and the round trip was not run.

## B1. Talking to the card

**`card.version` works**, and the card matches the expected device:

```
{"version": "notecard-11.3.1.17696", "device": "dev:868531063312800", "sku": "NOTE-MBGLW", "cell": true, "wifi": true, "gps": true, ...}
```

**`hub.status` fails every time** with `JSONDecodeError: Expecting value: line 2 column 1`.
The card sends back an empty line because it restarts in the middle of the reply. The cause is power:

- `vcgencmd get_throttled` reports `0x50005`, meaning the Pi is undervolted and throttled right now.
- The kernel log keeps printing `Undervoltage detected!`, and the Notecard's USB connection has dropped and reconnected 32 times since boot.

**The cellular radio pulls more current than the Pi's USB port can give.** On a Pi 5 without the official 5V/5A power supply,
the USB ports are capped at 600 mA total. Any of these should fix it:

- the official 27 W Pi 5 supply
- a powered USB hub
- a separate supply for the Notecarrier

After the fix, `vcgencmd get_throttled` should read `0x0`.

## B2. Tests

```
41 passed, 4 skipped in 0.14s
```

The tests were run and seen failing before the code was written. They cover:

- **`send_note`:** it builds the right `note.add` request (file, body, sync flag).
- **`receive_notes`:** it parses notes (oldest first) and handles an empty queue, `{note-noexist}` and other errors.
- **Command handling:** valid commands, and 9 kinds of malformed command.
- **Replies and the other scripts:** replies sent to `acks.qo`, plus the REST calls and MQTT output formatting.

The 4 skipped tests need the real card or the network and only run with `RUN_HW=1`.

## B3. Round trip

**Not run, so there is no output to show.** Besides the power problem:

- `NOTEHUB_CLIENT_ID`, `NOTEHUB_CLIENT_SECRET`, `PROJECT_UID` and `DEVICE_UID` are not set.
- No Notehub outbound MQTT Route has been created yet.

`README.md` has the exact commands for when those are ready.

## Downlink over MQTT isn't possible

Notehub has no inbound MQTT API. Its API reference lists only REST APIs, and its guide names only the Notehub UI and
the REST API for sending data to a card. MQTT exists only as an outbound Route.
`README.md` says this instead of making up an endpoint. It also describes a workaround: a small script that listens on your
own broker and makes the same REST call that `cloud_inject.py` makes.

## Where things are

- **Folder:** everything is in `cellular_test/`, with its own `.venv` so the existing one isn't touched.
  The command handlers only print; nothing touches motors.
- **Switching to I2C:** done in Part A.
- **Git:** nothing is committed yet.
- **One oddity:** the card shows up on USB as "Blues Inc — Cygnet Test App" (30a4:0003). It still answers as a Notecard,
  but mention it if Blues support ever asks.

## Sources

- [Routing Data to Cloud: MQTT](https://dev.blues.io/guides-and-tutorials/routing-data-to-cloud/mqtt/)
- [Notehub API intro (personal access tokens; OAuth deprecated)](https://dev.blues.io/api-reference/notehub-api/api-introduction/)
- [Notecard `hub` requests (`hub.set` `sync`, `duration`)](https://dev.blues.io/api-reference/notecard-api/hub-requests/latest/)
- [Using the Notehub API](https://dev.blues.io/guides-and-tutorials/using-the-notehub-api/)
- [Notehub API reference](https://dev.blues.io/api-reference/notehub-api/)
- [Notehub walkthrough](https://dev.blues.io/notehub/notehub-walkthrough/)
