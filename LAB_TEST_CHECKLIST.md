# Lab cellular test: resume checklist

Written 2026-10-05 so the work can pick up again after `sudo reboot`. Background and details are in `CELLULAR.md` (section 5,
"Unattended logging").

To read this from the Mac: `ssh robot cat testing/LAB_TEST_CHECKLIST.md`. Over Ethernet it's at `sdteam22@10.165.13.249`.
To pick up the Pi-side Claude session again (Ethernet still plugged in): `cd ~/testing && claude --continue`.

## Status at the time of writing

| Item | State |
|---|---|
| USB-C network (`setup_usb_gadget.sh`) | **Not working yet**, see "Update 2026-10-05 evening" below. Script fixed; re-run it with sudo. |
| Mac SSH key | Installed (`ssh-copy-id` done). `Host robot` → `192.168.77.1` is in the Mac's `~/.ssh/config`. |
| Logger auto-start | `@reboot` crontab line starts `cellular_logger.sh` 15 s after boot. |
| Control panel | `cellular_test/control_panel/` (`panel.py`, `index.html`). Runs **on the Mac**. Tested. |
| Mac Claude prompt | `cellular_test/control_panel/MAC_CLAUDE_PROMPT.md` |
| Notehub API key | New token saved on the Mac only. The Pi's `.env` still has the old one. |
| Notecard wiring | **Verified** after the reboot: `17` on the bus, card answers, hardware tests pass. |
| Git | Nothing committed. |

## Update 2026-10-05 evening (after the first reboot)

The Mac couldn't reach the Pi on USB (`ping 192.168.77.1` timed out, `ssh robot` hung). Checked from the Pi over Ethernet, it had
**two separate causes**:

1. **No USB data link.** `cat /sys/class/udc/*/state` said `not attached`, so the Pi never saw a USB host, although `g_ether` was
   loaded and bound. Likely causes: a **charge-only USB-C cable** (most likely), macOS blocking the accessory (look for an "Allow
   accessory to connect" prompt, or System Settings → Privacy & Security), or the Pi powered from something other than the Mac.
2. **NetworkManager ignored `usb0`** (`nmcli dev` showed `unmanaged`). Its stock rule `/usr/lib/udev/rules.d/85-nm-unmanaged.rules`
   marks every USB gadget interface unmanaged, so the `usb-gadget` profile never applied: no `192.168.77.1`, no DHCP for the Mac.
   **Fixed in `setup_usb_gadget.sh`**: it now also writes `/etc/udev/rules.d/86-usb-gadget-nm-managed.rules` (and `--uninstall`
   removes it). Not applied yet because it needs sudo.

To do, on the Pi over Ethernet (`ssh sdteam22@10.165.13.249`):

```bash
sudo bash ~/testing/setup_usb_gadget.sh   # safe to re-run; applies right away if usb0 exists, survives reboot
sudo reboot                               # optional, to confirm it all comes up by itself
```

Then, with a cable known to carry data, from the Mac to the Pi's USB-C port:

```bash
ping -c 3 192.168.77.1
```

On the Pi, the checks are:

```bash
cat /sys/class/udc/*/state     # "configured" = cable/Mac OK; "not attached" = cable or port problem
nmcli -t dev | grep usb0       # should say "connected:usb-gadget", not "unmanaged"
ip -br addr show usb0          # 192.168.77.1/24
```

Results from that session (over Ethernet):

| Check | Result |
|---|---|
| `pytest -q` (unit) | 67 passed, 4 skipped |
| `RUN_HW=1 pytest -q tests/test_hardware.py` | 4 passed |
| `i2cdetect -y 1` | `17` (Notecard) and `6a` present |
| `vcgencmd get_throttled` | `0x0` |
| Logger auto-start (`@reboot` cron) | Running in tmux `cellular`. Handled the leftovers: ping `65c38679` → `pong`, route `36112227` → `stale` |
| Cloud ping `d76d8716` (`cloud_inject.py`, sent from the Pi) | `pong`, but about **90 s** late: the session was `{connected-closed}` and the watchdog had to reopen it |

- **Session drops are still happening** (CELLULAR.md §8.1), even with `get_throttled` = `0x0`, so power isn't the only cause.
  Signal at the time: 1 bar, RSRP −105 to −110, SINR 2–10. Expect some commands to take about 90 s during the test.
- The Pi's old token in `.env` still worked for `cloud_inject.py`. If it's revoked, Pi-side injects fail (the Mac panel uses the new one).
- The test plan in section 6 hasn't been run yet; it needs the USB link.

## Update 2026-10-05, 20:36 (after the second reboot)

- The software side of USB-C is now done: the udev override is installed, `g_ether` is bound, and the `usb-gadget` profile exists.
  But `/sys/class/udc/*/state` still says `not attached` and `nmcli` shows `usb0` `unavailable`, so the Pi sees **no USB host
  on the data lines**. What's left is physical: the cable (use one known to carry data), the Mac's accessory prompt, or the Pi
  being powered from something other than the Mac.
- `get_throttled` = `0x50000` (undervoltage twice during boot, at 5 s and 13 s); the supply negotiated 3000 mA.
- `pytest -q`: 67 passed, 4 skipped. `RUN_HW=1 pytest tests/test_hardware.py`: 4 passed. `i2cdetect`: `17` and `6a` present.
- **Test plan step 1 (Ethernet baseline) done from the Pi** with `cloud_inject.py` in place of the Mac panel. Ids `lab-*-203705` and `lab-route-203823`:
  ping → `pong`, navigate/stop → `logged`, route → `logged`. All acks are in Notehub's `acks.qo`.
  The first batch took about 55 s because the session was `{connected-closed}` and the watchdog reopened it. With the session open, a route took about 3 s from POST to result.
  (`lab-route-203705` acked `ok:false` because I sent the polyline as a GeoJSON object instead of a bare array. That's correct behavior, not a bug.)
- Steps 2 (Ethernet unplugged) and 3 (upstairs) still need the USB link or the Mac panel.

## 1. Wire the Notecard (before or after reboot)

Pi 40-pin header:

| Notecarrier | Connects to | Pi pin |
|---|---|---|
| GND | Pi GND **and** the supply's − terminal (common ground) | **6** |
| SDA | Pi SDA (GPIO2) | **3** |
| SCL | Pi SCL (GPIO3) | **5** |
| VBAT | + terminal of the separate supply | none |

- **Supply:** at most about 5.5 V (confirm on the board's label or datasheet); 5 V or a 3.7 V LiPo is typical. It must handle short
  bursts of about 2 A.
- **One power source only:** don't also plug in the Notecarrier's USB port.
- **Never** feed VBAT from the Pi's 3.3 V pin. The Pi's 5 V pin (2 or 4) works in a pinch, but that caused undervoltage before.
- **Before connecting SDA/SCL to the Pi:** power the Notecarrier and measure SDA→GND and SCL→GND. Both should read about **3.3 V or
  less**. Near 5 V means don't connect: the Pi's pins are 3.3 V only.

## 2. Reboot, with Ethernet still plugged in as a safety net

```bash
sudo reboot
```

## 3. Check from the Mac

```bash
ping -c 3 192.168.77.1        # USB link up (click "Allow" if macOS asks about the accessory)
ssh robot                     # answer "yes" once; it should log in with no password
python3 --version             # the panel needs Python 3 (3.9+ is fine)
```

## 4. Check the Pi and the card (on the Pi, via `ssh robot`)

```bash
ip -br addr show usb0                         # should show 192.168.77.1/24
vcgencmd get_throttled                        # 0x0 = no undervoltage
tmux ls                                       # should list "cellular" (logger auto-started)
cd ~/testing/cellular_test
./cellular_logger.sh status                   # running + last log lines
```

If the log shows `Failed to reset Notecard`, the card isn't reachable. Check it with the logger stopped, since only one program may use
the card at a time:

```bash
./cellular_logger.sh stop
i2cdetect -y 1                                # must show 17
.venv/bin/python notecard_link.py             # card.version, hub.status, card.wireless
./cellular_logger.sh start
```

Healthy log lines:

```
card: dev:868531063312800  hub: connected (session open) {connected}
heartbeat: hub='connected (session open) {connected}' bars=1 ...   (every 60 s)
```

## 5. Start Claude on the Mac

Copy the prompt and paste it into Claude on the Mac:

```bash
ssh robot cat testing/cellular_test/control_panel/MAC_CLAUDE_PROMPT.md | pbcopy
```

It tells that Claude to:
- copy the panel to `~/robot-panel`;
- **ask you where the API key is** (it must never print the key);
- run `python3 ~/robot-panel/panel.py`, then you open **http://127.0.0.1:8765**.

## 6. Test plan

1. **Baseline (Ethernet still in):** Ping → expect "received" within a few seconds and the result `pong`. Then Navigate, Route and
   Stop, then "Check acks" once.
2. **Unplug Ethernet:** repeat step 1. It should behave the same.
3. **Upstairs:**
   - Unplugging from the Mac powers the Pi off. Plug back in, and the logger starts by itself about 15 s after boot.
   - The card may need a minute or two to connect.
   - Send about 10 pings, about 10 s apart. Compare delay, bars and RSRP to the basement: 1.5–3 s, 1 bar, RSRP −106 to −117 dBm.

## Viewing the log without the panel

```bash
ssh robot                                        # then:
cd ~/testing/cellular_test
./cellular_logger.sh view                        # live (Ctrl-C stops viewing, not logging)
less logs/cellular_log.txt                       # whole file
# copy it to the Mac (run on the Mac):
scp robot:testing/cellular_test/logs/cellular_log.txt .
```

Log times are UTC from the Notecard's clock. The Pi's own clock may be wrong without Ethernet.

## Expect these leftovers first

These test commands from setup are queued in Notehub and arrive once the card is online. They're not part of the test.
- pings `5a3494ee` and `65c38679`; `65c38679` was sent twice, so the second copy acks as a duplicate
- route `36112227`, which acks `stale`

## Undo or turn off

| What | How |
|---|---|
| USB-C networking | `sudo bash ~/testing/setup_usb_gadget.sh --uninstall`, then reboot |
| Logger auto-start | `crontab -e` and delete the `@reboot` line |
| Stop logging now | `~/testing/cellular_test/cellular_logger.sh stop` |
