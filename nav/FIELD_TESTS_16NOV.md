# Field tests, 16 Nov 2026: four campus routes with `--avoid`

Outside, Purdue engineering campus. Routes from Valhalla (OSM pedestrian graph), robot position from RTK when it
had it. Logs in `nav/logs/` (`follow_route_<date>_<time>.json`, `_route.json`, `_track.json`; the LiDAR scans
`_scans.npz` and the videos stay on the Pi, too big for git).

| run | log | route | speed | result |
|---|---|---|---|---|
| 1 | `165625` | robot → MSEE front, 172 m | 0.3 m/s | 137.8 m, then stopped by hand; stuck at a slope, a kerb, a person |
| 2 | `174252` | MSEE → WALC, 246 m | 0.8 m/s | **arrived**; 225 s to get going (started facing away, K-turns between two bins) |
| 3 | `180149` | WALC → Lambertus, 332 m | 1.5 m/s | **arrived**; 146 s stuck in the heading leg, then 1.09 m/s average |
| 4 | `181616` | Lambertus → BHEE west walk, 153 m | 1.5 m/s | **a wheel came off** at ~200 s; carried the rest |

## Run 1 (MSEE), what went wrong

- **Rising ground read as a wall.** Where the walk rises to the crossing, the flat LiDAR beam hits the pavement
  ~4.5 m ahead: a dense band of returns across the whole corridor that *moves with the robot* (nearest return ahead
  15 m → 4.7 m while the robot moved ~1 m). Blocked 62 s, then 42 s; the 8 s wider corridor was tried (from ~131 s)
  but the "wall" was wider than it too. Only moved on after a human stepped in.
- **A kerb below the scan plane.** At 632 s it commanded 0.2 m/s, both wheels read 0 rpm, odometry and GPS froze:
  pushing against a kerb for 8 s, 3 STM32 stall faults, each cleared and retried. The planner thought the way was
  clear, so the wider-corridor logic never ran.
- **A person standing in the way: 26 s to get past.** Guard stop, wait 2.5 s, straight back 0.6 m at 0.15 m/s, forward
  on the same 1 m-radius curve, stopped again, second back-up. The plan passed only 0.3–0.5 m from the person, inside
  the guard's dead-ahead box.
- Path following was good: 0.14 m mean off-line when not avoiding; fused pose within 5 cm (median) of RTK fixed.

## Changes made during the day (in this commit; only partly tested, see below)

| change | where | flag |
|---|---|---|
| **Creep toward far blocks**: blocked in both corridors but the block is > 2 m away → creep along the route at 0.25 m/s (the blocked timer keeps running; creeping stops 2 m short of anything real) | `LocalNav._creep` | `--no-creep` |
| **Stuck detector**: commanding forward, wheels moved < 4 cm in 1.2 s (or an STM32 stall fault) → lock a chassis-wide strip ahead of the bumper into the costmap (scans can't clear it), back up ≥ 0.5 m, replan round it; give up after 8 | `follow.py`, `LocalNav.mark_bumper`, `RollingCostmap.locked` | `--stuck-s`, `--max-stuck` |
| **K-turn back-up**: after 0.5 s held (was 2.5 s), 0.4 m/s (was 0.15), 0.4–1.0 m (was 0.6), on a 0.6 m-radius arc that swings the nose toward the plan; stops as soon as the way ahead is clear | `LocalNav.recovery` | `--no-backup` |
| **Turn on the spot** when the target is > 75° off the nose (only the guard's own stop may be in force, never anything touching the chassis) | `follow.py` | `--pivot-deg` (0 = off), `--pivot-w` |
| **GPS grace**: keep going on wheels + gyro for 1 s after the fix drops, then pause (follow phase only) | `gps_paused()` | `--gps-grace` |
| **Speed 1.5 m/s** default (~141 of ~195 wheel rpm); look-ahead now `max(1.5, 2.5 × speed)` = 3.75 m | `follow.py` | `--speed`, `--lookahead` |
| `load_scans` loaded each array once (it re-read the whole `.npz` per scan: > 60 s → 0.9 s) | `local_nav.py` | |
| Harness scenarios `kerb`, `slope`, `person_ahead` and `--flags` | `sim_follow_harness.py` | |

**Testing status:** replaying run 1's scans through the new planner gives "creeping: blocked 4.9 m ahead" at every
moment it sat blocked (126, 140, 160, 205 s). The stuck detector, the arc back-up and the new harness scenarios
have **not** been run in closed loop (the real-time harness runs were stopped to save time). Turning on the spot
and the GPS grace were used in runs 3–4.

## Run 2 (WALC)

Arrived, 246 m. The start took **225 s for the first metre**: the heading leg found the robot facing ~32°
(north-east) while the route leaves south-west, and with no pivots it K-turned between two bins (7 back-ups,
25 s of guard stops, 31 s blocked, 57 s of joystick). **61 GPS pauses, 138 s**, 32 of them ≤ 1 s; plain GPS 27 %
of the time. After the start: 245 m in 465 s, 0.65 m/s average moving. → turn on the spot, GPS grace, faster
back-ups, 1.5 m/s.

## Run 3 (WALC → Lambertus): issues

- **Heading leg stuck 146 s.** Before following, the robot drives 3 m straight to fit its heading from RTK. That leg
  uses the old straight-box LiDAR check and has **no avoidance, no back-up, no pivot and no GPS grace**. Nosed up to
  something on its front-left (398 returns at +19..+85°, nearest 0.66 m, at 100 s), it sat: 33 s LiDAR-stopped,
  26 s GPS pauses, 10 s joystick.
- **Flickering status.** Only 4 real stop/go flips while the button was held; what alternated was two *stop reasons*
  for the same object ("obstacle 0.51 m ahead" from the straight box, "something 0.23 m away at +44 deg" from the
  ring), and before the button, "obstacle"/"slowing" at exactly the 0.80 m stop line. Neither check has hysteresis.
- Once following: **1.09 m/s average, 1.50 max**; 0.13 m mean off-line when not avoiding (p95 0.28 m); **0 s of GPS
  pauses** (138 s in run 2: the grace works); 1 back-up; 1.1 s of pivoting.

## Run 4 (Lambertus → BHEE): issues

- **Planned from a plain-GPS fix.** Between Lambertus and Knoy the start fix was plain GPS, ~9 m off (it put the
  robot inside Lambertus). The follower began **15 m from the route** ("path blocked: no plan yet": the route was
  off the 16 m costmap's useful area) until the joystick brought it closer.
- **70 % plain GPS**, 27 resets of the fused pose to GPS, 418 fixes ignored by the fusion gate: an urban canyon.
- **Pivots and the wheel.** 6 turn-on-the-spot bursts between 39 and 200 s (2.2, 1.0, 1.6, 0.2, 0.4, 0.7 s). The one
  STM32 stall fault came at 187 s, right after the 1.6 s pivot at 185 s. The wheels last turned at 200 s, right after
  the last pivots; then a wheel came off. Spinning a skid-steer on the spot loads the wheel hubs sideways (and was
  disabled in path following before today for stalling the motors). **Strong suspect.**
- After 200 s the odometry moved 7 cm while GPS moved 89 m: the robot was carried. The logged "progress 132 m" and
  "off line 13.9 m mean" are GPS following the carry, not driving; autonomous driving was ~45 s.

## Open items, in priority order

1. **Wheels**: check every hub's set screw / key / nut before the next run. Until the hubs are secured, run with
   `--pivot-deg 0` (no turning on the spot).
2. Heading leg: drive it **in reverse** when the way ahead is blocked (the RTK track works backwards), and give it the
   GPS grace.
3. **Hysteresis** on both LiDAR checks (release ~10 cm past the stop line) and one stop reason at a time.
4. Don't start a route from a plain-GPS fix: wait for RTK float, or start the route where the robot really is.
5. Closed-loop harness runs of `kerb`, `slope`, `person_ahead` (the new behaviours have only been replayed).
6. Still outstanding from before: STM32 command watchdog (it holds its last target if the Pi dies); Pi undervoltage
   under motor load (throttled 0x50000 this boot).
