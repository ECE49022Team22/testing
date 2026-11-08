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

1. **Install scikit-image** (the fast search; without it a pure-Python search is used, ~2.5× slower):
   `.venv/bin/pip install scikit-image` (aarch64 wheels exist for Python 3.13).
2. **Benchmark**: `.venv/bin/python nav/local_nav.py`. It prints map-update and plan times on the BHEE scans.
   Budget: a map update every 100 ms and a plan every 200 ms, in their own thread. Here (2.1 GHz Xeon) they took
   ~0.7 ms and ~2 ms; expect 2-3× that on the Pi 5. Anything under ~40 ms per plan is fine. OpenCV (already
   installed for the camera) makes the distance transforms ~3.5× faster; without it scipy is used.
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
- Each scan does a log-odds update: +0.85 at each return, −0.4 along every third beam (0.5° apart, about a cell
  at 6 m; up to 6 m), clamped to [−2, 2].
- The robot's own footprint is forced free. Positive cells fade 3 % per scan.
- No-return beams don't clear anything, because the driver drops them.
- Unknown cells cost nothing extra. Open areas are mostly unknown, since grass and sky return nothing; an
  unknown-cost made it hug the few seen-free cells.

**Plan** (every 0.2 s): first the cheap check below (the route itself, when it's clear). Otherwise Dijkstra
(scikit-image `MCP_Geometric`, 8-connected) from the robot to candidate goals on the route 5-8.5 m ahead,
inside a crop around the route window. The search runs on a **10 cm grid pooled from the 5 cm map** (4× fewer
cells):
- A 10 cm cell is no-go if the mean of its four obstacle distances (its centre's, within 3.5 cm) is ≤ 0.30 m,
  so every gap of 0.7 m or more stays open.
- Its inflation cost uses the best of the four, as a 5 cm path could.
- Obstacle and corridor distances, smoothing and the clearance checks stay at 5 cm.
- Distance transforms use OpenCV when it's installed (exact; it's on the robot for the camera), and scipy
  otherwise.

The cost per cell is:
- 1, plus
- inflation: infinite within 0.30 m of a return, then quadratic to 1.0 m (weight 12), plus
- corridor: distance d to the route, linear + 2·(min(d, cap)/cap)⁴, infinite beyond the cap (1.5 m), plus.
  - The second term is steep near the edge, which is roughly the walk's edge, and flat past it, where the robot
    may be after a detour.
  - Why the 4th power: with a square, going round the bench beside a 1.0 m gap (on the grass) cost within 1 % of
    going through the gap, so either could win.
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
| Bin on the route | **stuck**, 0.47 m, 224 s | through, 0.40 m, 129 s | through, 0.43 m, 65 s | through, 0.41 m, 128 s | through, 0.42 m, 65 s | through, 0.43 m, 49 s |
| Bike rack + parked bikes | **stuck**, 0.47 m, 224 s | through, 0.38 m, 128 s | through, 0.42 m, 65 s | through, 0.43 m, 128 s | through, 0.47 m, 64 s | through, 0.49 m, 48 s |
| Gap 1.0 m | **stuck**, 0.29 m, 224 s | through, 0.22 m, 143 s | through, 0.24 m, 80 s | through, 0.24 m, 143 s | through, 0.25 m, 79 s | through, 0.25 m, 59 s |
| Gap 0.75 m | **stuck**, 0.47 m, 224 s | through, 0.08 m, 147 s | through, 0.09 m, 93 s | through, 0.10 m, 146 s | through, 0.11 m, 90 s | through, 0.12 m, 75 s |
| Group across the walk | through, 2.41 m, 156 s | through, 2.18 m, 133 s | through, 2.27 m, 72 s | through, 2.25 m, 132 s | through, 2.16 m, 71 s | through, 2.66 m, 57 s |
| Barrier | **stuck**, 0.45 m, 224 s | through, 0.9 m onto grass, 0.29 m, 147 s | through, 0.9 m onto grass, 0.28 m, 80 s | through, 0.9 m onto grass, 0.28 m, 147 s | through, 0.9 m onto grass, 0.32 m, 79 s | through, 0.9 m onto grass, 0.30 m, 62 s |
| Oncoming person | **stuck**, 0.22 m, 224 s | through, 0.21 m, 129 s | through, 0.14 m, 68 s | through, 0.23 m, 129 s | through, 0.24 m, 66 s | walked into*, -0.27 m, 50 s |
| Crossing person | through, nothing near, 156 s | through, 1.16 m, 125 s | through, 1.34 m, 65 s | through, 1.17 m, 125 s | through, 1.23 m, 63 s | through, 1.27 m, 49 s |
| Route 0.9 m off | **stuck**, 0.23 m, 224 s | through, 1.2 m onto grass, 0.44 m, 139 s | through, 1.3 m onto grass, 0.53 m, 71 s | through, 1.2 m onto grass, 0.45 m, 139 s | through, 1.2 m onto grass, 0.48 m, 70 s | through, 1.3 m onto grass, 0.47 m, 53 s |
| GPS jump | **stuck**, 0.44 m, 224 s | through, 0.41 m, 128 s | through, 0.46 m, 65 s | through, 0.42 m, 128 s | through, 0.46 m, 64 s | through, 0.49 m, 48 s |
| Corner + obstacles | **stuck**, 0.48 m, 224 s | through, 0.35 m, 135 s | through, 0.38 m, 70 s | through, 0.34 m, 136 s | through, 0.38 m, 72 s | through, 0.37 m, 52 s |
| Campus mix, 64 m | **stuck**, 0.46 m, 383 s | through, 0.24 m, 265 s | through, 0.1 m onto grass, 0.23 m, 142 s | through, 0.25 m, 264 s | through, 0.25 m, 142 s | through, 0.26 m, 108 s |

With `--avoid`, all 65 of 65 runs arrived, and none drove into anything. The exceptions:

- \* One run had contact: oncoming person, casters, 0.8 m/s. The simulated person never yields; they walked into the robot after it had stopped (0.14 m/s at first touch).
- Barrier: it went 0.9 m onto grass, because that is the only way round. It does this only after 8 s blocked (`--widen-after`).
- Route 0.9 m off: it went 1.2-1.3 m onto grass (see the risks below).
- Campus mix: at its 90° turns the chassis corner overhangs the walk edge by up to 0.11 m.

Today's follow.py got stuck in front of 10 of the 13 scenarios. On the clear walk it took 156 s against 123 s: the old guard's "anything within 0.25 m" check keeps firing on the intermittent self-return.

GPS jump: with the costmap in the GPS frame instead, it also got past (0.38-0.46 m, against 0.46 m). So a single jump shows only a small benefit. The odom frame is there for the metre-scale RTK float wandering seen near buildings on 7 Nov, which the simulator doesn't model.

**Timing** on a 2.1 GHz Xeon core, over 29,680 plans:

- Map update: median 0.6 ms, worst run's 95th percentile 1.2 ms.
- Plan: median 0.6 ms (mostly the route-is-clear check). A full search takes 1.5-3 ms. The worst run's 95th
  percentile was 5.5 ms, and the single slowest plan 19 ms.
- Before the speed-up (8 Nov) these were 4.7 / 18 ms and 3.0 / 34 / 99 ms. See **Speed** below.

Expect 2-3× on a Pi 5. The budget is 100 ms per update and 200 ms per plan, in their own thread.

**The real follow.py** (`sim_follow_harness.py`, real time, final code):

- Bin, casters 0.6 m/s, `--avoid`: arrived in 31 s, closest 0.42 m. Loop ticks median 50 ms, worst 50 ms.
- Bike rack, taped 0.6 m/s, `--avoid`: arrived in 53 s, closest 0.55 m, worst tick 50 ms.
- Bin, today (no `--avoid`): time limit, stopped 0.47 m from the bin.

**Real scans**: on the five BHEE-entrance scans in `scan_here.json`, a route through the racks makes it bend 1.4 m round them with 0.71 m clearance.

## Speed

The planner was profiled and sped up on 8 Nov, using a replay of every planner call from five simulated runs:
35k calls over 4,775 scans, interleaved with the original. A *cycle* is one LiDAR period (100 ms): one map update,
about half a plan, two guard checks, two back-up checks and two path look-ups.

| | before | after | |
|---|---|---|---|
| cycle mean | 6.6-7.8 ms | 1.55-1.70 ms | **4.6×** (4.0-4.9× per paired run) |
| cycle 99th percentile | 17.7-22.2 ms | 5.7-6.3 ms | **3.5×** (2.8-3.9×) |
| map update mean | 3.4-4.3 ms | 0.63-0.70 ms | ~6× |
| plan mean / 99th percentile | 4.4-4.9 / 15-18 ms | 1.5 / 5.2-5.6 ms | ~3× |
| guard / back-up check | 0.42 / 0.21 ms | 0.09 / 0.017 ms | 4.5× / 12× |

What changed:

1. **Free-space raycast.** Every third beam, one sample per cell, all beams at once, each cut where it returns or
   leaves the grid. It was sampling every beam every 3.5 cm and then running `nonzero`.
2. **Scan conversion.** Done once per scan with `fromiter` and shared by the map, guard and back-up. It used to be
   converted five times per scan.
3. **Plan order.** The route-is-clear check runs right after the obstacle distance transform, before any cost
   grid is built.
4. **10 cm search grid.** The search runs on a grid pooled from the 5 cm map. No-go uses the mean distance, so
   gaps of 0.7 m or more stay open; the inflation cost uses the best sub-cell. Obstacle and corridor distances,
   smoothing and clearance checks stay at 5 cm.
5. **OpenCV distance transforms** (exact) when installed.
6. **Guard.** Exact distance to the plan's segments, for returns in the plan's bounding box only.
7. **Route window.** It starts 1 m behind the robot, not 3 m.

Results:

- **Complexity:** average cyclomatic complexity (radon) went 4.14 → 3.74. Splitting `_plan` (39) into small
  helpers did that; the worst function is now 12. SLOC went 591 → 611.
- **Decisions on identical inputs:** go/blocked and route-is-clear agree on all 2,145 plans, and guard speed
  decisions on 99.97 % of 9,543. In the five that differ, the new guard slows slightly earlier.
- **Closed loop:** all 67 runs with `--avoid` have the same outcome and no robot-caused contacts. Closest
  approaches are within ±7 cm and finish times within ±5 %.

One cost changed on purpose. The corridor term went from (d/1.5)² to 2·(min(d, 1.5)/1.5)⁴: steep near the edge,
flat past it.
- In the original, going round the bench beside the 1.0 m gap (onto grass) cost within 1.2 % of going through
  the gap. The faster grid tipped it, and at 0.3 m/s the robot went 0.7 m onto grass.
- With the new term the margin is 7-9 % on both grids, and it goes through the gap.
- Side effect: at the 90° corners of the campus run, the chassis now overhangs the walk by up to 0.11 m instead
  of 0.26 m.

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
