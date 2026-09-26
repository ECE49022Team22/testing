# App ↔ robot over the Notecard: integration contract

How the web app sends commands to the robot through Notehub and the Blues Notecard, and how the Raspberry Pi
replies. This is the contract between the app team and the robot/cellular team. The Pi side is implemented in
`receive_demo.py` and tested against the real card (2026-09-25).

## Flow

```
Web app ──HTTPS POST──▶ Notehub ──LTE──▶ Notecard ──I2C──▶ Raspberry Pi (receive_demo.py)
        (commands.qi)                                       │ validates, dedupes, handles
Web app ◀── Events API / MQTT route ◀── Notehub ◀──LTE── Notecard ◀─┘ (acks.qo)
```

| | |
|---|---|
| Project UID | `app:45ea1319-9f3d-4738-9ee1-55e662440586` |
| Product UID | `com.gmail.chensonny46:delivery_robot` |
| Device UID | `dev:868531063312800` |
| Notecard | NOTE-MBGLW, firmware 11.3.1, AT&T LTE, on the Pi's I2C bus (`/dev/i2c-1`, address `0x17`) |

- **Downlink is HTTP only.** The Notecard is not a modem and has no MQTT. The app POSTs a note to the `commands.qi`
  notefile through the Notehub REST API. Notehub has no inbound MQTT; its MQTT routes are outbound only.
- **Uplink** (acks, telemetry): the app polls the Events API, or Notehub pushes events through a Route.

## Sending a command

```
POST https://api.notefile.net/v1/projects/{PROJECT_UID}/devices/{DEVICE_UID}/notes/commands.qi
Authorization: Bearer <Notehub personal access token>
Content-Type: application/json

{"body": <packet>}
```

- **Success:** HTTP 200 `{}` only means Notehub **queued** the command, not that the robot has it.
- **Token:** Notehub → user menu (top right) → **API Access** → Create New Token.
  Keep it on the server (`NOTEHUB_TOKEN` in `web/.env.local`). Never ship it to a browser or phone: it controls the whole project.

### Packet fields (all commands)

| Field | Required | Rule |
|---|---|---|
| `id` | yes | Non-empty string, unique per command. Used to match the ack and to dedupe. |
| `type` | yes | `route`, `navigate`, `stop` or `ping`. |
| `issuedAt` | `route`: yes; `navigate`: optional | UTC ISO-8601 **with a timezone**, e.g. `2026-09-25T20:31:00.000Z`. |
| `body` | depends on type | Must be a JSON object if present. |

### `route`

Built by the app in `web/lib/robot-packet.ts` (`buildRoutePacket`). Change both sides together.

```jsonc
{
  "id": "b7f3…",
  "type": "route",
  "issuedAt": "2026-09-25T20:31:00.000Z",
  "body": {
    "destination": { "lat": 40.4270, "lon": -86.9135 },   // required, numbers
    "profile": "foot-walking",                             // or "wheelchair" (logged only)
    "distanceMeters": 812,                                  // logged only
    "durationSeconds": 585,                                 // logged only
    "polyline": [ [-86.9194, 40.4283], [-86.9160, 40.4278], … ]   // optional, GeoJSON [lon, lat]
  }
}
```

**Coordinate order:** `destination` uses named `lat`/`lon`, but `polyline` points are **`[lon, lat]`** (longitude first),
as OpenRouteService returns them. The Pi reads them that way and rejects points outside ±180 / ±90.
Swapped Indiana coordinates (`[40.4, -86.9]`) are still in range, so the Pi can't catch that mistake for you.

**What the Pi does today:** it validates the packet and logs the destination, profile, distance, duration and the polyline's
point count, first point and last point. It doesn't move the robot yet (path following is future work), and it answers `"result": "logged"`.

### `navigate`, `stop`, `ping`

Unchanged: `navigate` takes `body.lat` / `body.lon`; `stop` and `ping` take no body. `ping` answers `"result": "pong"`.

## Acks (robot → app)

Every note the Pi reads from `commands.qi` gets exactly one ack in `acks.qo`, including malformed, unknown, stale and duplicate commands.
Nothing is dropped silently.

```jsonc
{ "id": "b7f3…", "type": "route", "ok": true,  "result": "logged" }
{ "id": "b7f3…", "type": "route", "ok": true,  "result": "logged", "duplicate": true }   // same id seen again
{ "id": "b7f3…", "type": "route", "ok": false, "error": "stale" }
{ "id": "…",     "type": "fly",   "ok": false, "error": "unknown type 'fly'" }
{ "id": null,                     "ok": false, "error": "missing 'id' (non-empty string)" }
```

### Error strings

| `error` | Cause |
|---|---|
| `command is not a JSON object` | The note body isn't an object. |
| `missing 'id' (non-empty string)` | No usable `id`, so the ack has `"id": null` and the app can't match it. |
| `missing 'type' (non-empty string)` | |
| `'body' must be an object` | |
| `unknown type '<type>'` | |
| `missing 'issuedAt'` | `route` without `issuedAt`. |
| `invalid 'issuedAt' (want UTC ISO-8601)` | Can't be parsed, or has no timezone (`…T20:31:00` without `Z` is rejected). |
| `stale` | Too old; see below. Not acted on. |
| `handler failed: <reason>` | Bad payload, e.g. `body.destination must be an object with lat/lon`, `destination.lat must be a number`, `destination lat/lon out of range`, `polyline must be a list of [lon, lat] pairs`, `polyline point out of range (expected [lon, lat])`. |

### Staleness

`now - issuedAt` is checked against:

| type | max age |
|---|---|
| `route` | 600 s (10 min) |
| `navigate` | 60 s, only when `issuedAt` is present |
| `stop`, `ping` | never stale |

"now" comes from the **Notecard's network clock** (`card.time`) and falls back to the Pi clock, so it's correct even if the
robot can't reach NTP. The limits are `MAX_AGE_SECONDS` in `receive_demo.py`. A command dated in the future counts as fresh.

### Duplicates

The Pi remembers the last 1000 `id`s it handled (in memory, cleared when it restarts). A repeated `id` is **not acted on again**,
but it is acked again with the first result plus `"duplicate": true`. Keep ids unique; don't reuse one for a new command.

### Reading acks

1. **Events API polling** (what the app does today, `web/lib/notehub-client.ts` `pollAck`):
   `GET /v1/projects/{PROJECT_UID}/events?deviceUID={DEVICE_UID}&files=acks.qo&sortOrder=desc&pageSize=10`,
   then look for an event whose `body.id` matches.
   **Poll every 3 s or slower, and back off on HTTP 429.** During testing, polling once a second (on top of a few minutes of
   earlier test calls) got the token rate-limited (`429 Too Many Requests`), and while it was limited **the next command POST failed too**:
   the limit covers the whole token, not just the Events endpoint. Notehub's exact limits weren't measured.
   The Events API also once returned an empty, non-JSON 200 response; treat that as "no events yet" and retry.
2. **Outbound MQTT route** (recommended for production). Notehub publishes each `acks.qo` / `telemetry.qo` event to your broker
   and the app consumes it with `web/lib/mqtt.ts`. It costs the device nothing extra, since the Notecard uploads each
   `.qo` note either way. Setup steps are in `README.md`. **Not tested end to end yet.**

## Measured timing (2026-09-25, 1-bar AT&T LTE, RSRP about −110 to −117 dBm)

| Path | Time |
|---|---|
| POST → Pi receives `ping` | 1.5–2.8 s |
| POST → ack visible in Events API (`navigate`) | 4.9 s |
| POST → ack visible in Events API (`route`, 3 points) | 6.4–6.6 s |
| POST → ack visible in Events API (`route`, 400-point polyline, 11 KB) | 6.1 s |
| Before `hub.set sync:true` | more than 150 s (commands waited for the card's periodic inbound check) |

The polling in these measurements added up to 3 s. Large packets are fine: an 11 KB, 400-point route arrived intact.

## Known risks

- **The session to Notehub can drop.** Fast delivery needs the card's Notehub session to be open
  (`hub.status` = `connected (session open) {connected}`). On 2026-09-25 it dropped once to `connected {connected-closed}` and
  didn't reopen by itself, so commands would have waited in Notehub. `receive_demo.py` now has a watchdog: if the
  session stays closed for 30 s it forces a `hub.sync`, retrying every 2 min. **A reconnect takes about 90 s** (modem power cycle),
  so expect roughly 2 min of delay in that case. The cause isn't proven; it happened while the Pi was logging undervoltage (see below).
- **Power:** the Pi's supply only negotiates 3 A, and the Pi logs `Undervoltage detected!` during radio bursts.
  Over I2C the card keeps working, but the robot needs a 5 V/5 A supply or a separate supply for the Notecarrier.
- **Weak signal:** 1 bar indoors. Weaker coverage means slower or delayed delivery. Commands wait in Notehub and arrive
  when the robot reconnects, and `issuedAt` keeps it from acting on old routes.
- **Commands are consumed on read** (`note.changes` with `delete:true`); several pending notes are handled oldest first.

## Testing end to end

1. App: `cd web`, set `NOTEHUB_TOKEN` in `.env.local`, `npm run dev`.
2. Pi: `cd cellular_test && .venv/bin/python receive_demo.py` (applies `hub.set {"mode":"continuous","sync":true}` on start, polls every 1 s).
3. App: `python scripts/notehub_send_mock.py`, which sends a mock route and prints the round trip.
4. Pi only, without the app: `.venv/bin/python cloud_inject.py '<packet json>'` sends any packet using `cellular_test/.env`.
