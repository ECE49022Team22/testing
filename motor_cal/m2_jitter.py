import re, time, serial
TEL = re.compile(r"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+) "
                 r"tgt2=(-?[\d.]+) meas2=(-?[\d.]+) duty2=(-?[\d.]+)% cap2=(-?[\d.]+)% cnt2=(-?\d+)(.*)")
s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.2)
def run(cmd, sec):
    s.write((cmd + "\n").encode()); rows = []; end = time.time() + sec
    while time.time() < end:
        m = TEL.match(s.readline().decode(errors="replace").strip())
        if m: rows.append([float(x) for x in m.groups()[:10]])
    return rows
def stats(rows, i, tgt):
    late = [r[i] for r in rows[len(rows) // 2:]]
    avg = sum(late) / len(late); sd = (sum((x - avg) ** 2 for x in late) / len(late)) ** 0.5
    peak = max(abs(r[i]) for r in rows)
    return f"mean {avg:+6.1f} jit {sd:3.1f} over {max(0, (peak - abs(tgt)) / abs(tgt) * 100):4.1f}%"
try:
    s.write(b"reset\nrate 50\n"); time.sleep(0.3)
    for kp in (0.089, 0.066):
        run(f"m2 kp {kp}", 0.2)
        for label, both in (("m2 alone", False), ("both    ", True)):
            for v in (60, 120):
                rows = run(f"d {-v if both else 0} {v}", 3.0)
                print(f"m2 Kp {kp:.3f} {label} {v:4d} RPM: m2 {stats(rows, 6, v)}" + (f" | m1 {stats(rows, 1, -v)}" if both else ""), flush=True)
            run("stop", 2.0)
    run("m2 kp 0.089", 0.2)
    print("done", flush=True)
finally:
    s.write(b"stop\n"); time.sleep(0.1); s.write(b"rate 10\n"); time.sleep(0.1); s.close()
