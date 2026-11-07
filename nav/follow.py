#!/usr/bin/env python3
"""Autonomous path following with RTK GPS, a gyro-kept heading and a LiDAR crash guard.

    .venv/bin/python nav/follow.py line [--length 10] [--speed 0.3]     step 2: straight line
    .venv/bin/python nav/follow.py route nav/route_lmbs_points.json      later: a planned route ([lat, lon] list)

Open the hold-to-run page it prints (http://<pi>:8100/) on a phone and hold the button: the robot only moves
while it's held, and stops within ~0.5 s of letting go. Stop the demo first (it uses the motors and the GPS port).

How it works:
- Position: GGA from the GEM1305 (5 Hz) with RTK corrections from the NTRIP caster (ntrip_rtk.py, corrections
  out on UART4 / pin 32). If the Pi has no IPv4 route, the caster is reached through NAT64 (64:ff9b::/96).
  Positions go into a local east/north frame (metres) around the start.
- Heading: the IMU's gyro gives the turn; the absolute heading comes from the GPS track. The robot first drives
  --init-m straight (gyro holding zero turn) and takes the heading from that track; afterwards the heading is
  nudged toward the GPS course whenever it drives fairly straight. (The IMU compass is unreliable by the motors.)
- `line` builds a straight route from the start along that initial heading; `route` follows the given points.
- Steering: pure pursuit to a point --lookahead m ahead on the route -> turn rate; wheel speeds from the
  skid-steer model (effective track 0.95 m, motor_cal) with a gyro yaw-rate correction.
- LiDAR guard (robot frame, x forward, y left; LiDAR front at 271.5 deg, chassis returns < 15 cm ignored):
  stop if anything is in the corridor ahead (|y| < --half-width) within --stop-m; half speed within --slow-m;
  stop if anything at all is within --near-m; stop if the LiDAR goes quiet. It resumes on its own once clear.
- Also stops on: button released, GPS fix lost or older than 1 s, motor fault, ~/motor_cal/STOP, --max-s.
Every tick is logged to nav/logs/follow_<time>.json and the track is drawn on the map at the end.
"""
import argparse
import http.server
import json
import math
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import ntrip_rtk                      # noqa: E402
import robot_drive as rd              # noqa: E402
from lidar_odom import scan_to_points  # noqa: E402

TRACK_EFF = 0.95                       # m, effective skid-steer track on tile (motor_cal turn maps)
RTK = ("4", "5")                       # GGA fix qualities trusted for heading (RTK fixed / float)
JUMP_M = 0.5                           # a fix this far from the previous one (at <= 2.5 m/s, 5 Hz) is an outlier
WHEEL_SCALE = 0.94                     # effective/nominal wheel circumference (LiDAR vs encoders, motor_cal)
# Fusion: the pose is dead-reckoned from wheel speed + gyro heading and pulled toward each GPS fix by this gain
# (per 5 Hz fix: 0.05 -> ~4 s time constant). Near buildings RTK float wandered by metres for seconds at a time
# (7 Nov: GPS track straight while wheels + gyro showed a 37 deg left turn), so the GPS only nudges.
GPS_GAIN = {"4": 0.10, "5": 0.05, "2": 0.01, "1": 0.01}
GATE_M = 1.5                           # GPS fixes farther than this from the fused pose are ignored ...
GATE_RESET = 15                        # ... unless this many in a row disagree: then jump to GPS
R_EARTH = 6378137.0
FIX_NAMES = {"0": "no fix", "1": "GPS", "2": "DGPS", "4": "RTK fixed", "5": "RTK float", "6": "dead reckoning"}


# ---------------------------------------------------------------- geometry
class Enu:
    """Small-area east/north metres around an origin."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = lat0, lon0
        self.k = math.cos(math.radians(lat0))

    def to(self, lat, lon):
        return (math.radians(lon - self.lon0) * R_EARTH * self.k, math.radians(lat - self.lat0) * R_EARTH)

    def back(self, e, n):
        return (self.lat0 + math.degrees(n / R_EARTH), self.lon0 + math.degrees(e / (R_EARTH * self.k)))


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def parse_gga(line):
    f = line.split("*")[0].split(",")
    if len(f) < 10 or not f[2] or not f[4] or f[6] in ("", "0"):
        return None
    lat = int(f[2][:2]) + float(f[2][2:]) / 60
    lon = int(f[4][:3]) + float(f[4][3:]) / 60
    if f[3] == "S":
        lat = -lat
    if f[5] == "W":
        lon = -lon
    return dict(lat=lat, lon=lon, q=f[6], sats=int(f[7] or 0), hdop=float(f[8] or 99),
                age=f[13] if len(f) > 13 else "")


def line_fit(pts):
    """Direction of travel (rad, from first to last point), length (m) and RMS scatter (m) of a straight-line fit."""
    if len(pts) < 3:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)                       # principal axis
    c, s_ = math.cos(ang), math.sin(ang)
    along = [(p[0] - mx) * c + (p[1] - my) * s_ for p in pts]
    if along[-1] < along[0]:                                         # point it the way we travelled
        ang += math.pi
    across = [-(p[0] - mx) * s_ + (p[1] - my) * c for p in pts]
    return wrap(ang), max(along) - min(along), (sum(d * d for d in across) / n) ** 0.5


class Path:
    """Polyline in ENU with arc-length lookup for pure pursuit."""

    def __init__(self, pts):
        self.p = pts
        self.s = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.s.append(self.s[-1] + math.dist(a, b))
        self.length = self.s[-1]

    def project(self, x, y, s_hint=0.0, window=6.0):
        """(arc length, cross-track m, + = path is to the left) of the closest point, searching near s_hint."""
        best = (1e9, 0.0, 0.0)
        for i, (a, b) in enumerate(zip(self.p, self.p[1:])):
            if self.s[i + 1] < s_hint - window or self.s[i] > s_hint + window:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
            px, py = a[0] + t * dx, a[1] + t * dy
            d = math.hypot(x - px, y - py)
            if d < best[0]:
                side = math.copysign(d, dx * (py - y) - dy * (px - x))   # >0: path point is left of the robot
                best = (d, self.s[i] + t * math.sqrt(L2), side)
        return best[1], best[2]

    def at(self, s):
        s = max(0.0, min(self.length, s))
        for i in range(len(self.p) - 1):
            if s <= self.s[i + 1] or i == len(self.p) - 2:
                seg = self.s[i + 1] - self.s[i] or 1e-9
                t = (s - self.s[i]) / seg
                a, b = self.p[i], self.p[i + 1]
                return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])


# ---------------------------------------------------------------- hold-to-run page
PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>Robot hold-to-run</title><style>
body{font-family:system-ui;margin:0;padding:16px;background:#111;color:#eee;user-select:none;-webkit-user-select:none}
#b{width:100%;height:46vh;border-radius:18px;border:0;font-size:2em;font-weight:700;background:#2a78d6;color:#fff;touch-action:none}
#b.on{background:#1baf7a}#s{font-size:1.05em;line-height:1.5;margin-top:14px;white-space:pre-wrap}.bad{color:#ff6b6b}
</style></head><body><button id=b>HOLD TO RUN</button><div id=s>connecting…</div><script>
const b=document.getElementById('b');let t=null;
function hold(){fetch('/hold',{method:'POST'}).catch(()=>{});}
function down(e){e.preventDefault();b.classList.add('on');b.textContent='RUNNING';hold();clearInterval(t);t=setInterval(hold,200);}
function up(){clearInterval(t);t=null;b.classList.remove('on');b.textContent='HOLD TO RUN';fetch('/release',{method:'POST'}).catch(()=>{});}
b.addEventListener('pointerdown',down);['pointerup','pointercancel','pointerleave'].forEach(x=>b.addEventListener(x,up));
document.addEventListener('visibilitychange',()=>{if(document.hidden)up();});
setInterval(()=>fetch('/status').then(r=>r.json()).then(j=>{document.getElementById('s').innerHTML=j.html;}).catch(()=>{
document.getElementById('s').innerHTML='<span class=bad>lost the robot</span>';}),400);
</script></body></html>"""


class Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)   # IPv4 and IPv6
        super().server_bind()


def start_page(port, st):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/status"):
                return self._send(200, "application/json", json.dumps({"html": st.get("html", "")}).encode())
            self._send(200, "text/html; charset=utf-8", PAGE.encode())

        def do_POST(self):
            if self.path.startswith("/hold"):
                st["hold_t"] = time.monotonic()
            elif self.path.startswith("/release"):
                st["hold_t"] = 0.0
            self._send(200, "text/plain", b"ok")

    srv = Server(("::", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def page_urls(port):
    out = []
    for fam, flag in ((socket.AF_INET, "-4"), (socket.AF_INET6, "-6")):
        try:
            import subprocess
            r = subprocess.run(["ip", flag, "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
            for line in r.splitlines():
                ip = line.split()[3].split("/")[0]
                out.append(f"http://{ip}:{port}/" if fam == socket.AF_INET else f"http://[{ip}]:{port}/")
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- LiDAR guard
def lidar_check(lid, a):
    """(speed factor 0 / 0.5 / 1, reason or ''). Robot frame: x forward, y left."""
    if time.monotonic() - lid.t > 0.5:
        return 0.0, "LiDAR quiet"
    pts = scan_to_points(lid.scan)
    if len(pts) == 0:
        return 1.0, ""
    x, y = pts[:, 0], pts[:, 1]
    r = (x * x + y * y) ** 0.5
    if (r < a.near_m).any():
        i = r.argmin()
        return 0.0, f"something {r[i]:.2f} m away at {math.degrees(math.atan2(y[i], x[i])):+.0f} deg"
    ahead = (x > 0) & (abs(y) < a.half_width)
    if ahead.any():
        d = x[ahead].min()
        if d < a.stop_m:
            return 0.0, f"obstacle {d:.2f} m ahead"
        if d < a.slow_m:
            return 0.5, f"slowing: obstacle {d:.2f} m ahead"
    return 1.0, ""


# ---------------------------------------------------------------- main loop
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("line", "route"))
    ap.add_argument("route_file", nargs="?", help="route: JSON list of [lat, lon]")
    ap.add_argument("--length", type=float, default=10.0, help="line: metres to drive")
    ap.add_argument("--speed", type=float, default=0.3, help="m/s")
    ap.add_argument("--init-m", type=float, default=2.0, help="straight distance used to find the heading")
    ap.add_argument("--lookahead", type=float, default=1.5, help="pure pursuit look-ahead, m")
    ap.add_argument("--stop-m", type=float, default=0.8, help="stop if something is this close in the path")
    ap.add_argument("--slow-m", type=float, default=2.0, help="half speed if something is this close in the path")
    ap.add_argument("--half-width", type=float, default=0.45, help="half width of the path corridor, m")
    ap.add_argument("--near-m", type=float, default=0.25, help="stop if anything at all is this close")
    ap.add_argument("--min-fix", default="5,4", help="GGA fix qualities allowed to drive (default RTK float/fixed)")
    ap.add_argument("--max-s", type=float, default=180)
    ap.add_argument("--min-speed", type=float, default=0.15,
                    help="never creep slower than this while moving (slow skid-steer turns pivot and stall)")
    ap.add_argument("--gps-gain", type=float, default=1.0,
                    help="scale on how strongly GPS pulls the fused pose (0 = wheels + gyro only after the heading is found)")
    ap.add_argument("--min-radius", type=float, default=1.0, help="tightest turn allowed, m")
    ap.add_argument("--inner-min", type=float, default=0.3, help="inner wheel never below this fraction of the outer")
    ap.add_argument("--port", type=int, default=8100, help="hold-to-run page port")
    ap.add_argument("--no-ntrip", action="store_true", help="don't start the RTK client (plain GPS)")
    ap.add_argument("--no-gps", action="store_true",
                    help="line: no GPS at all. The line runs straight ahead from where the robot points at the start, "
                         "followed by wheels + gyro (tests the controller on its own)")
    a = ap.parse_args()
    ok_fix = set(a.min_fix.split(","))

    # --- GPS + RTK
    rx = ntrip_rtk.Receiver("/dev/ttyAMA0", 230400, "/dev/ttyAMA4")
    nt = {"state": "off", "bytes": 0, "connects": 0, "last_data": 0.0, "types": __import__("collections").Counter()}
    stop_ev = threading.Event()
    if not a.no_ntrip:
        cfg = json.load(open(os.path.expanduser("~/.config/ntrip.json")))
        has_v4 = any(l.startswith("default") for l in os.popen("ip -4 route").read().splitlines())
        if not has_v4 and cfg["host"].count(".") == 3:                  # no IPv4: go through NAT64
            cfg["host"] = "64:ff9b::" + "%x%02x:%x%02x" % tuple(int(x) for x in cfg["host"].split("."))
        threading.Thread(target=ntrip_rtk.ntrip, args=(cfg, rx, nt, stop_ev), daemon=True).start()
        print(f"RTK corrections from {cfg['host']}:{cfg['port']}/{cfg['mountpoint']}", flush=True)

    # --- sensors and motors (robot_drive's classes: LiDAR scans, gyro, STM32 link)
    lid = rd.Lidar(); lid.start()
    imu = rd.Imu(); imu.start()
    mcu = rd.Stm32()
    st = {"hold_t": 0.0, "html": "starting…"}
    srv = start_page(a.port, st)
    print("hold-to-run page: " + "  or  ".join(page_urls(a.port)), flush=True)

    t0 = time.monotonic()
    while time.monotonic() - t0 < 3 and (lid.scan is None or mcu.row is None or imu.t == 0):
        time.sleep(0.05)
    if lid.scan is None or mcu.row is None or imu.t == 0:
        mcu.close(); sys.exit("LiDAR, IMU or STM32 not sending")
    xs = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.5:                                  # gyro bias, standing still
        xs.append(imu.gz); time.sleep(0.01)
    imu.bias = sum(xs) / len(xs); imu.yaw = 0.0

    if a.no_gps:
        if a.mode != "line":
            sys.exit("--no-gps only works with line")
        a.gps_gain = 0.0
        ok_fix = {"0", "1", "2", "4", "5", "6"}
    # --- wait for a usable fix
    print(f"waiting for a fix of type {'/'.join(FIX_NAMES.get(q, q) for q in ok_fix)} …", flush=True)
    while True:
        g = parse_gga(rx.gga.decode(errors="replace")) if rx.gga else None
        q = g["q"] if g else "0"
        st["html"] = (f"waiting for GPS: <b>{FIX_NAMES.get(q, q)}</b>, sats {g['sats'] if g else 0}, "
                      f"correction age {g['age'] if g and g['age'] else '-'}<br>RTK link: {nt['state']}")
        if g and q in ok_fix or a.no_gps:
            break
        if os.path.exists(rd.STOP_FILE):
            mcu.close(); sys.exit("STOP file")
        time.sleep(0.5)
    if g:
        enu = Enu(g["lat"], g["lon"])
        print(f"fix: {FIX_NAMES.get(g['q'])} at {g['lat']:.7f}, {g['lon']:.7f}", flush=True)
    else:
        enu = Enu(40.0, -86.0)                                       # placeholder origin (no GPS used)

    route = None
    if a.mode == "route":
        pts = json.load(open(a.route_file))
        route = Path([enu.to(la, lo) for la, lo in pts])

    S = {"phase": "init", "heading": None, "yaw0": None, "init_start": None, "s": 0.0, "i": 0.0,
         "track": [], "last_gga": None, "pos": None, "pos_t": 0.0, "course_pts": []}
    if a.no_gps:                                                     # robot at (0, 0) facing +x; line straight ahead
        S.update(phase="follow", heading=0.0, yaw0=imu.yaw, fused=(0.0, 0.0))
        route = Path([(0.0, 0.0), (a.length, 0.0)])
        print(f"no GPS: following a {a.length:.1f} m line straight ahead of the start, by wheels + gyro", flush=True)
    log, reason = [], None
    t_start = time.monotonic()
    nxt = t_start
    try:
        while True:
            now = time.monotonic()
            # ---- latest GPS position
            gtxt = rx.gga.decode(errors="replace") if rx.gga else ""
            if gtxt != S["last_gga"]:
                S["last_gga"] = gtxt
                g = parse_gga(gtxt)
                if g:
                    S["fix"] = g
                    p = enu.to(g["lat"], g["lon"])
                    jump = S["pos"] is not None and math.dist(p, S["pos"]) > JUMP_M + 2.5 * (now - S["pos_t"])
                    S["track"].append((round(now - t_start, 2), g["lat"], g["lon"], g["q"]))
                    if jump:
                        S["jumps"] = S.get("jumps", 0) + 1
                        S["course_pts"] = []                          # a jump poisons the heading window
                    else:
                        S["pos"], S["pos_t"] = p, now
                        if g["q"] in RTK:
                            S["course_pts"].append((now, *p, imu.yaw))
                        else:
                            S["course_pts"] = []
                    S["course_pts"] = [q for q in S["course_pts"] if now - q[0] < 3.0]
                    if S["phase"] == "init" and (jump or g["q"] not in RTK):
                        S["init_pts"] = []                            # restart the heading measurement
            fix = S.get("fix")

            # ---- heading: gyro + GPS course
            if S["heading"] is not None:
                head = S["heading"] + (imu.yaw - S["yaw0"])
                cp = S["course_pts"]
                # only with RTK fixed: an RTK float track near buildings was wrong by tens of degrees (7 Nov)
                if (not a.no_gps and fix and fix["q"] == "4" and len(cp) >= 10 and abs(imu.gz) < math.radians(3)
                        and abs(cp[-1][3] - cp[0][3]) < math.radians(4)
                        and S.get("v_cmd", 0) >= a.min_speed and cp[-1][0] - S.get("last_course_t", 0) > 0.5):
                    fit = line_fit([(q[1], q[2]) for q in cp])
                    if fit and fit[1] > 1.0 and fit[2] < 0.10:          # >1 m of straight, clean RTK track
                        course = fit[0]
                        mid_yaw = (cp[-1][3] + cp[0][3]) / 2               # gyro heading at the window's middle
                        err = wrap(course - (S["heading"] + mid_yaw - S["yaw0"]))
                        S["heading"] += max(-math.radians(1.5), min(math.radians(1.5), 0.3 * err))
                        S["last_course_t"] = cp[-1][0]
                        head = S["heading"] + (imu.yaw - S["yaw0"])
            else:
                head = None

            # ---- gyro bias: re-estimated whenever the robot stands still (it wandered +-0.6 deg/s, 7 Nov)
            (mlb, mrb), _ = mcu.wheels()
            if S.get("v_cmd", 0) == 0 and abs(mlb) < 0.5 and abs(mrb) < 0.5 and abs(imu.gz) < 0.03:
                S["still_n"] = S.get("still_n", 0) + 1
                if S["still_n"] > 20:                                  # 1 s still: the motors have stopped
                    imu.bias += 0.02 * imu.gz
            else:
                S["still_n"] = 0

            # ---- fused position: wheels + gyro, nudged by GPS
            (ml_, mr_), _ = mcu.wheels()
            v_odo = (ml_ + mr_) / 2 / 60 * rd.WHEEL_C * WHEEL_SCALE
            dt = now - S.get("fuse_t", now)
            S["fuse_t"] = now
            if S.get("fused") is not None and head is not None:
                fx, fy = S["fused"]
                S["fused"] = (fx + v_odo * dt * math.cos(head), fy + v_odo * dt * math.sin(head))
            if not a.no_gps and S["pos"] is not None and S["pos_t"] == now and fix:
                if S.get("fused") is None or head is None:
                    S["fused"] = S["pos"]                             # until the heading is known: raw GPS
                else:
                    e = (S["pos"][0] - S["fused"][0], S["pos"][1] - S["fused"][1])
                    if a.gps_gain <= 0:
                        pass                                          # dead reckoning only
                    elif math.hypot(*e) > GATE_M:
                        S["gated"] = S.get("gated", 0) + 1
                        S["gate_run"] = S.get("gate_run", 0) + 1
                        if S["gate_run"] >= GATE_RESET:
                            S["fused"], S["gate_run"] = S["pos"], 0
                            S["resets"] = S.get("resets", 0) + 1
                    else:
                        S["gate_run"] = 0
                        k = GPS_GAIN.get(fix["q"], 0.0) * a.gps_gain
                        S["fused"] = (S["fused"][0] + k * e[0], S["fused"][1] + k * e[1])

            # ---- stop conditions
            held = now - st["hold_t"] < 0.6
            lid_k, lid_why = lidar_check(lid, a)
            why = None
            if os.path.exists(rd.STOP_FILE):
                why = "STOP file"
            elif now - t_start > a.max_s:
                why = "time limit"
            elif now - mcu.t > 0.5:
                why = "no STM32 telemetry"
            if not why and ("FAULT" in mcu.flags or "stall2" in mcu.flags):
                S["stalls"] = S.get("stalls", 0) + 1
                print(f"{now - t_start:6.1f} s: motor stall fault #{S['stalls']}: clearing it, pausing 1 s", flush=True)
                mcu.drive(0.0, 0.0); mcu.ser.write(b"reset\n"); time.sleep(1.0)
                if S["stalls"] > 3:
                    why = "motor stalled 4 times"
            if why:
                reason = why
                break
            pause = None
            if not held:
                pause = "button not held"
            elif not a.no_gps and (not fix or fix["q"] not in ok_fix or now - S["pos_t"] > 1.0):
                pause = f"GPS: {FIX_NAMES.get(fix['q'], fix['q']) if fix else 'none'}" + (" (stale)" if now - S["pos_t"] > 1.0 else "")
            elif lid_k == 0.0:
                pause = lid_why

            # ---- no-GPS line: it starts from the robot's pose the first time the button is held
            if a.no_gps and not S.get("armed") and held:
                S.update(armed=True, yaw0=imu.yaw, fused=(0.0, 0.0), s=0.0, i=0.0)
                print(f"{now - t_start:6.1f} s: button held: line starts here, straight ahead", flush=True)
            if a.no_gps and not S.get("armed"):
                pause = pause or "press and hold to start the line from here"

            # ---- control
            v = w = 0.0
            x, y = S["pos"] if S["pos"] else (0.0, 0.0)
            xt = None
            if S["phase"] == "init":
                ip = S.setdefault("init_pts", [])
                if fix and fix["q"] in RTK and S["pos_t"] == now and (not ip or ip[-1][:2] != tuple(S["pos"])):
                    ip.append((*S["pos"], imu.yaw))
                moved = math.dist(ip[0][:2], ip[-1][:2]) if len(ip) >= 2 else 0.0
                fit = line_fit([q[:2] for q in ip]) if len(ip) >= 8 else None
                if moved >= a.init_m and fit and fit[2] < 0.15:
                    ix, iy = ip[0][:2]
                    mid_yaw = sum(q[2] for q in ip) / len(ip)
                    S["heading"] = fit[0] - (mid_yaw - imu.yaw)               # heading now = course + gyro since
                    S["yaw0"] = imu.yaw
                    print(f"heading fit: {len(ip)} RTK points over {moved:.2f} m, scatter {fit[2] * 100:.1f} cm", flush=True)
                    if a.mode == "line":
                        h = fit[0]
                        route = Path([(ix, iy), (ix + a.length * math.cos(h), iy + a.length * math.sin(h))])
                    S["phase"] = "follow"
                    S["s"] = route.project(x, y, 0.0, window=1e9)[0]
                    print(f"heading from the first {moved:.1f} m: {math.degrees(S['heading']):.1f} deg (from east, CCW); "
                          f"route {route.length:.1f} m, now at {S['s']:.1f} m", flush=True)
                else:
                    v, w = a.speed * 0.7, 0.0                           # straight, gyro holds zero turn
            if S["phase"] == "follow":
                head = S["heading"] + (imu.yaw - S["yaw0"])
                x, y = S["fused"]                                      # fused pose, not raw GPS
                S["s"], xt = route.project(x, y, S["s"])
                if S["s"] >= route.length - 0.3:
                    reason = "arrived"
                    break
                tx, ty = route.at(S["s"] + a.lookahead)
                alpha = wrap(math.atan2(ty - y, tx - x) - head)
                Ld = math.hypot(tx - x, ty - y) or a.lookahead
                v = a.speed * min(1.0, (route.length - S["s"]) / 1.0 + 0.3)
                k = 2 * math.sin(alpha) / Ld                             # pure pursuit curvature
                k = max(-1 / a.min_radius, min(1 / a.min_radius, k))    # no tighter than min_radius: no pivots
                w = v * k
            if not pause and v > 0:
                f = lid_k
                v, w = v * f, w * f
                if v < a.min_speed:                                       # creeping + turning = pivot = stall
                    w *= a.min_speed / v
                    v = a.min_speed
            if pause or v <= 0:
                v = w = 0.0
                S["i"] = 0.0
            else:
                err = w - imu.gz                                         # gyro yaw-rate correction
                S["i"] = max(-0.2, min(0.2, S["i"] + err / 20))
                w_cmd = w + 0.4 * err + 1.0 * S["i"]
                w_cmd = max(-v / a.min_radius, min(v / a.min_radius, w_cmd))
                vl, vr = v - w_cmd * TRACK_EFF / 2, v + w_cmd * TRACK_EFF / 2
                lo = a.inner_min * max(vl, vr)                           # inner wheel keeps rolling forward
                vl, vr = max(vl, lo), max(vr, lo)
            S["v_cmd"] = v
            if pause or v <= 0:
                mcu.drive(0.0, 0.0)
            else:
                mcu.drive(rd.rpm_for(vl), rd.rpm_for(vr))

            # ---- status + log
            fx = fix or {}
            st["html"] = (f"<b>{'PAUSED: ' + pause if pause else ('RUNNING' if S['phase'] == 'follow' else 'finding heading')}</b>"
                          f"{'<br>' + lid_why if lid_why and not pause else ''}<br>"
                          f"GPS {FIX_NAMES.get(fx.get('q'), '?')}, {fx.get('sats', 0)} sats, age {fx.get('age') or '-'}<br>"
                          f"progress {S['s']:.1f} / {route.length if route else a.length:.1f} m"
                          f"{f', off line {xt:+.2f} m' if xt is not None else ''}<br>"
                          f"heading {math.degrees(head) if head is not None else float('nan'):.0f} deg, speed {v:.2f} m/s")
            (ml, mr), _ = mcu.wheels()
            gx, gy = S["pos"] if S["pos"] else (float("nan"), float("nan"))
            log.append(dict(t=round(now - t_start, 3), phase=S["phase"], x=round(x, 3), y=round(y, 3),
                            gps_x=round(gx, 3), gps_y=round(gy, 3),
                            fix=fx.get("q"), s=round(S["s"], 2), xt=None if xt is None else round(xt, 3),
                            head=None if head is None else round(math.degrees(head), 2), v=round(v, 3),
                            w=round(w, 3), gz=round(imu.gz, 4), ml=ml, mr=mr, pause=pause, lidar=lid_why))
            nxt += 0.05
            time.sleep(max(0.0, nxt - time.monotonic()))
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        mcu.stop()
        stop_ev.set()
        st["html"] = f"<b>STOPPED: {reason}</b>"
        print(f"stopped: {reason}", flush=True)
        os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = os.path.join(HERE, "logs", f"follow_{a.mode}_{stamp}.json")
        route_ll = [enu.back(*p) for p in route.p] if route else []
        json.dump(dict(args=vars(a), reason=reason, origin=[enu.lat0, enu.lon0], route=route_ll,
                       track=S["track"], log=log), open(out, "w"))
        print(f"log: {out}", flush=True)
        print(f"GPS jumps rejected: {S.get('jumps', 0)}, GPS fixes ignored by the fusion gate: {S.get('gated', 0)} "
              f"(resets to GPS: {S.get('resets', 0)}), stall faults: {S.get('stalls', 0)}", flush=True)
        if S.get("fused") is not None and S["pos"] is not None:
            print(f"at the end the GPS and the fused pose differed by {math.dist(S['fused'], S['pos']):.2f} m", flush=True)
        f = [r for r in log if r["phase"] == "follow" and r["xt"] is not None and not r["pause"]]
        if f:
            xts = [abs(r["xt"]) for r in f]
            print(f"off-line distance while following: mean {sum(xts) / len(xts):.2f} m, max {max(xts):.2f} m, "
                  f"progress {S['s']:.1f} of {route.length:.1f} m", flush=True)
        if S["track"] and route_ll:
            json.dump([[p[1], p[2]] for p in S["track"]], open(out.replace(".json", "_track.json"), "w"))
            json.dump(route_ll, open(out.replace(".json", "_route.json"), "w"))
        time.sleep(0.5)
        imu.close(); mcu.close()


if __name__ == "__main__":
    main()
