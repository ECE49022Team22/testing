# Notecard continuous session won't reopen (2026-10-05/06)

Open issue from the session on the evening of 2026-10-05 EDT (2026-10-06 UTC). See CELLULAR.md for the full cellular setup.

## Status when we stopped

- Receiver running under `cellular_test/cellular_logger.sh` (tmux session `cellular`), log in `cellular_test/logs/cellular_log.txt`.
  `./watch_log.sh --open` opens the live log window on the Pi desktop.
- Card is stuck at `hub.status` = `connected {connected-closed}`. Commands sent from the app wait in Notehub until a sync happens,
  so latency is 35 s to minutes instead of 1.5–3 s.
- Forum post below is drafted but **not posted yet** (discuss.blues.io, Notecard category).

## What we found

1. **I2C crashes were power.** Notecarrier VBAT was on a bench supply at 3.7 V. About 30–45 s after each forced `hub.sync`
   (modem power-up, up to 2 A), the kernel logged `i2c_dw_handle_tx_abort: SDA stuck at low` and the receiver crashed with
   `Failed to reset Notecard`. No IMU or GPS was connected, so the card side was holding SDA low. Raising the supply to
   **4.2 V** stopped the jams (`card.voltage` now reads about 4.4 V). Don't go above 4.2 V on VBAT (it's the LiPo input).
2. **Code reads the card fine.** The one `JSONDecodeError` crash (01:54:40Z) was a second process talking to the card at the
   same time as the receiver. Stop the receiver (`./cellular_logger.sh stop`) before running any other card query.
3. **Session problem.** Card settings are correct (`hub.get`: continuous, `sync:true`; firmware 11.3.1.17696; AT&T LTE, 2 bars).
   Notehub session history (`GET /v1/projects/{PROJECT_UID}/devices/{DEVICE_UID}/sessions`):
   - Before the brownouts: continuous sessions of 18 and 31 min, push worked.
   - Since then: only 3–8 s "first sync" sessions closed by the notecard; none continuous.
   - None of these reopened it: `hub.sync`, `hub.sync` with `allow:true`, `hub.set` periodic then back to continuous,
     `card.restart`. After `card.restart` it connected in about 45 s, did one first-sync, then sat in `{connected-closed}` again.
   - `hub.sync.status`: `connected {connected-closed} {transport}`, mode `{modem-on}`; `hub.sync` stays "requested" with no new Notehub session.
   - SIM data is fine (144 KB of 500 MB), device not disabled.

## Next steps

1. Check whether the session reopened by itself now that power is stable: look for `(session open)` in the log heartbeats.
2. Post the forum question below and follow up on the answer.
3. Revisit `SessionWatchdog` in `receive_demo.py`: it forces `hub.sync` every 2 min, each one restarts the modem (about 90 s),
   and right now the syncs aren't reopening the session, so it may be getting in the way.
4. Still open from CELLULAR.md: proper Pi power (27 W 5 V/5 A supply; `vcgencmd get_throttled` showed `0x50000`).

## Forum post draft

Leave out ICCID, IMSI, IMEI and the product UID (it contains a Gmail address).

**Title:** Continuous session won't reopen after brownouts (stuck at connected-closed)

```
Hi all,

I've got a Notecard (NOTE-MBGLW, firmware 11.3.1.17696) on a Notecarrier X v1.2, talking to a Raspberry Pi 5 over I2C. hub.set is mode continuous with sync:true, so commands we add to commands.qi from the Notehub API show up in a couple seconds. That was working fine earlier today, sessions were staying open 20-30 min at a time.

Then I had power problems. The card was on a bench supply at 3.7V on VBAT and it was sagging when the radio kicked on, so the card kept resetting (and jamming the Pi's I2C bus each time). I bumped the supply to 4.2V and the resets stopped, but now the card won't go back to a continuous session.

hub.status just sits at "connected {connected-closed}" and hub.sync.status says "connected {connected-closed} {transport}" with mode {modem-on}. Signal is fine (AT&T LTE, 2 bars, SINR around 14). In Notehub I only see short "first sync" sessions, like 3-8 seconds, closed by the notecard, nothing marked continuous.

Things I tried:
- hub.sync: shows as requested, but nothing shows up in Notehub
- hub.sync with allow:true: same
- switching hub.set to periodic and back to continuous: no change
- card.restart: connects in about 45s, does one quick first sync, then goes right back to connected-closed

So a few questions:
- What does {connected-closed} {transport} actually mean when you're in continuous mode?
- Could the card be in some kind of backoff after all the resets? Is there a way to check or clear that?
- Is there a better way to recover the session from the host than card.restart?
- For getting commands down in a few seconds, is continuous + sync:true the right setup, or should I be using something else?

Thanks!
```
