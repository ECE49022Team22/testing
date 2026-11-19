# Taking deliveries from the web app: `follow.py --app`

Without `--app`, follow.py is unchanged (`line`, `route`, `local`, `teleop`) and never talks to the app.
With `--app` it connects to the Cosmo web app over HTTPS through the phone hotspot, and drives the legs the app sends.

## One program, started at boot

`robot_service.sh` runs `nav/follow.py --app`: sensors, driving, the control page on `:8100` and the link to the
web app, in one process. `setup_robot_service.sh` makes systemd start it at every boot and restart it if it ever stops.

```bash
cd ~/testing && git fetch && git checkout app-link && sudo bash setup_robot_service.sh   # once; asks for the token
```

- **Token:** the robot token (the same value as `ROBOT_API_TOKEN` in Vercel) goes in `~/.config/cosmo_robot.env`
  (mode 600, not in git). The setup script asks for it.
- **Flags:** `COSMO_FLAGS="..."` in the same file changes follow.py's flags. The defaults are
  `--avoid --speed 0.8 --no-video`. Add `--pivot-deg 0` if the wheel hubs still aren't secured.
- **Old autostart:** the script removes the `@reboot` crontab line for the Notecard logger (it backs up the crontab first).
- **Live output:** `journalctl -u cosmo-robot -f`. Each run's logs go to `nav/logs/follow_app_<time>_partNNN.json`,
  written every 5 min (`--log-every`), so nothing grows without bound and a power cut loses at most 5 min.
- **Restarts:** a delivery in progress is saved in `~/.local/state/cosmo_delivery.json`. After a crash or reboot it
  carries on with the same delivery, but driving is disabled again until someone enables it on the page.
- **Stopping:** `touch ~/motor_cal/STOP` stops the robot and keeps it stopped (the service waits) until you
  `rm ~/motor_cal/STOP`. `sudo systemctl stop cosmo-robot` stops the program. Do that before running anything
  else that uses the motors, GPS or LiDAR (`follow.py local`, the demo, `motor_cal`). Start it again with
  `sudo systemctl start cosmo-robot`. `sudo bash setup_robot_service.sh --uninstall` removes the service.
- **Control page:** at `http://<pi>:8100/`, also through Tailscale (`tailscale ip -4` on the Pi).

To run it by hand instead (service stopped):

```bash
.venv/bin/python nav/follow.py --app --avoid --speed 0.8
```

## Running a delivery

1. It polls the app every 3 s from the start, but **driving is disabled** at start.
2. Open the control page it prints (`http://<pi>:8100/`). Move the robot somewhere safe with the joystick (or by hand).
   It should face roughly along the first leg: it drives ~2 m straight to find its heading.
3. Tap **Driving disabled: tap to enable** (turns green), then **hold to run** as before. Both are needed to drive.
4. Order from the app. The robot drives to the pickup and waits at `AWAITING_LOAD`. The vendor's Unlock and Lock on
   the app send it to the destination. At `ARRIVED` the app emails the customer the code. The customer's Unlock and
   Lock complete the delivery (`COMPLETED`, then `IDLE`), and the app sends the next queued order.

Tap the green button again to disable driving at any time. The joystick works whether driving is enabled or not.

| flag | default | |
|---|---|---|
| `--app` | off | take deliveries from the app |
| `--app-url` | `https://cosmo-beryl.vercel.app` | e.g. `http://<laptop>:8200` for `fake_app.py` |
| `--app-token-file` | `~/.config/cosmo_robot.env` | or set `ROBOT_API_TOKEN` in the environment |
| `--link-timeout` | 60 s | no successful poll for this long while on a leg: stop until it's back (S9-1) |
| `--state-file` | `~/.local/state/cosmo_delivery.json` | the delivery in progress, kept across restarts |
| `--log-every` | 300 s | write the run log out in parts this often |
| `--max-s` | none with `--app` | time limit |

## How the link works (`app_link.py`)

The robot always calls the app (the hotspot can't take incoming connections). Every 3 s (the app's `pollSeconds`) it
does one exchange:

1. `GET /api/robot/inbox` returns the commands the app is waiting to have acked.
2. Each command is run by `delivery.py`, which gives back its ack.
3. `POST /api/robot/uplink` sends the acks, every change not yet delivered, and the robot's state and position now.

Nothing is lost when an exchange fails, with no retry logic needed:
- **Commands:** the app keeps sending a command until it gets the ack. `delivery.py` answers a repeat with the
  first answer (`duplicate: true`) without running it again.
- **Changes:** each state, lid or fault change waits in `delivery.outbox` until a POST succeeds. The outbox is
  saved to disk with the delivery, so changes even survive a restart.
- **Position:** the current state and position go out on every exchange (the app's live map, S10-2), so a lost one
  is replaced 3 s later.

**Connecting:** HTTPS with the system's certificates. On an IPv6-only hotspot without DNS64 the normal connection to
`*.vercel.app` (IPv4-only) fails. The link then connects to `64:ff9b::<IPv4>` (NAT64), still checking the certificate
for `cosmo-beryl.vercel.app`, the same way `ntrip_rtk.py` reaches the RTK caster.

## The rules (`delivery.py`)

- **Every command is acked.** A repeated `id` gets the first answer again.
- **Stale commands are refused:** a `delivery` older than 600 s, or an `unlock`/`lock` older than 60 s. The age is
  judged on the app's clock (`now` vs `issuedAt`), since the Pi has no RTC.
- **One job at a time:** a second `delivery` during a job is refused `busy…`.
- **Unlock** works only while stopped at the pickup or destination.
- **Lock** after the lid was opened at that stop moves the delivery on (7-2).
- **`route`** (the operator link test) is acked but not driven.
- **Faults:** stalled 4 times, stuck too often, or no STM32 telemetry. Instead of ending the run (as without
  `--app`), it reports `FAULT`, stops and disables driving. Re-enabling clears the fault.
- **Link loss** (S9-1): stopped while the last good exchange is older than `--link-timeout`. The compartment stays
  locked. It carries on once an exchange succeeds again.
- **Stops:** the `STOP` file and Ctrl-C still end the run.

## Checking the link with the real app (before the robot drives)

Run these on the Pi, connected to the hotspot, with the robot's program stopped (`sudo systemctl stop cosmo-robot`):

```bash
python3 nav/app_check.py check      # read-only: DNS, direct / NAT64 connection, token, what the inbox returns
python3 nav/app_check.py pretend    # be the robot with no hardware: order in the app and watch the whole delivery
```

- **`check`** must end with `Link OK.`. A `401` means the token differs from Vercel's.
- **`pretend`** runs the real `delivery.py` + `app_link.py`. Each leg "drives" in 20 s (`--leg-s`), moving the
  reported position along the route. Do a whole delivery from the app: order, vendor Unlock/Lock, wait for the email,
  customer code, Unlock/Lock. Check the next order is dispatched.
- Both also work on a laptop: copy the token file there, or pass `--token-file`.

## Not done yet

- **Latch:** `delivery.Lid` is a placeholder. It only prints, because the STM32 firmware has no latch command yet
  (11-4/11-5). Swap in the STM32 command and its reported latch state there.
- **STM32 command watchdog** (4-3): still missing in the firmware. If the Pi dies, the motors keep their last target.

## Testing without the robot or the app

```bash
python3 -m pytest nav/tests -q                                       # rules + link incl. HTTPS and NAT64 (~6 s)
python3 nav/sim_follow_harness.py clear --app --avoid --length 24    # whole delivery in the simulator (~90 s)
python3 nav/sim_follow_harness.py clear --app --restart --length 24  # ... with follow.py restarted mid-leg
python3 nav/fake_app.py --token test                                 # stand-in app on :8200
```

The tests check:
- a failed POST loses nothing;
- the certificate is still verified through the NAT64 fallback;
- a wrong token shows as `401`.

The harness checks:
- the robot doesn't move before driving is enabled, even with a delivery waiting;
- it stops within 0.1–0.3 m of the pickup and the destination;
- an unlock sent while driving is refused;
- a link outage stops it until the link is back;
- with `--restart`, it resumes the same delivery and doesn't move until re-enabled.
