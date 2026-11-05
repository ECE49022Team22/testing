import re, time, serial, json
TEL = re.compile(r"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+) "
                 r"tgt2=(-?[\d.]+) meas2=(-?[\d.]+) duty2=(-?[\d.]+)% cap2=(-?[\d.]+)% cnt2=(-?\d+)(.*)")
s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.2)
def run(cmds, sec):
    for c in cmds: s.write((c + "\n").encode())
    rows = []; end = time.time() + sec
    while time.time() < end:
        m = TEL.match(s.readline().decode(errors="replace").strip())
        if m: rows.append([float(x) for x in m.groups()[:10]] + [m.group(11)])
    return rows
res = {}
try:
    s.write(b"reset\nrate 20\n"); time.sleep(0.3); s.reset_input_buffer()
    for sign in (1, -1):
        for d in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            duty = sign * d
            rows = run([f"open {duty}", f"m2 open {duty}"], 2.5)
            late = rows[len(rows) // 2:]
            if any("FAULT" in r[10] or "stall2" in r[10] for r in rows): print("FAULT", duty, flush=True)
            m1 = sum(r[1] for r in late) / len(late); m2 = sum(r[6] for r in late) / len(late)
            res[duty] = (m1, m2)
            print(f"{duty:+4d}%  motor1 {m1:7.1f} RPM   motor2 {m2:7.1f} RPM", flush=True)
        run(["stop"], 2.5)
    json.dump(res, open("sweep.json", "w"))
    print("done", flush=True)
finally:
    s.write(b"stop\n"); time.sleep(0.1); s.write(b"rate 10\n"); time.sleep(0.1); s.close()
