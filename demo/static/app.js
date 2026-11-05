"use strict";
// Live dashboard: renders the hub's state (Server-Sent Events, 10 Hz).

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
let S = null;            // latest state
let pending = false;

// ---------------------------------------------------------------- theme
(function theme() {
  let saved = null;
  try { saved = localStorage.getItem("demo-theme"); } catch (e) { /* storage blocked */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("demo-theme", document.documentElement.dataset.theme); } catch (e) { /* ignore */ }
    if (S) render();
  });
})();

// ---------------------------------------------------------------- status
const STATE = {
  ok: ["ok", "live"], starting: ["warn", "starting"], nodata: ["warn", "no data"],
  disconnected: ["bad", "not connected"], error: ["bad", "error"], stale: ["bad", "stopped"], missing: ["bad", "not running"],
};
function workerState(name) {
  const w = S.workers[name];
  if (!w) return { key: "missing", detail: "worker not started" };
  if (S.now - w.seen > 3) return { key: "stale", detail: "no messages for " + Math.round(S.now - w.seen) + " s" };
  const st = w.status || {};
  return { key: st.state || "starting", detail: st.detail || "" };
}
function chip(el, key) {
  const [cls, label] = STATE[key] || ["", key];
  el.className = "chip " + cls;
  el.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(label);
}
const stat = (k, v, unit = "") => `<div class="stat"><div class="v">${v}${unit ? "<small>" + unit + "</small>" : ""}</div><div class="k">${esc(k)}</div></div>`;
const stats = (name) => (S.workers[name] || {}).stats || {};
const data = (name) => (S.workers[name] || {}).data || {};

// ---------------------------------------------------------------- canvas helpers
function fit(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight || Number(canvas.getAttribute("height"));
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    canvas.style.height = h + "px";
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return [ctx, w, h];
}

// ---------------------------------------------------------------- sparklines (one series each)
const sparks = [];
document.querySelectorAll(".spark").forEach((el) => {
  el.innerHTML = `<div class="title">${esc(el.dataset.title)}</div><canvas height="84"></canvas><div class="tip"></div>`;
  const sp = { el, key: el.dataset.hist, canvas: el.querySelector("canvas"), tip: el.querySelector(".tip"), hover: null, geo: null };
  sp.canvas.addEventListener("mousemove", (e) => { sp.hover = e.offsetX; drawSpark(sp); });
  sp.canvas.addEventListener("mouseleave", () => { sp.hover = null; sp.tip.style.display = "none"; drawSpark(sp); });
  sparks.push(sp);
});
function budgetFor(key) {
  const d = (S.deadlines || []).find((x) => x.worker + "." + x.key === key);
  return d ? d.budget : null;
}
function drawSpark(sp) {
  if (!S) return;
  const [ctx, w, h] = fit(sp.canvas);
  const hist = S.history[sp.key] || [];
  const budget = budgetFor(sp.key);
  const pad = { l: 34, r: 8, t: 6, b: 16 };
  const span = 120, t1 = S.now, t0 = t1 - span;
  const pts = hist.filter((p) => p[0] >= t0);
  const top = Math.max(budget ? budget * 1.15 : 0, ...pts.map((p) => p[1] * 1.1), 1);
  const x = (t) => pad.l + ((t - t0) / span) * (w - pad.l - pad.r);
  const y = (v) => pad.t + (1 - Math.min(v, top) / top) * (h - pad.t - pad.b);
  ctx.clearRect(0, 0, w, h);
  ctx.font = "11px system-ui, sans-serif";
  // grid + axis
  ctx.strokeStyle = css("--grid"); ctx.lineWidth = 1;
  [0, top / 2, top].forEach((v) => { ctx.beginPath(); ctx.moveTo(pad.l, y(v) + 0.5); ctx.lineTo(w - pad.r, y(v) + 0.5); ctx.stroke(); });
  ctx.fillStyle = css("--text-muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
  ctx.fillText(fmt(top, top < 10 ? 1 : 0), pad.l - 4, y(top)); ctx.fillText("0", pad.l - 4, y(0));
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
  ctx.fillText("−2 min", pad.l, h - 3); ctx.textAlign = "right"; ctx.fillText("now", w - pad.r, h - 3);
  // budget
  if (budget) {
    ctx.strokeStyle = css("--critical"); ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, y(budget) + 0.5); ctx.lineTo(w - pad.r, y(budget) + 0.5); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = css("--text-secondary"); ctx.textAlign = "left"; ctx.textBaseline = "bottom";
    ctx.fillText("budget " + fmt(budget, 0) + " ms", pad.l + 4, y(budget) - 2);
  }
  // series (2px line)
  if (pts.length > 1) {
    ctx.strokeStyle = css("--series-1"); ctx.lineWidth = 2; ctx.lineJoin = "round";
    ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(x(p[0]), y(p[1])) : ctx.moveTo(x(p[0]), y(p[1])))); ctx.stroke();
  }
  // hover crosshair + tooltip
  if (sp.hover !== null && pts.length) {
    const tAt = t0 + ((sp.hover - pad.l) / (w - pad.l - pad.r)) * span;
    const p = pts.reduce((a, b) => (Math.abs(b[0] - tAt) < Math.abs(a[0] - tAt) ? b : a));
    ctx.strokeStyle = css("--axis"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x(p[0]) + 0.5, pad.t); ctx.lineTo(x(p[0]) + 0.5, h - pad.b); ctx.stroke();
    ctx.fillStyle = css("--series-1"); ctx.strokeStyle = css("--surface-1"); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x(p[0]), y(p[1]), 4, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    sp.tip.innerHTML = `${fmt(S.now - p[0], 0)} s ago · p99 <b>${fmt(p[1], 2)}</b> ms · max ${fmt(p[2], 2)} ms`;
    sp.tip.style.display = "block";
    const tx = Math.min(Math.max(0, x(p[0]) - sp.tip.offsetWidth / 2), w - sp.tip.offsetWidth);
    sp.tip.style.left = tx + "px"; sp.tip.style.top = "-6px";
  }
}

// ---------------------------------------------------------------- IMU horizon
function drawHorizon() {
  const c = $("horizon"); const [ctx, w, h] = fit(c);
  const d = data("imu"); const [roll, pitch] = d.rpy || [0, 0, 0];
  ctx.clearRect(0, 0, w, h);
  ctx.save();
  ctx.beginPath(); ctx.roundRect(0, 0, w, h, 8); ctx.clip();
  ctx.translate(w / 2, h / 2); ctx.rotate((-roll * Math.PI) / 180);
  const off = pitch * (h / 90);
  ctx.fillStyle = css("--horizon-sky"); ctx.fillRect(-w, -2 * h + off, 2 * w, 2 * h);
  ctx.fillStyle = css("--horizon-ground"); ctx.fillRect(-w, off, 2 * w, 2 * h);
  ctx.strokeStyle = css("--text-primary"); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(-w, off); ctx.lineTo(w, off); ctx.stroke();
  ctx.restore();
  // fixed aircraft symbol
  ctx.strokeStyle = css("--text-primary"); ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(w / 2 - 40, h / 2); ctx.lineTo(w / 2 - 12, h / 2); ctx.moveTo(w / 2 + 12, h / 2); ctx.lineTo(w / 2 + 40, h / 2); ctx.stroke();
  ctx.fillStyle = css("--text-primary"); ctx.font = "600 12px system-ui, sans-serif"; ctx.textAlign = "left";
  const [r, p, yw] = d.rpy || [null, null, null];
  ctx.fillText(`roll ${fmt(r)}°   pitch ${fmt(p)}°   yaw ${fmt(yw)}°`, 10, h - 10);
}

// ---------------------------------------------------------------- LiDAR (top view, forward up)
function drawLidar() {
  const c = $("lidar"); const [ctx, w, h] = fit(c);
  const sc = data("lidar"); const bins = (S.workers.lidar && S.workers.lidar.scan && S.workers.lidar.scan.bins) || [];
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 14;
  const d = bins.filter((v) => v > 0).sort((a, b) => a - b);
  const p90 = d.length ? d[Math.floor(d.length * 0.9)] / 1000 : 4;
  const maxR = [1, 2, 4, 6, 8, 12].find((m) => m >= p90) || 12;
  ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--text-muted"); ctx.font = "11px system-ui, sans-serif"; ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, 2 * Math.PI); ctx.stroke();
    ctx.fillText(fmt(maxR * f, maxR * f < 2 ? 1 : 0) + " m", cx + 3, cy - R * f - 2);
  });
  ctx.beginPath(); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.stroke();
  ctx.fillStyle = css("--series-1");
  bins.forEach((mm, deg) => {
    if (!mm) return;
    const r = Math.min(mm / 1000, maxR) / maxR * R;
    const a = (deg * Math.PI) / 180;              // 0 deg = forward (up), clockwise
    ctx.fillRect(cx + r * Math.sin(a) - 1.5, cy - r * Math.cos(a) - 1.5, 3, 3);
  });
  ctx.fillStyle = css("--text-primary");
  ctx.beginPath(); ctx.moveTo(cx, cy - 7); ctx.lineTo(cx - 5, cy + 5); ctx.lineTo(cx + 5, cy + 5); ctx.closePath(); ctx.fill();
  if (!bins.length) { ctx.fillStyle = css("--text-secondary"); ctx.textAlign = "center"; ctx.fillText("no scan", cx, cy + 24); ctx.textAlign = "left"; }
}

// ---------------------------------------------------------------- tiles
function renderVision() {
  const s = stats("vision");
  const img = $("video");
  if (s.stream_port && !img.dataset.src) {
    img.dataset.src = `${location.protocol}//${location.hostname}:${s.stream_port}/stream.mjpg`;
    img.onload = () => { $("video-none").style.display = "none"; };
    img.onerror = () => { $("video-none").style.display = "flex"; $("video-none").textContent = "video stream unavailable"; delete img.dataset.src; };
    img.src = img.dataset.src;
  }
  if (img.naturalWidth > 0) $("video-none").style.display = "none";   // MJPEG doesn't reliably fire onload
  const e = s.e2e_ms || {}, inf = s.infer_ms || {}, age = s.age_ms || {};
  $("vision-stats").innerHTML = stat("frames / s", fmt(s.fps, 1)) + stat("capture → detection p50", fmt(e.p50, 0), "ms") +
    stat("p99", fmt(e.p99, 0), "ms") + stat("inference p50", fmt(inf.p50, 0), "ms") + stat("frame age", fmt(age.p50, 0), "ms") +
    stat("detector", esc(s.backend || "–"));
  const cf = $("confirm");
  cf.className = "confirm" + (s.confirmed ? " on" : "");
  cf.textContent = s.confirmed ? `STOP SIGN CONFIRMED (3 frames, score ${fmt(s.best, 2)})` : s.best ? `candidate, score ${fmt(s.best, 2)}` : "no stop sign";
}
function renderImu() {
  const s = stats("imu"), l = s.int_latency_ms || {}, p = s.period_ms || {};
  $("imu-stats").innerHTML = stat("samples / s", fmt(s.rate_hz, 0)) + stat("interrupt p99", fmt(l.p99, 2), "ms") +
    stat("interrupt max", fmt(l.max, 2), "ms") + stat("period p99", fmt(p.p99, 1), "ms") +
    stat("late samples", s.late ?? "–") + stat("watchdog resets", s.resets ?? "–");
  drawHorizon();
}
function renderLidar() {
  const s = stats("lidar"), e = s.excess_ms || {}, sc = (S.workers.lidar || {}).scan || {};
  $("lidar-stats").innerHTML = stat("scans / s", fmt(s.scan_hz, 1)) + stat("delivery p99", fmt(e.p99, 1), "ms") +
    stat("points / scan", sc.points ?? "–") + stat("nearest ahead", sc.fwd_min_mm ? fmt(sc.fwd_min_mm / 1000, 2) : "–", "m") +
    stat("CRC errors", s.crc_errors ?? "–") + stat("rejected", s.rejected ?? "–");
  drawLidar();
}
function renderGps() {
  const s = stats("gps"), d = data("gps"), j = s.gga_jitter_ms || {}, pp = s.pps_to_gga_ms || {};
  const pos = d.lat != null ? `${fmt(d.lat, 6)}, ${fmt(d.lon, 6)}` : "–";
  $("gps-kv").innerHTML = `<span class="k">fix</span><span>${esc(d.fix || "–")}</span><span class="k">satellites</span><span>${d.sats ?? "–"}${d.hdop ? " · HDOP " + fmt(d.hdop, 1) : ""}</span>` +
    `<span class="k">position</span><span>${pos}</span><span class="k">altitude</span><span>${d.alt_m != null ? fmt(d.alt_m, 1) + " m" : "–"}</span>`;
  $("gps-stats").innerHTML = stat("fixes / s", fmt(s.gga_hz, 1)) + stat("timing p99", fmt(j.p99, 1), "ms") + stat("timing max", fmt(j.max, 1), "ms") +
    stat("PPS pulses", s.pps_pulses ?? "–") + stat("PPS → fix", fmt(pp.p50, 0), "ms");
}
const ROLE_COLOR = (role) => (/sensor/.test(role) ? "--series-1" : /vision/.test(role) ? "--series-2" : /shared/.test(role) ? "--shared" : "--series-3");
function renderSystem() {
  const sys = S.system || {}, roles = S.roles || {};
  $("sys-iface").textContent = `governor ${sys.governor || "–"} · ${fmt(sys.freq_mhz, 0)} MHz · isolated cores: ${sys.isolated || "none"}`;
  const seen = [...new Set(Object.keys(roles).filter((k) => k !== "about").map((k) => roles[k]))];
  $("legend").innerHTML = seen.map((r) => `<span style="--c: var(${ROLE_COLOR(r)})">${esc(r)}</span>`).join("");
  $("cores").innerHTML = (sys.cores || []).map((c) => {
    const role = roles[String(c.core)] || "";
    return `<div class="core"><span>core ${c.core}</span><div class="bar" role="img" aria-label="core ${c.core} ${fmt(c.util, 0)} percent busy">` +
      `<div class="fill" style="width:${Math.min(100, c.util)}%; background: var(${ROLE_COLOR(role)})"></div></div><span class="num">${fmt(c.util, 0)}%</span>` +
      `<span class="role">${esc(role)}</span></div>`;
  }).join("");
  $("procs").innerHTML = (sys.procs || []).map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.allowed)}</td><td>${esc((p.cores || []).join(","))}</td>` +
    `<td>${p.policy === "FIFO" ? "real-time, priority " + p.prio : esc(p.policy)}</td><td class="num">${fmt(p.cpu_pct, 1)}%</td>` +
    `<td class="num">${p.preempt_s ?? "–"}</td></tr>`).join("");
  const thr = sys.throttled;
  const thrText = thr == null ? "–" : thr === "0x0" ? '<span class="okt">✓ never</span>' :
    (parseInt(thr, 16) & 0x5 ? '<span class="badt">✕ now</span>' : '<span class="badt">! earlier since boot</span>') + " (" + esc(thr) + ")";
  $("sys-kv").innerHTML = `<span class="k">temperature</span><span>${fmt(sys.temp_c, 1)} °C</span>` +
    `<span class="k">under-voltage / throttling</span><span>${thrText}</span>` +
    `<span class="k">5 V input</span><span>${fmt(sys.ext5v_v, 2)} V</span><span class="k">CPU core current</span><span>${fmt(sys.vdd_core_a, 2)} A</span>`;
}
function renderCell() {
  const d = data("cell"), hb = d.heartbeat;
  const age = hb ? Math.round((Date.now() - Date.parse(hb.time.replace(" ", "T").replace("Z", "") + "Z")) / 1000) : null;
  $("cell-kv").innerHTML = `<span class="k">receiver</span><span>${d.receiver ? "running" : d.receiver === false ? "stopped" : "–"}</span>` +
    `<span class="k">Notehub</span><span>${hb ? esc(hb.hub) : "–"}</span>` +
    `<span class="k">signal</span><span>${hb ? `${hb.bars} bar${hb.bars === 1 ? "" : "s"} · RSSI ${hb.rssi} · RSRP ${hb.rsrp} · SINR ${hb.sinr} (${esc(hb.rat)})` : "–"}</span>` +
    `<span class="k">last heartbeat</span><span>${age != null && age >= 0 ? age + " s ago" : "–"}</span>`;
  $("cell-events").innerHTML = (d.events || []).slice().reverse().map((e) => `<div>${esc(e.time.slice(11, 19))} ${esc(e.msg)}</div>`).join("");
}
function drawRobot(d, max) {
  const [ctx, w, h] = fit($("robot"));
  ctx.clearRect(0, 0, w, h);
  const bw = Math.min(150, w * 0.42), bh = h - 40, cx = w / 2, top = 20;
  ctx.fillStyle = css("--surface-2"); ctx.strokeStyle = css("--axis"); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(cx - bw / 2, top, bw, bh, 10); ctx.fill(); ctx.stroke();
  ctx.fillStyle = css("--text-muted"); ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "center";
  ctx.fillText("▲ front", cx, top + 16);
  // one speed bar per wheel, centred on 0: fill = measured, tick = target
  const ww = 22, mid = top + bh / 2, half = bh / 2 - 8;
  for (const [side, x] of [["left", cx - bw / 2 - ww - 8], ["right", cx + bw / 2 + 8]]) {
    const wd = d[side] || {}, ok = wd.meas !== undefined;
    ctx.fillStyle = css("--surface-2"); ctx.beginPath(); ctx.roundRect(x, top, ww, bh, 5); ctx.fill();
    ctx.strokeStyle = css("--axis"); ctx.beginPath(); ctx.moveTo(x - 3, mid); ctx.lineTo(x + ww + 3, mid); ctx.stroke();
    if (ok) {
      const y = (v) => mid - Math.max(-1, Math.min(1, v / max)) * half;
      ctx.fillStyle = (wd.flags || []).length ? css("--critical") : css("--series-1");
      const ym = y(wd.meas);
      ctx.fillRect(x + 3, Math.min(mid, ym), ww - 6, Math.abs(ym - mid));
      ctx.strokeStyle = css("--text-primary"); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x - 4, y(wd.tgt)); ctx.lineTo(x + ww + 4, y(wd.tgt)); ctx.stroke(); ctx.lineWidth = 1;
    }
    ctx.fillStyle = css("--text-secondary"); ctx.textAlign = "center";
    ctx.fillText(side, x + ww / 2, top + bh + 15);
    ctx.fillStyle = css("--text-primary"); ctx.font = "600 13px system-ui, sans-serif";
    ctx.fillText(ok ? fmt(wd.meas, 0) : "–", x + ww / 2, top - 6); ctx.font = "12px system-ui, sans-serif";
  }
  const l = (d.left || {}).meas, r = (d.right || {}).meas;
  let what = "stopped";
  if (l !== undefined && (Math.abs(l) > 2 || Math.abs(r) > 2)) {
    what = Math.abs(l - r) < 0.2 * Math.max(Math.abs(l), Math.abs(r)) ? (l > 0 ? "driving forward" : "driving backward")
      : Math.sign(l) !== Math.sign(r) && Math.abs(l + r) < 0.3 * Math.abs(l - r) ? (l > r ? "spinning right" : "spinning left")
      : l > r ? "curving right" : "curving left";
  }
  ctx.fillStyle = css("--text-secondary"); ctx.textAlign = "center"; ctx.fillText(what, cx, mid + 4);
}
function renderMotor() {
  const s = stats("motor"), d = data("motor"), r = s.cmd_rtt_ms || {}, dl = s.telem_delivery_ms || {};
  const wl = d.left || {}, wr = d.right || {}, wh = s.wheels || {};
  const head = (side) => `${side}<br><span class="muted">motor ${(wh[side] || {}).motor ?? "–"}${(wh[side] || {}).sign === -1 ? ", reversed" : ""}</span>`;
  $("wh-left").innerHTML = head("left"); $("wh-right").innerHTML = head("right");
  const flags = (w) => (w.flags || []).length ? `<span class="badt">${esc(w.flags.join(", "))}</span>` : (w.flags ? '<span class="okt">none</span>' : "–");
  const row = (k, f) => `<tr><td>${k}</td><td class="num">${f(wl)}</td><td class="num">${f(wr)}</td></tr>`;
  $("wheel-rows").innerHTML = row("target", (w) => fmt(w.tgt, 1) + " RPM") + row("measured", (w) => fmt(w.meas, 1) + " RPM") +
    row("duty · cap", (w) => `${fmt(w.duty, 1)}% · ${fmt(w.cap, 0)}%`) + row("encoder", (w) => w.cnt ?? "–") + row("faults", flags);
  drawRobot(d, s.max_rpm || 190);
  $("motor-stats").innerHTML = stat("commands / s", fmt(s.cmd_hz, 0)) + stat("ack p50", fmt(r.p50, 1), "ms") + stat("ack p99", fmt(r.p99, 1), "ms") +
    stat("no reply", s.timeouts ?? "–") + stat("telemetry / s", fmt(s.tel_hz, 0)) + stat("telemetry delivery p99", fmt(dl.p99, 1), "ms");
}
// ---------------------------------------------------------------- motor control
// The worker drops a dashboard target unless it's renewed within ~1 s, so while driving the page
// re-sends it every 300 ms. Releasing the pad, Stop, Esc, hiding the tab or closing it all stop.
// Targets are wheel RPM in the robot's frame: [left, right], + = forward.
const motor = { mode: null, dir: null, timer: null, err: null };   // mode: null | "pad" | "wheels"
function motorPost(body) {
  return fetch("/motor", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => { motor.err = r.ok ? null : "the hub refused the command (" + r.status + ")"; })
    .catch(() => { motor.err = "can't reach the Pi: the motors stop within a second"; });
}
const num = (id) => Number($(id).value);
function motorTargets() {
  if (motor.mode === "wheels") return [num("m-left"), num("m-right")];
  const v = num("m-speed"), t = num("m-turn");
  return { fwd: [v, v], back: [-v, -v], left: [-t, t], right: [t, -t] }[motor.dir] || [0, 0];
}
function motorStart(mode, dir) {
  motor.mode = mode; motor.dir = dir || null;
  motorPost({ drive: motorTargets() });
  clearInterval(motor.timer);
  motor.timer = setInterval(() => motorPost({ drive: motorTargets() }), 300);
  motorUi();
}
function motorStop() {
  const was = motor.mode;
  motor.mode = null; motor.dir = null;
  clearInterval(motor.timer);
  motor.timer = null;
  motorPost({ cmd: "stop" });
  motorUi();
  return was;
}
const rpmText = (v) => (v > 0 ? "+" : "") + v + " RPM";
function motorUi() {
  for (const id of ["m-left", "m-right"]) $(id + "-v").textContent = rpmText(num(id));
  for (const id of ["m-speed", "m-turn"]) $(id + "-v").textContent = num(id) + " RPM";
  $("motor-ctl").classList.toggle("driving", !!motor.mode);
  document.querySelectorAll("#m-pad button").forEach((b) => b.classList.toggle("on", motor.mode === "pad" && motor.dir === b.dataset.dir));
  $("m-run").textContent = motor.mode === "wheels" ? "Running…" : "Run both";
}
(function motorControls() {
  ["m-left", "m-right", "m-speed", "m-turn"].forEach((id) => $(id).addEventListener("input", motorUi));   // next renewal carries it
  const pad = $("m-pad");
  pad.addEventListener("pointerdown", (e) => {
    const b = e.target.closest("button[data-dir]");
    if (!b || b.disabled) return;
    e.preventDefault();
    b.setPointerCapture(e.pointerId);
    motorStart("pad", b.dataset.dir);
  });
  const release = () => { if (motor.mode === "pad") motorStop(); };
  pad.addEventListener("pointerup", release);
  pad.addEventListener("pointercancel", release);
  pad.addEventListener("lostpointercapture", release);
  const KEYS = { ArrowUp: "fwd", w: "fwd", ArrowDown: "back", s: "back", ArrowLeft: "left", a: "left", ArrowRight: "right", d: "right" };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { motorStop(); return; }
    const dir = KEYS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (!dir || $("motor-ctl").hidden || $("m-run").disabled || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) && e.target.type !== "range") return;
    e.preventDefault();
    if (motor.mode !== "pad" || motor.dir !== dir) motorStart("pad", dir);
  });
  document.addEventListener("keyup", (e) => {
    const dir = KEYS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (dir && motor.mode === "pad" && motor.dir === dir) motorStop();
  });
  window.addEventListener("blur", release);
  $("m-run").addEventListener("click", () => motorStart("wheels"));
  $("m-stop").addEventListener("click", motorStop);
  $("m-reset").addEventListener("click", () => motorPost({ cmd: "reset" }));
  document.addEventListener("visibilitychange", () => { if (document.hidden && motor.mode) motorStop(); });
  window.addEventListener("pagehide", () => { if (motor.mode) navigator.sendBeacon("/motor", JSON.stringify({ cmd: "stop" })); });
  motorUi();
})();
function renderMotorControl() {
  const s = stats("motor"), on = !!(S.control && S.control.motor) && workerState("motor").key === "ok";
  $("motor-ctl").hidden = !(S.control && S.control.motor);
  if (s.max_rpm) {
    for (const id of ["m-left", "m-right"]) if (Number($(id).max) !== s.max_rpm) { $(id).min = -s.max_rpm; $(id).max = s.max_rpm; }
    for (const id of ["m-speed", "m-turn"]) if (Number($(id).max) !== s.max_rpm) $(id).max = s.max_rpm;
    motorUi();
  }
  document.querySelectorAll("#m-pad button, #m-run").forEach((b) => { b.disabled = !on || (b.id === "m-run" && motor.mode === "wheels"); });
  if (!on && motor.mode) motorStop();
  const src = s.source === "dashboard" ? `the dashboard is setting left ${fmt(s.target_left, 0)} / right ${fmt(s.target_right, 0)} RPM`
    : `holding the command-line target, ${fmt(s.target_left, 0)} RPM`;
  $("m-note").innerHTML = motor.err ? `<span class="badt">${esc(motor.err)}</span>`
    : !on ? "motor link not live: controls are disabled"
    : esc(src) + " · limit ±" + fmt(s.max_rpm, 0) + " RPM · Esc stops, and so do closing or hiding this tab";
}
function renderDeadlines() {
  let live = 0, missed = 0;
  $("deadlines").innerHTML = (S.deadlines || []).map((d) => {
    const ws = workerState(d.worker);
    const s = stats(d.worker)[d.key] || {};
    const ok = d.windows ? 100 * (1 - d.over / d.windows) : null;
    const active = ws.key === "ok" && d.windows > 0;
    if (active) { live++; if (d.over) missed++; }
    const mark = !active ? '<span class="muted">not live</span>' : d.over ? `<span class="badt">! ${fmt(ok, 2)}%</span>` : `<span class="okt">✓ ${fmt(ok, 0)}%</span>`;
    return `<tr><td>${esc(d.label)}</td><td class="num">${fmt(d.budget, 0)} ms</td><td class="num">${fmt(s.p99, 2)}</td>` +
      `<td class="num">${fmt(d.worst, 2)}</td><td class="num">${mark}</td></tr>`;
  }).join("");
  const up = Math.round(S.now - S.started), mins = Math.floor(up / 60), secs = up % 60;
  const b = $("banner");
  const cls = !live ? "warn" : missed ? "warn" : "ok";
  const label = !live ? "starting" : missed ? `${missed} of ${live} missed a deadline` : `all ${live} live streams on time`;
  b.innerHTML = `<span class="chip ${cls}"><span class="dot" aria-hidden="true"></span>${esc(label)}</span>` +
    `<span class="sub">running ${mins} min ${secs} s · ${Object.keys(S.workers).length - (S.workers.hub ? 1 : 0)} processes reporting</span>`;
}

function render() {
  pending = false;
  if (!S) return;
  $("about").textContent = (S.roles && S.roles.about) || "";
  $("meta").textContent = `profile: ${S.profile}`;
  document.querySelectorAll("[data-status]").forEach((el) => chip(el, workerState(el.dataset.status).key));
  document.querySelectorAll("[data-detail]").forEach((el) => { el.textContent = workerState(el.dataset.detail).detail; });
  renderDeadlines(); renderVision(); renderImu(); renderLidar(); renderGps(); renderSystem(); renderCell(); renderMotor(); renderMotorControl();
  sparks.forEach(drawSpark);
}

const es = new EventSource("/events");
es.onmessage = (ev) => { S = JSON.parse(ev.data); if (!pending) { pending = true; requestAnimationFrame(render); } };
es.onerror = () => { $("about").textContent = "lost connection to the hub, retrying…"; };
window.addEventListener("resize", () => S && render());
