"""The curb history's charts: one self-contained HTML page (no libraries, no network), written by `history.py plot`.

Each crossing (scenario, direction, start, descent start) gets a small chart of the chosen measure against the runs in
order (every run one column, its repeats side by side, its median a line), marked by outcome: filled = met (and fluid,
for a robot whose runner scores fluidity), ringed = passed but not met or not fluid, a red cross = failed. A filter row
picks the measure, the direction, the start and whether only runs at the standard settings show; an overview gives each
run's share of crossings that met their expectation; a table lists the runs. Robots are series, so two robots' crossings
share a chart when both ran the same one. The shared measures (measures.py, the same for every robot) come first;
write(..., measures=...) adds a robot's own.
"""

import html
import json
import os

SHARED_MEASURES = [
    ("shared.times.edge_to_last_down_s", "Front wheel at the edge to the last wheel down (s)", "lower"),
    ("shared.times.edge_to_done_s", "Front wheel at the edge to Done (s)", "lower"),
    ("shared.times.edge_to_rest_s", "Front wheel at the edge to at rest (s)", "lower"),
    ("shared.speed.v_min_cm_s", "Least speed, edge to last wheel down (cm/s over 0.3 s)", "higher"),
    ("shared.speed.mean_cm_s", "Mean speed, edge to last wheel down (cm/s)", "higher"),
    ("shared.speed.stopped_s", "Time stopped, edge to last wheel down (s)", "lower"),
    ("shared.attitude.max_seat_incl_deg", "Most seat inclination, edge to last wheel down (deg)", "lower"),
    ("shared.attitude.seat_tilt_rate_deg_s", "Fastest seat tilt (deg/s over 0.3 s)", "lower"),
    ("shared.attitude.final_seat_incl_deg", "Seat inclination at Done (deg)", "lower"),
    ("shared.path.drift_cm", "Drift across the heading (cm)", "lower"),
    ("rider.peak_total_m_s2", "Rider's peak acceleration (m/s^2)", "lower"),
    ("rider.rms_total_m_s2", "Rider's RMS acceleration (m/s^2)", "lower"),
]
MEASURES = list(SHARED_MEASURES)


def get(rec, path):
    cur = rec
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None


def describe_code(code):
    """The code a record ran on, as [name, text] pairs for the page: each
    repository's commit (+ with uncommitted changes), the binaries' build
    times; a backfilled run's note and the commits it names (~ when they are
    only approximate); `at record` when only the checkout at recording is
    known."""
    out = []
    at = code.get("ran_on") or code.get("at_record")
    if at:
        pre = "" if code.get("ran_on") else "at record: "
        for k, v in at.items():
            if isinstance(v, dict) and k != "built":
                out.append([pre + k, "%s%s" % (str(v.get("sha", ""))[:7], "+" if v.get("dirty") else "")])
        for k, v in (at.get("built") or {}).items():
            out.append([k + " built", str(v).replace("T", " ")[:16]])
    note = code.get("ran_on_note") or {}
    if note:
        mark = "~" if note.get("approximate") else ""
        for k, v in (note.get("commits") or {}).items():
            out.append([k, mark + str(v)])
        if note.get("note"):
            out.append(["note", ("approximately: " if note.get("approximate") else "") + note["note"]])
    return out


def slim(rec, measures):
    """What the page needs of a record."""
    o = rec.get("outcome") or {}
    code_desc = describe_code(rec.get("code") or {})
    return {
        "robot": rec.get("robot"), "scenario": rec.get("scenario"), "dir": rec.get("dir"), "start": rec.get("start"),
        "from": rec.get("descent_start"), "rep": rec.get("rep"), "ran_at": rec.get("ran_at"), "run": rec["run"]["dir"],
        "label": rec.get("label"), "standard": bool((rec.get("settings") or {}).get("standard")),
        "settings": {k: v for k, v in (rec.get("settings") or {}).items() if v not in (None, False, "") and k != "standard"},
        "met": o.get("met"), "pass": o.get("pass"), "fluid": o.get("fluid"), "failed": o.get("failed"), "status": o.get("status"),
        "code": code_desc,
        "m": {path: get(rec, path) for path, _, _ in measures},
    }


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Curb crossing history</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--crit:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--crit:#d03b3b}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--crit:#d03b3b}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1400px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}p.sub{color:var(--ink2);margin:0 0 12px}
.filters{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:0 0 12px}.filters label{color:var(--ink2)}
select,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px 8px}
.legend{display:flex;flex-wrap:wrap;gap:16px;color:var(--ink2);margin:0 0 12px;align-items:center}.legend svg{vertical-align:middle}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 10px 4px}
.card h3{font-size:13px;margin:0 0 2px;font-weight:600}.card .meta{color:var(--muted);font-size:12px;margin:0 0 4px}
svg text{fill:var(--muted);font-size:11px}.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);
border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.18);max-width:360px;display:none;z-index:9}
.tip b{font-weight:600}.tip .k{color:var(--ink2)}table{border-collapse:collapse;width:100%;background:var(--surface);font-size:12px}
th,td{border-bottom:1px solid var(--grid);padding:4px 6px;text-align:left;white-space:nowrap}th{color:var(--ink2);font-weight:600}
details{margin:16px 0}summary{cursor:pointer;color:var(--ink2)}.tablewrap{overflow-x:auto}
.overview{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px;margin:0 0 12px}
</style></head>
<body><main>
<h1>Curb crossing history</h1>
<p class="sub">__SUB__</p>
<div class="filters">
<label>Measure <select id="measure"></select></label>
<label>Direction <select id="dir"><option value="">both</option><option>up</option><option>down</option></select></label>
<label>Start <select id="start"><option value="">both</option><option>standing</option><option>rolling</option></select></label>
<label><input type="checkbox" id="std" __STD__> standard settings only</label>
<button id="theme" type="button">Theme</button>
</div>
<div class="legend" id="legend"></div>
<div class="overview"><h3 style="margin:0 0 4px;font-size:13px">Share of crossings that met their expectation, per run</h3><div id="overview"></div></div>
<div class="grid" id="grid"></div>
<p class="sub" id="without" style="margin-top:12px"></p>
<details><summary>Runs (table)</summary><div class="tablewrap" id="runs"></div></details>
</main><div class="tip" id="tip"></div>
<script>
const DATA = __DATA__;
const MEASURES = __MEASURES__;
const ROBOTS = {gen2:{name:"Gen2", v:"--s1"}, gen1:{name:"Gen1", v:"--s2"}};
const robotOf = k => ROBOTS[k] || {name:k, v:"--s3"};
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
for (const [p, n] of MEASURES) { const o = document.createElement("option"); o.value = p; o.textContent = n; $("measure").appendChild(o); }
try { const s = localStorage.getItem("curbhist.measure"); if (s) $("measure").value = s; } catch (e) {}
$("theme").onclick = () => { const r = document.documentElement; const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = r.dataset.theme || (dark ? "dark" : "light"); r.dataset.theme = cur === "dark" ? "light" : "dark"; draw(); };
const tip = $("tip");
function showTip(ev, h) { tip.innerHTML = h; tip.style.display = "block"; const w = tip.offsetWidth, hh = tip.offsetHeight;
  let x = ev.clientX + 14, y = ev.clientY + 14; if (x + w > innerWidth - 8) x = ev.clientX - w - 14; if (y + hh > innerHeight - 8) y = ev.clientY - hh - 14;
  tip.style.left = x + "px"; tip.style.top = y + "px"; }
const hideTip = () => tip.style.display = "none";
const NS = "http://www.w3.org/2000/svg";
function el(t, a, p) { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
function niceTicks(lo, hi, n) { if (!(hi > lo)) { hi = lo + 1; } const span = hi - lo, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || mag * 10; const t = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) t.push(+v.toFixed(6)); return t; }
function dateLabels(svg, pts, H, left, right) {
  if (!pts.length) return;
  // pts: [x, text] in order. Each day's first run (where the date changes) and the last run, none within 46 px of another
  // (the last kept over one before it).
  const keep = []; const last = pts[pts.length - 1];
  pts.forEach((p, i) => { if (p === last) return; if (i > 0 && p[1] === pts[i - 1][1]) return;
    if ((!keep.length || p[0] - keep[keep.length - 1][0] >= 46) && last[0] - p[0] >= 46) keep.push(p); });
  if (!keep.length || keep[keep.length - 1][1] !== last[1]) keep.push(last);
  for (const [x, t] of keep) { const a = x - left < 20 ? "start" : right - x < 20 ? "end" : "middle";
    el("text", {x, y:H - 5, "text-anchor":a}, svg).textContent = t; } }
function median(a) { const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function outcome(r) { return r.met && r.fluid !== false ? "fluid" : (r.pass || r.met ? "pass" : "fail"); }
function mark(g, x, y, r, color) { const o = outcome(r);
  if (o === "fail") { const s = 4.5; el("path", {d:`M${x-s},${y-s}L${x+s},${y+s}M${x-s},${y+s}L${x+s},${y-s}`, stroke:css("--crit"), "stroke-width":2.2, "stroke-linecap":"round"}, g); }
  else el("circle", {cx:x, cy:y, r:4.5, fill:o === "fluid" ? color : css("--surface"), stroke:o === "fluid" ? css("--surface") : color, "stroke-width":o === "fluid" ? 2 : 2}, g); }
function legend() { const robots = [...new Set(DATA.map(r => r.robot))];
  let h = robots.map(k => `<span><svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="${css(robotOf(k).v)}"/></svg> ${esc(robotOf(k).name)}</span>`).join("");
  const c = css("--s1"), sf = css("--surface");
  h += `<span><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="${c}" stroke="${sf}" stroke-width="2"/></svg> met (and fluid, where scored)</span>`;
  h += `<span><svg width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="${sf}" stroke="${c}" stroke-width="2"/></svg> passed, not met or not fluid</span>`;
  h += `<span><svg width="14" height="14"><path d="M3,3L11,11M3,11L11,3" stroke="${css("--crit")}" stroke-width="2.2" stroke-linecap="round"/></svg> failed</span>`;
  h += `<span><svg width="22" height="14"><line x1="1" y1="7" x2="21" y2="7" stroke="${c}" stroke-width="2"/></svg> the run's median</span>`;
  $("legend").innerHTML = h; }
function tipFor(r, m, name) { const v = r.m[m];
  return `<b>${esc(r.scenario)} ${esc(r.dir)}, ${esc(r.start)}${r.from ? " (" + esc(r.from) + ")" : ""}</b> &middot; ${esc(robotOf(r.robot).name)}<br>` +
    `<span class="k">${esc(name)}:</span> ${v == null ? "&ndash;" : v}<br><span class="k">outcome:</span> ${outcome(r)}${r.failed ? " (" + esc(r.failed.join(", ")) + ")" : ""}<br>` +
    `<span class="k">ran:</span> ${esc((r.ran_at || "").replace("T", " ").slice(0, 16))} &middot; rep ${r.rep}<br><span class="k">run:</span> ${esc(r.run)}${r.label ? " [" + esc(r.label) + "]" : ""}<br>` +
    `<span class="k">code:</span> ${esc(r.code.map(([k, v]) => k + " " + v).join(", "))}` +
    (Object.keys(r.settings).length ? `<br><span class="k">settings:</span> ${esc(Object.entries(r.settings).map(([k, v]) => k + " " + v).join(", "))}` : "") +
    (r.status ? `<br><span class="k">status:</span> ${esc(r.status)}` : ""); }
function draw() {
  const m = $("measure").value; try { localStorage.setItem("curbhist.measure", m); } catch (e) {}
  const name = MEASURES.find(x => x[0] === m)[1];
  const rows = DATA.filter(r => (!$("dir").value || r.dir === $("dir").value) && (!$("start").value || r.start === $("start").value) && (!$("std").checked || r.standard));
  legend();
  $("grid").innerHTML = ""; $("without").textContent = ""; $("runs").innerHTML = ""; $("overview").innerHTML = "";
  if (!rows.length) { $("overview").textContent = "No crossings match these filters."; return; }
  // Runs in order of their first crossing: one column each, shared by every chart.
  const runFirst = {}; for (const r of rows) { const t = r.ran_at || ""; if (!(r.run in runFirst) || t < runFirst[r.run]) runFirst[r.run] = t; }
  const runs = Object.keys(runFirst).sort((a, b) => runFirst[a] < runFirst[b] ? -1 : runFirst[a] > runFirst[b] ? 1 : a < b ? -1 : 1);
  const col = Object.fromEntries(runs.map((r, i) => [r, i]));
  // Overview: per run, the share met.
  overview(rows, runs, col, runFirst);
  const groups = {}; for (const r of rows) { const k = [r.scenario, r.dir, r.start, r.from || ""].join("|"); (groups[k] ||= []).push(r); }
  const grid = $("grid"); grid.innerHTML = ""; const without = [];
  for (const k of Object.keys(groups).sort()) {
    const g = groups[k], [sc, dir, start, from] = k.split("|");
    const vals = g.map(r => r.m[m]).filter(v => v != null);
    if (!vals.length) { without.push(`${sc} ${dir} (${start}${from ? ", " + from.replace("_", " ") : ""}; ${g.filter(r => r.met).length} of ${g.length} met)`); continue; }
    const card = document.createElement("div"); card.className = "card";
    const met = g.filter(r => r.met).length;
    card.innerHTML = `<h3>${esc(sc)} ${esc(dir)} &middot; ${esc(start)}${from ? " &middot; " + esc(from.replace("_", " ")) : ""}</h3><div class="meta">${g.length} crossings, ${met} met${vals.length ? ", latest " + esc(vals[vals.length - 1]) : ""}</div>`;
    grid.appendChild(card);
    const W = 330, H = 150, L = 36, R = 8, T = 8, B = 20;
    const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, width:"100%", role:"img", "aria-label":`${sc} ${dir} ${start}: ${name} by run`}, card);
    let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1; lo -= pad; hi += pad;
    if (lo > 0 && lo < (hi - lo) * 0.5) lo = 0;
    const ticks = niceTicks(lo, hi, 4); lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const used = [...new Set(g.map(r => col[r.run]))].sort((a, b) => a - b);
    const X0 = L + 12, X1 = W - R - 8;  // the dots clear of the value labels
    const xs = Object.fromEntries(used.map((c, i) => [c, used.length === 1 ? (X0 + X1) / 2 : X0 + i * (X1 - X0) / (used.length - 1)]));
    const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
    for (const t of ticks) { el("line", {x1:L, x2:W - R, y1:y(t), y2:y(t), stroke:css("--grid"), "stroke-width":1}, svg);
      el("text", {x:L - 4, y:y(t) + 4, "text-anchor":"end"}, svg).textContent = +t.toFixed(2); }
    const step = used.length > 1 ? (X1 - X0) / (used.length - 1) : 40;
    dateLabels(svg, used.map(c => [xs[c], (runFirst[runs[c]] || "").slice(5, 10)]), H, L, W - R);
    for (const robot of [...new Set(g.map(r => r.robot))]) {
      const color = css(robotOf(robot).v); const pts = [];
      for (const c of used) { const v = g.filter(r => r.robot === robot && col[r.run] === c && r.m[m] != null).map(r => r.m[m]); if (v.length) pts.push([xs[c], y(median(v))]); }
      if (pts.length > 1) el("path", {d:"M" + pts.map(p => p.join(",")).join("L"), fill:"none", stroke:color, "stroke-width":2, "stroke-linejoin":"round", opacity:0.55}, svg);
      const gg = el("g", {}, svg);
      for (const c of used) { const here = g.filter(r => r.robot === robot && col[r.run] === c && r.m[m] != null).sort((a, b) => a.rep - b.rep);
        here.forEach((r, j) => { const dx = here.length > 1 ? (j - (here.length - 1) / 2) * Math.min(7, step / (here.length + 1)) : 0;
          const cx = xs[c] + dx, cy = y(r.m[m]); mark(gg, cx, cy, r, color);
          const hit = el("circle", {cx, cy, r:9, fill:"transparent"}, gg);
          hit.addEventListener("mousemove", ev => showTip(ev, tipFor(r, m, name))); hit.addEventListener("mouseleave", hideTip); }); }
    }
  }
  $("without").textContent = without.length ? "No values for this measure (refusals, or crossings that did not run that far): " + without.join("; ") + "." : "";
  table(rows, runs, runFirst);
}
function overview(rows, runs, col, runFirst) {
  const W = Math.max(330, Math.min(1360, runs.length * 26 + 50)), H = 110, L = 36, R = 8, T = 8, B = 20, box = $("overview"); box.innerHTML = "";
  const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, width:"100%", role:"img", "aria-label":"share of crossings met, per run"}, box);
  const y = v => T + (1 - v) * (H - T - B);
  for (const t of [0, 0.5, 1]) { el("line", {x1:L, x2:W - R, y1:y(t), y2:y(t), stroke:css("--grid")}, svg); el("text", {x:L - 4, y:y(t) + 4, "text-anchor":"end"}, svg).textContent = (t * 100) + "%"; }
  const nRobots = Math.max(1, new Set(rows.map(r => r.robot)).size);
  const bw = Math.max(3, Math.min(18, (W - L - R) / runs.length / nRobots - 4));
  runs.forEach((run, i) => { const inRun = rows.filter(r => r.run === run); const robots = [...new Set(inRun.map(r => r.robot))];
   robots.forEach((robot, j) => { const g = inRun.filter(r => r.robot === robot); const share = g.filter(r => r.met).length / g.length;
    const slot = (W - L - R) / runs.length; const x = L + i * slot + (j + 0.5) * slot / robots.length; const top = y(share), base = y(0);
    const hgt = Math.max(0, base - top); const r = Math.min(4, bw / 2, hgt);
    el("path", {d:`M${x - bw / 2},${base}V${top + r}Q${x - bw / 2},${top} ${x - bw / 2 + r},${top}H${x + bw / 2 - r}Q${x + bw / 2},${top} ${x + bw / 2},${top + r}V${base}Z`, fill:css(robotOf(robot).v)}, svg);
    const hit = el("rect", {x:x - Math.max(bw, 12) / 2, y:T, width:Math.max(bw, 12), height:H - T - B, fill:"transparent"}, svg);
    hit.addEventListener("mousemove", ev => showTip(ev, `<b>${esc(run)}</b> &middot; ${esc(robotOf(robot).name)}<br>${g.filter(r => r.met).length} of ${g.length} met (${Math.round(share * 100)}%)<br><span class="k">ran:</span> ${esc((g[0].ran_at || "").replace("T", " ").slice(0, 16))}`));
    hit.addEventListener("mouseleave", hideTip);
   }); });
  dateLabels(svg, runs.map((run, i) => [L + (i + 0.5) * (W - L - R) / runs.length, (runFirst[run] || "").slice(5, 10)]), H, L, W - R);
}
function table(rows, runs, runFirst) {
  let h = `<table><thead><tr><th>first crossing</th><th>run</th><th>label</th><th>robot</th><th>crossings</th><th>met</th><th>fluid</th><th>median ${esc(MEASURES[0][1])}</th><th>code</th></tr></thead><tbody>`;
  for (const run of runs) for (const robot of [...new Set(rows.filter(r => r.run === run).map(r => r.robot))]) {
    const g = rows.filter(r => r.run === run && r.robot === robot); const t = g.map(r => r.m[MEASURES[0][0]]).filter(v => v != null);
    h += `<tr><td>${esc((runFirst[run] || "").replace("T", " ").slice(0, 16))}</td><td>${esc(run)}</td><td>${esc(g[0].label || "")}</td><td>${esc(robotOf(g[0].robot).name)}</td>` +
      `<td>${g.length}</td><td>${g.filter(r => r.met).length}</td><td>${g.filter(r => r.fluid).length}</td><td>${t.length ? median(t).toFixed(2) : "&ndash;"}</td>` +
      `<td>${esc(g[0].code.map(([k, v]) => k + " " + v).join(", "))}</td></tr>`; }
  $("runs").innerHTML = h + "</tbody></table>"; }
for (const id of ["measure", "dir", "start", "std"]) $(id).addEventListener("change", draw);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
draw();
</script></body></html>
"""


def write(records, out, standard_only=True, measures=None):
    measures = list(measures or MEASURES)
    data = [slim(r, measures) for r in records]
    runs = len({r["run"] for r in data})
    sub = ("%d crossings over %d runs. Runs are in the order they ran, one column each (dated where the day changes); "
           "every dot is a crossing -- hover for its details." % (len(data), runs))
    page = (PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
            .replace("__MEASURES__", json.dumps([[p, n] for p, n, _ in measures]))
            .replace("__SUB__", html.escape(sub))
            .replace("__STD__", "checked" if standard_only else ""))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    os.replace(tmp, out)
    print("curb history: charts for %d crossing(s) in %s" % (len(data), out))
