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
try:
    time.sleep(10)
    s.write(b"reset\nrate 20\n"); time.sleep(0.3); s.reset_input_buffer()
    for name, pfx, i in (("motor 1", "", 1), ("motor 2", "m2 ", 6)):
        print(time.strftime("%H:%M:%S"), name, "start", flush=True)
        rows = run(f"{pfx}open 15", 8.0)
        c0, c1 = rows[0][i + 3], rows[-1][i + 3]
        late = rows[len(rows)//3:]
        other = 5 if i == 1 else 0
        print(f"   {name}: {sum(r[i] for r in late)/len(late):.1f} RPM, {c1 - c0:.0f} counts = {(c1 - c0)/751.8:.2f} output-shaft turns; "
              f"other encoder moved {rows[-1][other + 4] - rows[0][other + 4]:.0f} counts", flush=True)
        run(f"{pfx}stop", 4.0)
    print("done", flush=True)
finally:
    s.write(b"stop\n"); time.sleep(0.1); s.write(b"rate 10\n"); time.sleep(0.1); s.close()
