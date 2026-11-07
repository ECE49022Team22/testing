# Autonomous navigation: route planning and path following

Status on 2026-11-07: **straight-line following works** (10 m, ±0.4° heading swing, ~5 mm estimated off-line,
no GPS), and so does **a dog-leg path** (1 m, √2 m at 45°, 2 m) once the rear wheels were taped: worst 0.21 m off
the path, ending −0.9° to the final leg. Following a route by GPS does **not** work near buildings yet, because RTK float wanders by metres
there. Code: [`follow.py`](follow.py) (follower), [`route_map.py`](route_map.py) (map plot).
Logs from the six test runs are in [`logs/`](logs/).

---

## 1. Quick start

Stop the demo first: the follower uses the motors, the GPS port and the LiDAR. Then, from the repo root:

```bash
.venv/bin/python nav/follow.py line --length 10 --lookahead 3 --no-gps     # proven: straight line, wheels + gyro
.venv/bin/python nav/follow.py line --length 10 --lookahead 3 --gps-gain 0  # line direction from GPS, then wheels + gyro
.venv/bin/python nav/follow.py local --points "0,0 1,0 2,1 4,1" --side right --speed 0.15 --lookahead 1.25
                                            # proven: dog-leg, points in m from the start pose (x ahead, y left)
.venv/bin/python nav/follow.py route nav/route_lmbs_points.json --lookahead 3   # not ready: GPS too poor near buildings
```

`.venv/bin/python nav/follow.py teleop` just drives by hand (no path).

It prints a **control page**, `http://<pi>:8100/`, with a HOLD TO RUN button (autonomous), an on-screen **joystick**
(manual driving, up to `--tele-speed` 0.5 m/s and `--tele-turn` 1 rad/s, spinning in place allowed; let go and it stops
within 0.5 s; it overrides autonomy while used; the LiDAR still blocks driving forward into things) and **Restart path
from here** (re-anchors a `local` path / `--no-gps` line to the robot's current pose at the next hold). Open it on a phone on the same network and hold the big button.
The robot moves **only while the button is held**, and stops within ~0.5 s of letting go, of the page being hidden,
or of the network dropping. With the phone hotspot giving only IPv6, the address is `http://[<pi IPv6>]:8100/`.

- **`--no-gps` line and `local` path:** the path starts from wherever the robot points **the first time the button is
  pressed**, so position it before pressing. `local` never uses GPS. `--side right` mirrors its points.
- **GPS modes:** they wait for RTK float or fixed (about a minute after a restart). The RTK client starts
  automatically. Without an IPv4 route it reaches the caster through NAT64 (`64:ff9b::108.59.49.226`).
- **Onboard video:** the robot's camera (mounted upside down, so rotated 180°) records from the first hold or joystick
  use, with the run status drawn on each frame, to `logs/follow_<mode>_<time>.mp4` (H.264). Videos are not committed
  (10-20 MB each); they stay on the Pi. `--no-video` turns it off.
- **Stop file:** `touch ~/motor_cal/STOP` ends a run. Every run writes `logs/follow_<mode>_<time>.json` plus
  `_route.json` and `_track.json`.

## 2. Safety

| Layer | What it does |
|---|---|
| Hold-to-run page | Moves only while held. The page renews every 200 ms, and the robot pauses if nothing arrives for 0.6 s |
| LiDAR, path corridor | Stops if anything is within `--stop-m` (0.8 m) in a corridor `--half-width` (0.45 m) each side of the path ahead. Half speed within `--slow-m` (2 m) |
| LiDAR, all round | Stops if anything is within `--near-m` (0.25 m) in any direction. Chassis returns under 15 cm are ignored |
| LiDAR quiet | Pauses if no scan arrives for 0.5 s |
| GPS (GPS modes) | Pauses if the fix isn't RTK float/fixed or is over 1 s old |
| Motors | A stall fault is cleared and paused 1 s. The run ends after 4 stalls |
| Limits | `--max-s` time limit, `~/motor_cal/STOP` |

It resumes on its own once a pause clears, as long as the button is held. Walk ~1 m to the side: 0.25 m is
deliberately small so a person beside it doesn't stop it.

## 3. How it works

- **Position (fused):** dead-reckoned from wheel speed (encoders, ×0.94 effective wheel size from the LiDAR
  calibration in `motor_cal`) and the gyro heading. Each GPS fix pulls it by a gain (RTK fixed 0.10, float 0.05,
  plain GPS 0.01 per 5 Hz fix, scaled by `--gps-gain`). Fixes more than 1.5 m away are ignored unless 15 in a row
  agree. Fixes that jump more than 0.5 m (beyond what 2.5 m/s allows) are dropped.
- **Heading:** the IMU gyro (BNO085, z up, left turn positive) gives the turn. Its bias is measured at start and
  re-estimated whenever the robot stands still. The absolute heading in GPS modes comes from a least-squares line
  through the RTK points of the first `--init-m` (2 m) of straight driving. The measurement restarts if RTK drops or
  the position jumps. Later course corrections from the GPS track are used **only with RTK fixed**. The IMU compass
  isn't used: it's unreliable next to the motors.
- **Steering:** pure pursuit to the point `--lookahead` ahead on the path gives the curvature, capped at
  `--min-radius` (1 m). Past the path's end the target continues along the last segment (`Path.at_extended`), so
  the robot lines up with the final leg instead of aiming at the end point. The turn rate goes through the skid-steer model (effective track 0.95 m from `motor_cal`)
  with a gyro yaw-rate PI. **No pivots:** speed never drops below `--min-speed` (0.15 m/s) while moving, and the
  inner wheel stays above `--inner-min` (30%) of the outer. Slow, tight turns pivot on the inner wheel, which stalls
  on this chassis. A wheel target is never exactly 0, because the firmware then switches that motor off and it
  freewheels.
- **Wheel mapping:** left wheel = STM32 motor 2, right = motor 1 reversed (`motor_cal/robot_drive.py`).

## 4. Route planning

`route_lmbs_points.json` is a pedestrian route from the BHEE courtyard to Lambertus Hall (LMBS), from the
[Valhalla](https://valhalla1.openstreetmap.de) router on OpenStreetMap data: **146 m**, four legs along walkways
(north-east 9 m, right 40 m, right 37 m, left 60 m between Lambertus and Knoy). LMBS is at 40.427588, −86.911645
(OSM building "Lambertus Hall (LMBS)"; OSM's address points for 363 N Grant St are wrong). `route_lmbs.png` draws it:

```bash
.venv/bin/python nav/route_map.py nav/route_lmbs_points.json nav/route_lmbs.png \
    --mark "robot" 40.428589 -86.911542 --mark "LMBS" 40.4275884 -86.9116446
```

Map tiles are cached in `nav/tiles/` (not committed). Map data © OpenStreetMap contributors.

## 5. Test runs, 2026-11-07

All runs were on the walkway beside BHEE, 10 m line, 0.3 m/s, RTK float, robot on its wheels.

| Run | Log | Setup | Result | What it showed |
|---|---|---|---|---|
| 1 | `171145` | GPS steering, look-ahead 1.5 m | **Stall fault**, ~0 progress | A 5 m GPS jump (RTK float to GPS) went into the heading: 75° vs ~31° real. Steering hard at 0.06 m/s pivoted on the inner wheel, which stalled |
| 2 | `171618` | + jump rejection, line-fit heading, no-pivot limits, stall recovery | Ran off the walkway (stopped by hand) | GPS track straight (44°) while the wheels (R 30.1 vs L 25.9 RPM) and gyro (+37°) show it turned left. GPS kept saying "right of the line", so it kept steering left. 24 jumps rejected |
| 3 | `171947` | + wheel/gyro/GPS fusion, GPS heading corrections only with RTK fixed | Drifted left again; GPS vs fused 3.26 m apart | First 2 m perfectly straight (19.0/19.0 RPM, gyro 0). Following, GPS again said "right of the line" while the robot turned left 28°. Same place, same error: multipath off the buildings |
| 4 | `172213` | `--gps-gain 0` (GPS only for the line direction) | **Arrived**, ±0.13 m (estimated); ended angled | **Control oscillation**: heading swung ±7.7° with a ~14 s period. The gyro follows the turn command **2.85 s late** (skid-steer torque build-up), too slow for a 1.5 m look-ahead at 0.3 m/s |
| 5 | `172718` | + `--lookahead 3` | **Arrived**; weave down to ±2.8°; ended well off the walkway | The look-ahead fixed the weave. The line direction from GPS over 2 m was **34°**, against **58°** in run 4 on the same walkway: GPS heading error, not control |
| 6 | `173006` | `--no-gps`, `--lookahead 3` | **Arrived, "absolutely perfect"** | Heading within ±0.4° (−0.6 to +0.7°), estimated off-line ≤ 1.5 cm (mean 5 mm), ended +0.6° to the line, no pauses or stalls, 35 s |

`172851` is an aborted start of run 6 (stopped before moving). `logs/line_run<N>.out` is each run's console output.
`logs/line_run4.png` plots run 4's fused path against raw GPS (GPS ~2.6 m off).

### Dog-leg (L) path, `local` mode, right-hand

Path: 1 m straight, √2 m at 45° to the right, 2 m straight (4.41 m), 0.15 m/s, no GPS.

| Run | Log | Setup | Result |
|---|---|---|---|
| L1 | `173751` | look-ahead 2 m, plain wheels | Arrived; ended **−20.9°**, 1.41 m right (want 1.0), up to 0.41 m off. **Left turn back to straight: 0.8 of 6.7°/s commanded** (effective track ~5 m): in left turns the right driven wheel slips/lifts |
| L2 | `174609` | **rear (unpowered) wheels taped** to cut their sideways grip | Arrived; ended −10.4°, 0.94 m right, 0.06 m off. Right turns now achieve 3.9 of 4.0°/s; **turn delay ~1.35 s** (was 2.85-3.3 s). Remaining tilt: with a 2 m look-ahead on a 2 m final leg it aimed at the end point |
| L3 | `174849` | taped, **look-ahead 1.25 m + extended target** | **Arrived; ended −0.9°, 1.08 m right, worst 0.21 m off, mean 0.07 m** (simulation predicted 0.20 m and +0.7°). One corner still "snaps" (gyro peak 60°/s) as the taped wheels break free |

A small simulation (pure pursuit on the path, with a dead time plus first-order lag on the turn rate, fitted to the
measured delay) picked the speed and look-ahead before each run and matched L3 closely. Run 7 (`line_run7_tape.out`): 10 m straight with the 1.25 m
look-ahead at 0.3 m/s on the taped wheels, to check straights don't weave with the shorter look-ahead: **no weave**,
heading within ±0.2° (−0.3 to +0.2°), estimated off-line ≤ 0.5 cm (mean 1 mm), ended 0.0° to the line (log
`175149`). Two accidental button releases (1.3 s paused) were picked up cleanly. **One setting now covers both: look-ahead
1.25 m on the taped wheels.**

### Findings

1. **Steering works.** With a 3 m look-ahead, the no-pivot limits and the gyro yaw-rate loop, a straight line is
   followed to centimetres by wheels + gyro.
2. **Wheels + gyro are accurate over at least 10 m** (run 6 ended where the robot thought it was). The gyro bias
   wanders by about ±0.6°/s, now re-estimated whenever the robot stands still.
3. **The skid-steer responds late to turn commands:** ~2.85 s with plain wheels, ~1.35 s with the rear wheels
   taped. Keep the look-ahead ≥ ~3× the distance covered in that delay (3 m at 0.3 m/s plain; 1.25 m at 0.15 m/s
   taped), or add delay compensation.
5. **Left turns were weak on plain wheels** (outer right wheel slips: 0.8 of 6.7°/s). **Taping the unpowered rear
   wheels** fixed most of the turning trouble.
4. **RTK float beside BHEE is unusable for steering:** position wanders by metres for tens of seconds, it's biased the
   same way run after run, and the heading from 2 m of track varied by 24°. Signal strength was low too
   (24–32 dB-Hz, see GEM1305_CONFIG.md).

### Toward LMBS, evening of 7 Nov (dark, `local` mode, 0.3 m/s, look-ahead 1.5 m)

- **Finding the start without moving the robot:** RTK float (no fixed in 140 s) put the robot **inside BHEE**, ~8 m
  off. Matching a LiDAR scan to OSM building outlines (`map_localize.py`) was **ambiguous** there (best two poses 30 m
  apart, scores within 0.3 cm): in the recessed entrance the LiDAR mostly sees plants and benches. What worked: the
  user's description (the walkway from BHEE's recessed entrance to the Northwestern Ave bus stop) and a pace count
  (33 steps ≈ 25 m) for the first leg.
- **Run 1** (log `180813`, video): 25 m out of the entrance walkway, right turn onto the Northwestern sidewalk in about
  the right place (heading −82° vs −89° planned), "really close but slightly offset". Re-anchored by hand on the left
  of the sidewalk; the remaining route was shifted 0.7 m right to the sidewalk centre (`route_lmbs_local_sidewalk.txt`).
- **Run 2** (video `181324` only): **the Pi browned out and rebooted** about a minute in (`vcgencmd get_throttled`
  0x50000: undervoltage + throttling since boot) - the battery sagging under the motors. The STM32 reset too, so the
  motors stopped; the follower's log was lost because it's only written at the end.
- With the robot out of the courtyard the receiver reached **RTK fixed (24 sats)**. Against the no-GPS runs' own
  paths (accurate to centimetres), RTK fixed was ~10 cm off and float 15-42 cm, with metres of error near BHEE.

## 6. Next steps

0. **Safety, from the brownout:**
   - **STM32 command watchdog:** stop the motors if no command arrives for ~0.5 s. Today the firmware keeps the last
     target forever, so if the Pi crashes while the STM32 keeps power, the robot keeps driving.
   - **Power:** the Pi browned out under motor load. Check the battery charge / the Pi's supply (separate regulator,
     bulk capacitance) before longer runs.
   - **Write the follower log as it goes** (it was lost in the reboot).

1. ~~L-shaped path~~ done (L3). Smooth the corner "snap": limit the yaw-rate integral build-up while the
   taped wheels haven't broken free yet.
2. **Absolute pose without GPS near buildings:**
   - **Start from a known pose:** a marked start spot, pointing along a walkway whose direction comes from the map.
   - **LiDAR alignment:** walkway edges and building walls give an absolute heading all along the LMBS route.
   - **LiDAR scan matching** (`motor_cal/lidar_odom.py`, within ~1° of the gyro, 5 ms/scan) for position, to
     catch wheel slip.
3. **GPS only for slow drift,** and only when it agrees with the odometry, or in open sky / RTK fixed.
4. **Then the LMBS route,** supervised, with the hold-to-run page.
