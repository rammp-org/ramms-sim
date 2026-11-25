#!/usr/bin/env python3
"""Show a level run: one figure per case with the assist on over the assist off, and the tables.

    python -I Scripts/curb_runner/level_report.py RUN_DIR [--out FILE.html]
    python -I Scripts/curb_runner/level_report.py --history FILE [--out FILE.html]

RUN_DIR is a run_level.py --out folder (level_results.json and the traces beside it; rep<k>/ with --repeat). It
writes RUN_DIR/level_report.html, one page with every figure inline, and each figure alone as
RUN_DIR/figures/<case>.svg. A figure, against the distance along the path (against time for a run that stays where
it is):

    pitch, roll      the rider and the chassis with the assist on (blue) and off (orange), the ground's own attitude
                     under the standing wheels (grey) and the preference (dotted)
    error            the rider against the preference, on and off, with the 1 deg and 0.5 deg levels the transition
                     figures use
    level.state      the assist's state; level.reach and the speed scale
    speed, heading   the speed along the path; the heading off the path's and the turn the hold held (the steering
                     effort the run needed to stay on its path)

with the path's seams shaded (from the first wheel reaching one to the last leaving it), each stretch named along the
top, and every event marked. Under each figure: its segments (steady figures) and its transitions (peak, time outside
1 deg, tilt rate, settling), on beside off. With --history: a page of a level history's latest pair per case.
No plotting package: svg_plot.py writes the figures. Only the standard library.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import course  # noqa: E402
import history  # noqa: E402
import level_measures as lm  # noqa: E402
import robots  # noqa: E402
import svg_plot as sp  # noqa: E402

lt = course.lt

PAGE_STYLE = """
:root{--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--sub:#52514e;--mute:#898781;--line:#e1e0d9;--on:#2a78d6;--off:#eb6834;--bad:#d03b3b;--good:#0ca30c}
@media (prefers-color-scheme: dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#f0efec;--sub:#c3c2b7;--line:#2c2c2a;--on:#3987e5;--off:#d95926}}
body{margin:0;padding:20px 28px;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 6px}h3{font-size:13px;margin:16px 0 4px;color:var(--sub)}
p{margin:4px 0 10px;color:var(--sub);max-width:1000px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0 22px;overflow-x:auto}
table{border-collapse:collapse;font-size:12px;margin:4px 0 10px}th,td{padding:3px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--sub);font-weight:600}td:first-child,th:first-child{text-align:left}
.on{box-shadow:inset 3px 0 0 var(--on)}.off{box-shadow:inset 3px 0 0 var(--off)}
.no{color:var(--bad);font-weight:600}.yes{color:var(--good);font-weight:600}.mute{color:var(--mute)}
.fig{position:relative;display:inline-block}.tip{position:absolute;display:none;pointer-events:none;background:var(--card);
border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:11.5px;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);z-index:2}
.tip b{font-weight:600}.sw{display:inline-block;width:10px;height:3px;margin-right:5px;vertical-align:middle}
"""

# A crosshair and a readout over every figure: the nearest sample of each line at the pointer's x.
PAGE_SCRIPT = """
document.querySelectorAll('.fig').forEach(function(fig){
  var svg=fig.querySelector('svg'),tip=fig.querySelector('.tip'),hair=svg.querySelector('.sv-xhair');
  var data=JSON.parse(fig.querySelector('script[type="application/json"]').textContent);
  var x0=+svg.dataset.xmin,x1=+svg.dataset.xmax,l=+svg.dataset.left,r=+svg.dataset.right;
  svg.addEventListener('mousemove',function(ev){
    var box=svg.getBoundingClientRect(),k=svg.viewBox.baseVal.width/box.width,px=(ev.clientX-box.left)*k;
    if(px<l||px>r){tip.style.display='none';hair.style.visibility='hidden';return;}
    var x=x0+(px-l)/(r-l)*(x1-x0),rows=['<b>'+data.x+' '+x.toFixed(2)+'</b>'];
    data.series.forEach(function(s){
      var best=-1,d=1e99;for(var i=0;i<s.x.length;i++){var e=Math.abs(s.x[i]-x);if(e<d&&s.y[i]!==null){d=e;best=i;}}
      if(best>=0)rows.push('<span class="sw" style="background:var(--'+(s.role==='on'?'on':s.role==='off'?'off':'mute')+')"></span>'+s.label+': <b>'+s.y[best]+'</b>');
    });
    hair.setAttribute('x1',px);hair.setAttribute('x2',px);hair.style.visibility='visible';
    tip.innerHTML=rows.join('<br>');tip.style.display='block';
    var tx=(ev.clientX-box.left)+14;if(tx+tip.offsetWidth>box.width)tx=(ev.clientX-box.left)-tip.offsetWidth-14;
    tip.style.left=tx+'px';tip.style.top=Math.max(0,(ev.clientY-box.top)-20)+'px';
  });
  svg.addEventListener('mouseleave',function(){tip.style.display='none';hair.style.visibility='hidden';});
});
"""


def esc(s):
    return sp.esc("" if s is None else s)


def num(x, nd=2):
    if x is None:
        return '<span class="mute">-</span>'
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (list, tuple)):
        return ", ".join("%+.*f" % (nd, v) if v is not None else "-" for v in x)
    return "%.*f" % (nd, x)


def load_trace(d, row):
    p = os.path.join(d, row.get("trace") or "")
    if not row.get("trace") or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def case_title(row):
    hold = "" if (row.get("hold") or {}).get("on") else ", hold off"
    return "%s %s, start %s, %s, preference %+g / %+g deg, stick %g%s" % (
        row["course"], row["dir"], row["start"], row["variant"], row["pref"][0], row["pref"][1], row["stick"], hold)


def figure_of(on_row, off_row, on_trace, off_trace, level_prof):
    """(svg_plot.Figure, the readout's series) for a case: the on run over the off run (either may be missing)."""
    row = on_row or off_row
    layout = lt.layout(row["course"])
    runs = []
    for role, r, tr in (("on", on_row, on_trace), ("off", off_row, off_trace)):
        if r is None or tr is None or tr.get("go_t") is None:
            continue
        runs.append((role, tr, lm.series(tr, layout, level_prof)))
    if not runs:
        return None, None
    lead = runs[0][1]
    plan = lead["cfg"]["plan"]
    parked = "t" in (plan.get("end") or {})

    def xs_of(tr, rows):
        return [(r["t"] - tr["go_t"]) if parked else r["d"] / 100.0 for r in rows]

    panels = {"pitch": [], "roll": [], "err": [], "state": [], "reach": [], "speed": [], "yaw": [], "turn": []}
    ground = {"pitch": [], "roll": []}
    for role, tr, rows in runs:
        rows = [r for r in rows if r["t"] >= tr["go_t"] - (course.SETTLE_S if parked else 1.0)]
        xs = xs_of(tr, rows)
        name = "assist %s" % role
        if not ground["pitch"]:  # the ground and the preference once: both runs cover the same ground
            ground["pitch"] = [sp.Series("preference", xs, [r["pp"] for r in rows], "pref", "dot"),
                               sp.Series("ground", xs, [r["gp"] for r in rows], "ground")]
            ground["roll"] = [sp.Series("preference", xs, [r["pr"] for r in rows], "pref", "dot"),
                              sp.Series("ground", xs, [r["gr"] for r in rows], "ground")]
        panels["pitch"] += [sp.Series("rider, " + name, xs, [r["rp"] for r in rows], role),
                            sp.Series("chassis, " + name, xs, [r["cp"] for r in rows], role, "second")]
        panels["roll"] += [sp.Series("rider, " + name, xs, [r["rr"] for r in rows], role),
                           sp.Series("chassis, " + name, xs, [r["cr"] for r in rows], role, "second")]
        panels["err"].append(sp.Series("rider, " + name, xs, [r["re"] for r in rows], role))
        if any(r["state"] is not None for r in rows):
            panels["state"].append(sp.Series("state, " + name, xs, [r["state"] for r in rows], role, step=True))
            panels["reach"] += [sp.Series("reach, " + name, xs, [r["reach"] for r in rows], role),
                                sp.Series("speed scale, " + name, xs, [r["scale"] for r in rows], role, "second")]
        v = dict(lm.speeds(rows))
        panels["speed"].append(sp.Series(name, xs, [v.get(r["t"]) for r in rows], role))
        panels["yaw"].append(sp.Series(name, xs, [r["yaw_err"] for r in rows], role))
        panels["turn"].append(sp.Series(name, xs, [r["turn"] for r in rows], role))
    # The first listed is drawn on top: the rider with the assist on, then the off run, the ground under them all.
    out = [sp.Panel("pitch (deg, nose up +)", panels["pitch"] + ground["pitch"], refs=[0.0]),
           sp.Panel("roll (deg, right side up +)", panels["roll"] + ground["roll"], refs=[0.0]),
           sp.Panel("rider's error against the preference (deg)", panels["err"], refs=[lm.SETTLE_DEG, lm.OUTSIDE_DEG], height=96)]
    if panels["state"]:
        out.append(sp.Panel("level.state", panels["state"], y_range=(-0.4, len(lm.STATES) - 0.6),
                            ticks=[(i, n) for i, n in enumerate(lm.STATES)], height=100))
        out.append(sp.Panel("level.reach and speed scale (0..1)", panels["reach"], y_range=(-0.05, 1.05), height=80))
    if not parked:
        out.append(sp.Panel("speed along the path (cm/s)", panels["speed"], height=80))
        out.append(sp.Panel("heading off the path (deg, clockwise +)", panels["yaw"], refs=[0.0], height=80))
        out.append(sp.Panel("drive.turn held by the hold (stick)", panels["turn"], refs=[0.0], height=70))
    marks, spans, names = [], [], []
    if not parked:
        fp = lm.footprint_of(lead, level_prof)
        prof = layout.profile(plan["start"], fp or lt.REF_FOOTPRINT)
        for s in prof["segments"]:
            names.append((s["d0"] / 100.0, s["d1"] / 100.0, s["name"]))
        for t in prof["transitions"]:
            spans.append(sp.Span(t["d0"] / 100.0, t["d1"] / 100.0))
            marks.append(sp.Mark(t["d"] / 100.0, "%s > %s" % (t["from"], t["to"])))
    for e in lead.get("events") or []:
        if e.get("t") is None or (e["t"] < lead["go_t"] and not parked):
            continue  # set before go: in the tables; along the distance axis they would all sit at the start
        if e.get("do") == "pref" and e["t"] < lead["go_t"] and not (e.get("pitch") or e.get("roll")):
            continue
        marks.append(sp.Mark((e["t"] - lead["go_t"]) if parked else (e.get("d") or 0.0) / 100.0, e.get("label") or e["do"], "event"))
    fig = sp.Figure(case_title(row), "time from go (s)" if parked else "distance along the path (m)", out, marks, spans, names,
                    subtitle=layout.c.title)
    readout = {"x": "t" if parked else "m", "series": []}
    for p in out[:3]:
        for s in p.series:
            xs, ys = sp.thin(s.xs, s.ys, 700)
            readout["series"].append({"label": "%s: %s" % (p.title.split(" (")[0], s.label), "role": s.role,
                                      "x": [round(x, 3) for x in xs], "y": [None if y is None else round(y, 2) for y in ys]})
    return fig, readout


SEG_COLS = [("ground P, R", "ground_seen_deg"), ("rider - pref mean P, R", "rider_mean_deg"), ("rider RMS", "rider_rms_deg"),
            ("rider residual", "rider_residual_deg"), ("chassis residual", "chassis_residual_deg"),
            ("rider - ground P, R", "rider_off_ground_deg"), ("speed cm/s", "speed_mean_cm_s"), ("reach least", "reach_min"),
            ("scale least", "speed_scale_min"), ("yaw drift", "yaw_drift_deg"), ("lateral cm", "lateral_drift_cm"),
            ("steer mean", "steer_mean"), ("drive share least", "drive_share_min"), ("margin cm", "margin_min_cm")]
TR_COLS = [("window s", "window_s"), ("rider peak", "rider_peak_deg"), ("chassis peak", "chassis_peak_deg"),
           ("outside 1 deg s", "rider_outside_s"), ("rider rate /0.3 s", "rider_rate_deg_s"), ("chassis rate", "chassis_rate_deg_s"),
           ("ground rate", "ground_rate_deg_s"), ("settle s", "settle_s"), ("after the seam s", "settle_after_exit_s"),
           ("start", "rider_start_deg"), ("end", "rider_end_deg"), ("reach least", "reach_min"), ("scale least", "speed_scale_min"),
           ("yaw change", "yaw_change_deg")]
OVERALL_COLS = [("rider RMS", "rider_rms_deg"), ("rider peak", "rider_peak_deg"), ("chassis RMS", "chassis_rms_deg"),
                ("rider rate /0.3 s", "rider_rate_deg_s"), ("ground peak", "ground_incl_peak_deg"), ("speed cm/s", "speed_mean_cm_s"),
                ("least speed", "speed_min_cm_s"), ("stops", "stops"), ("reach least", "reach_min"), ("scale least", "speed_scale_min"),
                ("s at reach", "at_reach_s"), ("yaw change", "yaw_change_deg"), ("lateral end cm", "lateral_end_cm"),
                ("steer |mean|", "steer_abs_mean"), ("drive share least", "drive_share_min"), ("margin cm", "margin_min_cm"),
                ("wheel off s", "float_longest_s"), ("leg travel RMS cm", "leg_travel_rms_cm")]


def table(head, rows):
    out = ["<table><tr>%s</tr>" % "".join("<th>%s</th>" % esc(h) for h in head)]
    for cls, cells in rows:
        out.append('<tr>%s</tr>' % "".join('<td%s>%s</td>' % (' class="%s"' % cls if i == 0 and cls else "", c) for i, c in enumerate(cells)))
    out.append("</table>")
    return "".join(out)


def nd_of(key):
    return 3 if key in ("steer_mean", "steer_abs_mean") else 2


def case_tables(on_row, off_row):
    out = []
    runs = [(r["level"], r) for r in (on_row, off_row) if r and (r.get("figures") or {}).get("overall")]
    if not runs:
        return ""
    out.append("<h3>The run</h3>" + table(["assist", "end"] + [h for h, _ in OVERALL_COLS], [
        (lv, [esc("assist " + lv), esc(r["outcome"].get("end"))] + [num(r["figures"]["overall"].get(k), nd_of(k)) for _, k in OVERALL_COLS])
        for lv, r in runs]))
    p = (on_row or {}).get("pair")
    if p:
        out.append("<p>On against off: rejection %s (worst slope %s), speed kept %s (least on a slope %s), margin %s cm, "
                   "drive-wheel share %s.</p>" % (num(p.get("rejection")), num(p.get("rejection_slopes_max")), num(p.get("speed_kept")),
                                                   num(p.get("speed_kept_slopes_min")), num(p.get("margin_change_cm")),
                                                   num(p.get("drive_share_change"))))
    stood = [(lv, r["figures"]["parked"]) for lv, r in runs if r["figures"].get("parked")]
    if stood:
        cols = [("moved in all cm", "drift_cm"), ("settled after s", "settled_after_s"), ("commands quiet after s", "quiet_after_s"),
                ("command changes once quiet", "cmd_changes_after_settle"), ("crept while held cm", "hold_drift_cm"), ("held s", "hold_s")]
        out.append("<h3>Standing (moved in all: the reference point's farthest from where it stood at go, every switch included)</h3>"
                   + table(["assist"] + [h for h, _ in cols], [(lv, [esc("assist " + lv)] + [num(p.get(k)) for _, k in cols]) for lv, p in stood]))
    o = (on_row or {}).get("outcome") or {}
    if o.get("checks"):
        cells = []
        for c in o["checks"]:
            verdict = {True: '<span class="yes">ok</span>', False: '<span class="no">failed</span>', None: '<span class="mute">not measured</span>'}[c["ok"]]
            cells.append(("", [esc(c["name"]), num(c["value"]), ("&le; " if c["kind"] == "max" else "&ge; ") + num(c["limit"]), verdict]))
        out.append("<h3>Scored as %s</h3>" % esc(o.get("expect")) + table(["check", "value", "limit", ""], cells))
    names = []
    for _, r in runs:
        for s in r["figures"].get("segments") or []:
            if s["name"] not in names:
                names.append(s["name"])
    rows = []
    for n in names:
        for lv, r in runs:
            s = next((x for x in r["figures"]["segments"] if x["name"] == n), None)
            if s:
                rows.append((lv, [esc("%s, %s" % (n, lv))] + [num(s.get(k), nd_of(k)) for _, k in SEG_COLS]))
    if rows:
        out.append("<h3>Segments (steady: every standing wheel on one plane; residual over the last %.1f s)</h3>" % lm.STEADY_TAIL_S
                   + table(["segment"] + [h for h, _ in SEG_COLS], rows))
    rows = []
    seen = []
    for _, r in runs:
        for t in r["figures"].get("transitions") or []:
            key = (t["kind"], t["label"])
            if key not in seen:
                seen.append(key)
    for kind, label in seen:
        for lv, r in runs:
            for t in r["figures"]["transitions"]:
                if (t["kind"], t["label"]) == (kind, label):
                    note = "" if t.get("error_meant", True) else " (read the rates)"
                    rows.append((lv, [esc("%s: %s, %s%s" % (kind, label, lv, note))] + [num(t.get(k)) for _, k in TR_COLS]))
    if rows:
        out.append("<h3>Transitions (the rider's error against the preference; outside %.0f deg; settled within %.1f deg)</h3>"
                   % (lm.OUTSIDE_DEG, lm.SETTLE_DEG) + table(["transition"] + [h for h, _ in TR_COLS], rows))
    return "".join(out)


def summary_table(rows):
    head = ["case", "assist", "end", "expect", "met", "failed", "rider RMS", "rider peak", "worst residual", "tilt rate", "rejection",
            "speed kept", "reach least", "yaw change", "steer |mean|"]
    body = []
    for r in rows:
        o = r["outcome"]
        f = (r.get("figures") or {}).get("overall") or {}
        segs = (r.get("figures") or {}).get("segments") or []
        p = r.get("pair") or {}
        res = max((s["rider_residual_deg"] for s in segs if s.get("complete")), default=None)
        met = {True: '<span class="yes">yes</span>', False: '<span class="no">no</span>', None: '<span class="mute">-</span>'}[o.get("met")]
        body.append((r["level"], [esc(r.get("case") or r["course"]), esc(r["level"]), esc(o.get("end")), esc(o.get("expect") or "-"), met,
                                  esc(", ".join(o.get("failed") or []) or (o.get("why") or "")), num(f.get("rider_rms_deg")),
                                  num(f.get("rider_peak_deg")), num(res), num(f.get("rider_rate_deg_s")),
                                  num(p.get("rejection_slopes_max") if p.get("rejection_slopes_max") is not None else p.get("rejection")),
                                  num(p.get("speed_kept")), num(f.get("reach_min")), num(f.get("yaw_change_deg")),
                                  num(f.get("steer_abs_mean"), 3)]))
    return table(head, body)


def page(title, intro, body):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s</title><style>%s</style></head><body><h1>%s</h1>%s%s<script>%s</script></body></html>"
            % (esc(title), PAGE_STYLE, esc(title), intro, body, PAGE_SCRIPT))


def write(run_dir, out=None):
    """The run's report: RUN_DIR/level_report.html (or `out`) and RUN_DIR/figures/<case>.svg. Returns the page's path."""
    parts, all_rows, robot = [], [], None
    for rep, rows, path in history.run_rows(run_dir, history.LEVEL_RESULTS):
        d = os.path.dirname(path)
        all_rows += rows
        cases = {}
        for r in rows:
            if not r.get("course"):
                continue
            cases.setdefault(course.pair_key(r), {})[r.get("level")] = r
        for key, pr in cases.items():
            on_row, off_row = pr.get("on"), pr.get("off")
            row = on_row or off_row
            prof = robots.find(row.get("robot_id") or "")
            robot = robot or (prof or {}).get("name") or row.get("robot_id")
            level_prof = (prof or {}).get("level") or {}
            on_tr, off_tr = (load_trace(d, on_row) if on_row else None), (load_trace(d, off_row) if off_row else None)
            title = case_title(row) + (" (rep %d)" % rep if len(history.run_rows(run_dir, history.LEVEL_RESULTS)) > 1 else "")
            block = ["<h2>%s</h2>" % esc(title)]
            try:
                fig, readout = figure_of(on_row, off_row, on_tr, off_tr, level_prof)
            except Exception as exc:  # noqa: BLE001  (one case's figure must not lose the page)
                fig, readout = None, None
                block.append('<p class="no">no figure: %s: %s</p>' % (esc(type(exc).__name__), esc(exc)))
            if fig is not None:
                svg = sp.render(fig)
                name = (row.get("case") or "case").rsplit("_", 1)[0] + ("_rep%d" % rep if rep > 1 else "")
                sp.write(os.path.join(run_dir, "figures", name + ".svg"), svg)
                block.append('<div class="card"><div class="fig">%s<div class="tip"></div><script type="application/json">%s</script></div>'
                             % (svg, json.dumps(readout, separators=(",", ":")).replace("</", "<\\/")))
                block.append(case_tables(on_row, off_row) + "</div>")
            else:
                block.append('<div class="card">%s</div>' % (case_tables(on_row, off_row) or "<p>No trace to show.</p>"))
            parts.append("".join(block))
    scored = [r for r in all_rows if (r.get("outcome") or {}).get("met") is not None]
    intro = ("<p>%s. %d runs; %d of %d scored runs met their expectation. The rider is the seat less its mount's offset; errors are "
             "against the preference (pitch nose up, roll with the right side up); the ground is the plane under the standing wheels. "
             "Blue: assist on. Orange: assist off. Move the pointer over a figure for its values.</p>"
             % (esc(robot or "?"), len(all_rows), sum(1 for r in scored if r["outcome"]["met"]), len(scored)))
    body = '<div class="card">%s</div>%s' % (summary_table([r for r in all_rows if r.get("course")]), "".join(parts))
    out = out or os.path.join(run_dir, "level_report.html")
    sp.write(out, page("Level assist: %s" % os.path.basename(os.path.normpath(run_dir)), intro, body))
    return out


def history_page(records, out):
    """A level history's latest pair per case, as one table."""
    latest = {}
    for r in sorted(records, key=lambda r: r.get("ran_at") or ""):
        if r.get("group") != history.LEVEL_GROUP:
            continue
        key = (r.get("robot"), r.get("course"), r.get("dir"), r.get("start"), r.get("variant"), tuple(r.get("pref") or ()),
               r.get("stick"), r.get("hold"), bool((r.get("settings") or {}).get("locked_frame_s")))
        latest.setdefault(key, {})[r.get("level")] = r
    head = ["robot", "case", "ran", "met", "failed", "rider RMS on", "off", "rejection", "rider peak on", "off", "tilt rate on", "off",
            "speed kept", "margin on", "off", "reach least", "yaw change on", "off"]
    body = []
    for key in sorted(latest, key=str):
        on, off = latest[key].get("on"), latest[key].get("off")
        r = on or off
        fo = lambda rec, k: num((((rec or {}).get("figures") or {}).get("overall") or {}).get(k))  # noqa: E731
        p = (on or {}).get("pair") or {}
        o = (on or {}).get("outcome") or {}
        met = {True: '<span class="yes">yes</span>', False: '<span class="no">no</span>', None: '<span class="mute">-</span>'}[o.get("met")]
        case = "%s %s %s %s p%+g%+g s%g%s%s" % (r["course"], r["dir"], r["start"], r["variant"], r["pref"][0], r["pref"][1], r["stick"],
                                                "" if r.get("hold") else " nohold", " locked" if key[-1] else "")
        body.append(("", [esc(r.get("robot")), esc(case), esc((r.get("ran_at") or "")[:16]), met, esc(", ".join(o.get("failed") or [])),
                          fo(on, "rider_rms_deg"), fo(off, "rider_rms_deg"),
                          num(p.get("rejection_slopes_max") if p.get("rejection_slopes_max") is not None else p.get("rejection")),
                          fo(on, "rider_peak_deg"), fo(off, "rider_peak_deg"), fo(on, "rider_rate_deg_s"), fo(off, "rider_rate_deg_s"),
                          num(p.get("speed_kept")), fo(on, "margin_min_cm"), fo(off, "margin_min_cm"), fo(on, "reach_min"),
                          fo(on, "yaw_change_deg"), fo(off, "yaw_change_deg")]))
    intro = "<p>%d records; the latest assist-on run of each case beside its assist-off run.</p>" % len(records)
    sp.write(out, page("Level assist history", intro, '<div class="card">%s</div>' % table(head, body)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", nargs="?", help="a run_level.py --out folder")
    ap.add_argument("--history", default=None, help="a level history file: a page of its latest pair per case")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.history:
        stem = os.path.splitext(os.path.basename(args.history))[0]
        print(history_page(history.read_history(args.history), args.out or os.path.join(history.DEFAULT_OUT, stem + ".html")))
        return 0
    if not args.run:
        ap.error("a run folder, or --history FILE")
    print(write(args.run, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
