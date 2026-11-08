# Obstacle avoidance: LiDAR costmap + grid planner (`--avoid`)

`follow.py --avoid` bends the route around things the route doesn't know about, like bins, bike racks, parked
bikes and people. It stays within `--corridor` m of the route. If there's no way through, it stops and waits.
Without `--avoid`, follow.py behaves exactly as before.

Everything here was built and tested in simulation before going on the robot. The simulation covers the
measured turning lag, a simulated STL27L and campus-like obstacles. Numbers are in **Simulation results** below.

## Files

| file | what |
|---|---|
| `nav/local_nav.py` | the costmap, planner, path guard and back-up (`LocalNav`), and the planner thread (`NavThread`). `python3 nav/local_nav.py` benchmarks it on the real BHEE scans. |
| `nav/follow.py` | `--avoid`, `--corridor`, `--widen-after`, `--no-backup`, `--log-scans` |
| `nav/sim_local_nav.py` | closed-loop simulator: 13 scenarios × robot models × speeds, plus today's follow.py as a baseline |
| `nav/sim_follow_harness.py` | runs the **real follow.py** in real time against the simulator (fake LiDAR / IMU / STM32 / button) |

## On the Pi, in this order

1. **Install scikit-image** (the fast search; without it a pure-Python search is used, ~5× slower):
   `.venv/bin/pip install scikit-image` (aarch64 wheels exist for Python 3.13).
2. **Benchmark**: `.venv/bin/python nav/local_nav.py`. It prints map-update and plan times on the BHEE scans.
   Budget: a map update every 100 ms and a plan every 200 ms, in their own thread. Here (2.1 GHz Xeon) they took
   ~5-7 ms and ~8 ms; expect 2-3× that on the Pi 5. Anything under ~40 ms per plan is fine.
3. **Self-returns**: with the robot standing in the open, check nothing of the robot shows up within 5 cm of
   the chassis outline (`FOOTPRINT` in local_nav.py, 600 × 460 mm about the turning centre). The guard stops for
   anything in that ring. The BHEE scans have nothing there; the intermittent 0.18 m return at +52 deg falls
   inside the outline, so it's ignored. If the chassis or the LiDAR mounting differs, fix `FOOTPRINT` /
   `lidar_xy` first.
4. **Harness, on the Pi or a laptop** (no robot needed): `python3 nav/sim_follow_harness.py trash_can --avoid`.
   It should arrive with ~0.45 m clearance.
5. **On the robot, local mode, no GPS**, a bin or a box in an open space:
   `.venv/bin/python nav/follow.py local --points "0,0 15,0" --avoid --speed 0.3 --log-scans`.
   Put the box on the line ~8 m ahead. Expect it to start bending ~5-7 m before the box and pass with
   0.4-0.5 m clearance. Then try two boxes 1.0 m apart across the line (it should go through the gap,
   slowly), and a box right across with no way round inside 1.5 m (it should stop ~2-4 m short, and after
   8 s go round wider if it can).
6. **Route mode**, a short stretch with a real bin or bike rack, then longer.

`--log-scans` saves every scan with its poses (`logs/..._scans.npz`, about 4 MB per minute). The run JSON gets
the plan once a second (`nav_paths`) and per tick `ox, oy, oh` (odom pose), `nav_ok`, `nav_why`, `nav_dev`
(how far the plan bends), `nav_clear`, `nav_ms`, `back`. `local_nav.load_scans()` reads the scans back, so a
real run can be replayed through the planner offline.

## Flags

| flag | default | |
|---|---|---|
| `--avoid` | off | turn it on |
| `--corridor` | 1.5 m | furthest the plan may leave the route. **The LiDAR can't see grass or curbs**: this is the only thing keeping the robot on the sidewalk. About half the walk's width. |
| `--widen-after` | 8 s | still blocked after this long: also try a 60 % wider corridor (gets round a barrier, possibly over grass). 0 = never; it just waits. |
| `--no-backup` | | never back up |
| `--log-scans` | | save the scans |

The planner's own knobs are `LocalNav(...)` arguments in local_nav.py. The ones that matter:
- `lethal_m` 0.30 (chassis half-width 0.23 + 7 cm): the narrowest gap it plans through is 2 × this = 0.60 m.
- `inflate_m` 1.0, `w_inflate` 12: how hard it keeps away from things.
- `carrot_m` 7: how far ahead it plans.

## How it works

**Two frames.** The costmap lives in an *odom* frame (wheels + gyro only), which GPS never moves.
follow.py's fused pose (the frame the route is in) gets GPS nudges and occasionally jumps. A map kept in that
frame would smear, or jump obstacles toward the robot. Each plan maps the route into odom using the current
fused-vs-odom offset. A GPS correction then moves the route relative to the obstacles, which is right, and
never moves the obstacles relative to the robot. (In the sim, a 0.8 m GPS jump mid-avoidance: see results.)

**Map** (every scan, ~10 Hz): 16 m × 16 m at 5 cm, centred 3 m ahead of the robot, re-centred by whole-cell
shifts.
- Each scan does a log-odds update: +0.85 at each return, −0.4 along each beam (up to 6 m), clamped to [−2, 2].
- The robot's own footprint is forced free. Positive cells fade 3 % per scan.
- No-return beams don't clear anything, because the driver drops them.
- Unknown cells cost nothing extra. Open areas are mostly unknown, since grass and sky return nothing; an
  unknown-cost made it hug the few seen-free cells.

**Plan** (every 0.2 s): Dijkstra over the grid (scikit-image `MCP_Geometric`, 8-connected) from the robot to
candidate goals on the route 5-8.5 m ahead, inside a crop around the route window. The cost per cell is:
- 1, plus
- inflation: infinite within 0.30 m of a return, then quadratic to 1.0 m (weight 12), plus
- corridor: distance to the route, linear + quadratic, infinite beyond 1.5 m, plus
- kinematics: +20 behind the robot and inside its two 1 m turning circles (the search is holonomic; the robot
  can't reverse or pivot), plus
- hysteresis: +0.4 per metre away from the previous plan, but only beyond 1.5 m, so it keeps the side it chose.

The goal is the candidate with the lowest cost minus 1.2 × progress. The path is smoothed, and smoothing is
kept only if it stays clear.
- **If nothing is within 0.6 m of the route ahead and the robot is within 0.35 m of it, the plan is just the
  route.** On a clear walk it then behaves exactly like follow.py without `--avoid`.
- **No path:** "path blocked", stop and wait. Closer goals aren't used as a fallback (see results). After 8 s
  it also tries a 2.4 m corridor.

**Following**: pure pursuit on the local path in odom, look-ahead 1.5 m, shortened to 0.8 m when the path squeezes
past something (clearance/0.9 m × 1.5 m). Speed × clearance factor (0.35 at ≤ 0.35 m clearance, 1 at ≥ 0.9 m),
capped by curvature (a_lat 0.5 m/s²). Then follow.py's yaw-rate PI and wheel limits, unchanged.

**Guard** (replaces `lidar_check` while following with `--avoid`):
- Stop if anything is within 5 cm of the chassis outline.
- Stop if anything is dead ahead (26 cm either side), within the distance covered during the 0.8 s turn delay.
- Otherwise look along the *planned path*, not a straight box:
  - stop if anything is within 0.28 m of the path within max(0.8 m, 0.3 + 1.2 v);
  - half speed if anything is within 0.40 m of the path within max(2 m, 3 v).
- Returns inside the chassis outline are the robot itself and are ignored.
- This is also what removes today's self-return micro-stops: the old "anything within 0.25 m" check fired on
  them.

**Back-up**: if the guard holds the robot for 2.5 s while there is a plan, it's nose-up to something and can't turn
tighter than 1 m. It backs straight up 0.6 m at 0.15 m/s, stopping early if anything is within 0.45 m behind.
It only does this when the guard is the *only* reason it's stopped: never with the button released, never when
GPS is stale, never under manual driving.

## Simulation results

80 runs: 13 scenarios × (taped wheels at 0.3 / 0.6 m/s, casters at 0.3 / 0.6 / 0.8 m/s), plus today's follow.py (no `--avoid`, taped, 0.3 m/s) on each, plus the GPS-jump scenario with the costmap in the GPS frame. The models:

- **taped**: today's robot as fitted from the run toward Lambertus, ~1 s turning delay with stick-slip.
- **casters**: the same robot with swivel casters, so its yaw follows the wheels.

Each cell gives the result, then the closest the chassis rectangle came to anything (true geometry), then the time taken.

| scenario | today 0.3 | taped 0.3 | taped 0.6 | casters 0.3 | casters 0.6 | casters 0.8 |
|---|---|---|---|---|---|---|
| Clear walk | through, nothing near, 156 s | through, nothing near, 123 s | through, nothing near, 63 s | through, nothing near, 123 s | through, nothing near, 62 s | through, nothing near, 47 s |
| Bin on the route | **stuck**, 0.47 m, 224 s | through, 0.43 m, 127 s | through, 0.49 m, 64 s | through, 0.43 m, 127 s | through, 0.45 m, 64 s | through, 0.46 m, 49 s |
| Bike rack + parked bikes | **stuck**, 0.47 m, 224 s | through, 0.42 m, 126 s | through, 0.49 m, 64 s | through, 0.47 m, 126 s | through, 0.50 m, 63 s | through, 0.52 m, 48 s |
| Gap 1.0 m | **stuck**, 0.29 m, 224 s | through, 0.21 m, 143 s | through, 0.23 m, 80 s | through, 0.24 m, 143 s | through, 0.25 m, 79 s | through, 0.24 m, 59 s |
| Gap 0.75 m | **stuck**, 0.47 m, 224 s | through, 0.08 m, 156 s | through, 0.10 m, 90 s | through, 0.10 m, 143 s | through, 0.10 m, 89 s | through, 0.11 m, 75 s |
| Group across the walk | through, 2.41 m, 156 s | through, 2.16 m, 132 s | through, 2.34 m, 73 s | through, 2.16 m, 132 s | through, 2.32 m, 71 s | through, 2.50 m, 56 s |
| Barrier | **stuck**, 0.45 m, 224 s | through, 0.9 m onto grass, 0.31 m, 145 s | through, 0.9 m onto grass, 0.32 m, 80 s | through, 0.9 m onto grass, 0.31 m, 145 s | through, 0.9 m onto grass, 0.32 m, 79 s | through, 0.9 m onto grass, 0.30 m, 62 s |
| Oncoming person | **stuck**, 0.22 m, 224 s | through, 0.21 m, 127 s | through, 0.17 m, 66 s | through, 0.22 m, 127 s | through, 0.24 m, 65 s | walked into*, -0.29 m, 51 s |
| Crossing person | through, nothing near, 156 s | through, 1.16 m, 125 s | through, 1.31 m, 64 s | through, 1.16 m, 124 s | through, 1.23 m, 63 s | through, 1.25 m, 48 s |
| Route 0.9 m off | **stuck**, 0.23 m, 224 s | through, 1.3 m onto grass, 0.51 m, 133 s | through, 1.3 m onto grass, 0.45 m, 68 s | through, 1.3 m onto grass, 0.52 m, 133 s | through, 1.3 m onto grass, 0.50 m, 67 s | through, 1.3 m onto grass, 0.52 m, 51 s |
| GPS jump | **stuck**, 0.44 m, 224 s | through, 0.46 m, 127 s | through, 0.43 m, 65 s | through, 0.45 m, 127 s | through, 0.48 m, 64 s | through, 0.49 m, 48 s |
| Corner + obstacles | **stuck**, 0.48 m, 224 s | through, 0.33 m, 134 s | through, 0.37 m, 70 s | through, 0.33 m, 134 s | through, 0.37 m, 71 s | through, 0.38 m, 53 s |
| Campus mix, 64 m | **stuck**, 0.46 m, 383 s | through, 0.1 m onto grass, 0.23 m, 257 s | through, 0.3 m onto grass, 0.24 m, 137 s | through, 0.1 m onto grass, 0.25 m, 258 s | through, 0.26 m, 141 s | through, 0.2 m onto grass, 0.26 m, 107 s |

With `--avoid`, all 65 of 65 runs arrived, and none drove into anything. The exceptions:

- \* One run had contact: oncoming person, casters, 0.8 m/s. The simulated person never yields; they walked into the robot after it had stopped (0.11 m/s at first touch).
- Barrier: it went 0.9 m onto grass, because that is the only way round. It does this only after 8 s blocked (`--widen-after`).
- Route 0.9 m off: it went 1.3 m onto grass (see the risks below).
- Campus mix: at its 90° turns the chassis corner overhangs the walk edge by 0.1-0.26 m.

Today's follow.py got stuck in front of 10 of the 13 scenarios. On the clear walk it took 156 s against 123 s: the old guard's "anything within 0.25 m" check keeps firing on the intermittent self-return.

GPS jump: with the costmap in the GPS frame instead, it also got past (0.39-0.44 m, against 0.43-0.49 m). So a single jump shows only a small benefit. The odom frame is there for the metre-scale RTK float wandering seen near buildings on 7 Nov, which the simulator doesn't model.

**Timing** on a 2.1 GHz Xeon core, over 29,349 plans:

- Map update: median 4.7 ms, worst run's 95th percentile 18 ms.
- Plan: median 3.0 ms (mostly the route-is-clear shortcut). A full search takes 6-12 ms. The worst run's 95th percentile was 34 ms, and the single slowest plan 99 ms.

Expect 2-3× on a Pi 5. The budget is 100 ms per update and 200 ms per plan, in their own thread.

**The real follow.py** (`sim_follow_harness.py`, real time, final code):

- Bin, casters 0.6 m/s, `--avoid`: arrived in 31 s, closest 0.43 m. Loop ticks median 50 ms, worst 54 ms.
- Bike rack, taped 0.6 m/s, `--avoid`: arrived in 52 s, closest 0.48 m, worst tick 52 ms.
- Bin, today (no `--avoid`): time limit, stopped 0.47 m from the bin.

**Real scans**: on the five BHEE-entrance scans in `scan_here.json`, a route through the racks makes it bend 1.5 m round them with 0.84 m clearance.

## What the simulation changed

Each problem below was found in a run, fixed, and then the whole matrix was re-run.

1. **The planner made it weave on an empty walk.** The first version pulled each plan toward the previous one
   everywhere, so the plan followed the robot's drift. With the turning delay that became a weave: 15 cm rms
   off the line against 2 cm without the planner. Fix: that pull applies only beyond 1.5 m, there's a linear pull
   back to the route, and when nothing is near the route the plan is the route itself. Now 2 cm, the same as
   follow.py without `--avoid`.
2. **A 2 m corridor planned it round a group of people on the grass**, 0.5 m past the walk's edge. Fix: 1.5 m
   corridor; when blocked, wait, and only after 8 s try 60 % wider. It now stops 2.3 m short and waits.
3. **Falling back to closer goals parked it nose-up to a barrier.** With the far goals blocked, it aimed at
   nearer points on the route and crept to 0.4 m from the barrier. With a 1 m minimum turning radius it can't get
   out of that, and it sat there for 165 s. Fix: closer goals only at the route's end or the map edge, so a
   blockage seen 7 m out stops it 2-4 m short. Plus the back-up.
4. **Pure pursuit cut the corner round the end of the barrier.** A 1.5 m look-ahead cut the plan's tight bump by
   ~10 cm, and the 0.30 m planning radius is less than the chassis corner (0.37 m), so it touched the barrier
   (−3 cm). Fix: look-ahead shortens to 0.8 m when squeezing past things, and the inflation weight goes 6 → 12.
   Now +0.30 m at the tip.
5. **It planned U-turns the robot can't drive.** After a stop beside a bin, the holonomic search doubled back
   round the other side, and following that turned the robot into the bin (−2.5 cm). Fix: cost on cells behind
   the robot and inside its 1 m turning circles, and a log-odds ceiling of 2.0 (was 3.5) so a passing person's
   trail clears in ~0.4 s. Now 0.44 m.
6. **The guard lost a person once they were close.** Returns within 3 cm of the chassis outline were treated as
   the robot itself, so a person that close vanished and it drove on. Fix: the self-mask applies only inside the
   outline, there's a stop for anything within 5 cm of it, and stop/slow distances grow with speed.
7. **Unknown space as a cost made plans hug the few seen-free cells.** On the BHEE scans, plans detoured to stay
   on seen cells even where the route was clear. Fix: unknown costs nothing extra.

## What the simulation can't tell you (test these on the robot)

- **Grass and curbs are invisible to it.** `--corridor` is the only fence, and the "route 0.9 m off" scenario
  shows what happens when the route is wrong: it went round the racks on the far side, 1.3 m onto grass. Keep the
  corridor at about half the walk's width and check routes against the satellite view. A camera sidewalk mask
  (the Hailo is there) is the real fix if this keeps happening.
- **What the real STL27L sees at its mounting height.** Watch for:
  - bikes, which are mostly spokes;
  - low benches and chains between posts, which may sit under the scan plane;
  - glass doors;
  - ramps where the scan plane hits the ground ahead. That looks like a wall: the robot stops, or waits 8 s and
    goes round.

  Drive past racks and up a ramp with `--log-scans` and look.
- **Footprint and self-returns.** If the LiDAR isn't at the turning centre, or anything sticks out of the
  600 × 460 mm outline, set `FOOTPRINT` / `lidar_xy` (`LocalNav(..., lidar_xy=(x, y))`), or the guard will stop
  for the robot's own parts.
- **Pi timing**, with the camera recording too. Check `nav_ms` in the log and the loop tick times.
- **Reversing.** The joystick reverses, but the autonomous code never has before. Try the back-up with a box in
  the open.
- **People.** Simulated people never yield. With real people, it slows and stops, then waits for them.
- **Taped wheels at speed.** At 0.6 m/s the taped model weaves ±13 cm with or without the planner (stick-slip
  plus the ~1 s turning delay); the casters model doesn't. Fit the casters before going faster.
