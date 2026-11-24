"""Line charts as SVG text, with nothing but the standard library (no local Python here has matplotlib, and an SVG
opens anywhere): a figure is a stack of panels over one shared x axis, each panel one y axis with its own unit (never
two), lines that break where a value is missing, step lines for states, vertical marks and shaded spans across every
panel, and a legend.

    fig = Figure("RAMP5 fwd", "distance along the path (m)", [
        Panel("pitch (deg)", [Series("rider, assist on", xs, ys, "on"), Series("ground", xs, gs, "ground")]),
        Panel("level.state", [Series("state", xs, st, "on", step=True)], ticks=[(0, "Off"), (1, "Active")]),
    ], marks=[Mark(4.8, "in > up")], spans=[Span(4.5, 5.1)])
    write(path, render(fig))

Colour says which run a line belongs to, and nothing else: role "on" and "off" are the two series colours (in that
fixed order), "ground" and "pref" are inks. What a line is within a run is said by its weight and dash (`kind`:
"main" a 2 px line, "second" a thin dashed one, "dot" a dotted one). Every colour is a CSS class in the SVG's own
style block, with a dark set under prefers-color-scheme, so a figure reads on either surface, alone or inlined in a
page. The root carries the x axis's data range and pixel range (data-xmin, data-xmax, data-left, data-right) so a
page can add a crosshair.
"""

import math
import os
import tempfile

WIDTH = 980
LEFT, RIGHT, TOP, BOTTOM = 64, 150, 72, 40
PANEL_H = 118
PANEL_GAP = 26
MAX_POINTS = 800  # a line longer than this is thinned (every k-th point, the last kept)

# Light / dark: the surface, inks, hairlines, and the two series colours (blue, orange) in their fixed order.
STYLE = """
.sv-bg{fill:#fcfcfb}.sv-ink{fill:#0b0b0b}.sv-sub{fill:#52514e}.sv-mute{fill:#898781}
.sv-grid{stroke:#e1e0d9;stroke-width:1}.sv-axis{stroke:#c3c2b7;stroke-width:1}
.sv-line{fill:none;stroke-linejoin:round;stroke-linecap:round}
.sv-on{stroke:#2a78d6}.sv-off{stroke:#eb6834}.sv-ground{stroke:#898781}.sv-pref{stroke:#0b0b0b}
.sv-main{stroke-width:2}.sv-second{stroke-width:1.3;stroke-dasharray:5 3;opacity:.8}.sv-dot{stroke-width:1.3;stroke-dasharray:1.5 3.5}
.sv-mark{stroke:#52514e;stroke-width:1;stroke-dasharray:3 3}.sv-event{stroke:#0b0b0b;stroke-width:1}
.sv-span{fill:#898781;opacity:.12}.sv-ref{stroke:#c3c2b7;stroke-width:1;stroke-dasharray:6 4}
.sv-xhair{stroke:#52514e;stroke-width:1;visibility:hidden}
text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:11px}
.sv-title{font-size:14px;font-weight:600}.sv-ptitle{font-size:11.5px;font-weight:600}
@media (prefers-color-scheme: dark){
.sv-bg{fill:#1a1a19}.sv-ink{fill:#f0efec}.sv-sub{fill:#c3c2b7}.sv-mute{fill:#898781}
.sv-grid{stroke:#2c2c2a}.sv-axis{stroke:#383835}
.sv-on{stroke:#3987e5}.sv-off{stroke:#d95926}.sv-ground{stroke:#898781}.sv-pref{stroke:#f0efec}
.sv-mark{stroke:#c3c2b7}.sv-event{stroke:#f0efec}.sv-ref{stroke:#383835}.sv-xhair{stroke:#c3c2b7}
}
"""
ROLES = ("on", "off", "ground", "pref")
KINDS = ("main", "second", "dot")


class Series(object):
    """One line: its label, x and y values (a None or a non-finite y breaks the line), whose it is (`role`: on, off,
    ground, pref) and what it is (`kind`: main, second, dot); step: held from each x to the next (a state)."""

    def __init__(self, label, xs, ys, role="on", kind="main", step=False):
        if role not in ROLES or kind not in KINDS:
            raise ValueError("a series is one of %s and one of %s" % (ROLES, KINDS))
        self.label, self.role, self.kind, self.step = label, role, kind, step
        self.xs, self.ys = list(xs), list(ys)


class Panel(object):
    """One y axis: its title (with its unit), its lines, optionally its range (y_range), its tick names (ticks:
    [(value, name)]) and reference levels drawn across it (refs: [value])."""

    def __init__(self, title, series, y_range=None, ticks=None, refs=None, height=PANEL_H):
        self.title, self.series, self.y_range, self.ticks, self.refs, self.height = title, list(series), y_range, ticks, refs or [], height


class Mark(object):
    """A vertical line across every panel at x, with a label at the top; kind "seam" (dashed) or "event" (solid)."""

    def __init__(self, x, label, kind="seam"):
        self.x, self.label, self.kind = x, label, kind


class Span(object):
    """A shaded stretch of the x axis across every panel, with an optional name along the top."""

    def __init__(self, x0, x1, label=None):
        self.x0, self.x1, self.label = x0, x1, label


class Figure(object):
    def __init__(self, title, x_label, panels, marks=None, spans=None, names=None, subtitle=None, width=WIDTH):
        self.title, self.x_label, self.panels, self.subtitle, self.width = title, x_label, list(panels), subtitle, width
        self.marks, self.spans = list(marks or []), list(spans or [])
        self.names = list(names or [])  # [(x0, x1, name)]: what each stretch of the x axis is, written along the top


def ok(v):
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def nice_ticks(lo, hi, n=5):
    """About n round tick values covering [lo, hi] (steps of 1, 2 or 5 times a power of ten)."""
    if not (ok(lo) and ok(hi)):
        return [0.0, 1.0]
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < 1e-12:
        lo, hi = lo - 0.5, hi + 0.5
    raw = (hi - lo) / max(1, n)
    mag = 10.0 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1.0, 2.0, 5.0, 10.0) if m * mag >= raw - 1e-12)
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + 1e-9 * max(1.0, abs(hi)):
        out.append(0.0 if abs(v) < step * 1e-9 else round(v, 10))
        v += step
    return out


def fmt(v):
    if abs(v - round(v)) < 1e-9:
        return "%d" % round(v)
    return ("%.2f" % v).rstrip("0").rstrip(".")


def scale(v, lo, hi, a, b):
    """v in [lo, hi] mapped linearly onto [a, b]."""
    return a + (v - lo) / (hi - lo) * (b - a)


def thin(xs, ys, limit=MAX_POINTS):
    if len(xs) <= limit:
        return xs, ys
    k = int(math.ceil(len(xs) / float(limit)))
    keep = list(range(0, len(xs), k))
    if keep[-1] != len(xs) - 1:
        keep.append(len(xs) - 1)
    return [xs[i] for i in keep], [ys[i] for i in keep]


def path_of(xs, ys, sx, sy, step=False):
    """An SVG path through the points, broken where y is missing; a step line holds each y to the next x."""
    out, pen, last = [], False, None
    for x, y in zip(xs, ys):
        if not (ok(x) and ok(y)):
            pen = False
            continue
        px, py = sx(x), sy(y)
        if not pen:
            out.append("M%.1f %.1f" % (px, py))
            pen = True
        else:
            if step:
                out.append("L%.1f %.1f" % (px, last))
            out.append("L%.1f %.1f" % (px, py))
        last = py
    return " ".join(out)


def x_range(fig):
    xs = [x for p in fig.panels for s in p.series for x, y in zip(s.xs, s.ys) if ok(x) and ok(y)]
    xs += [m.x for m in fig.marks if ok(m.x)]
    if not xs:
        return 0.0, 1.0
    lo, hi = min(xs), max(xs)
    return (lo - 0.5, hi + 0.5) if hi - lo < 1e-12 else (lo, hi)


def y_range_of(panel):
    if panel.y_range:
        return panel.y_range
    ys = [y for s in panel.series for y in s.ys if ok(y)] + [r for r in panel.refs if ok(r)]
    if not ys:
        return 0.0, 1.0
    lo, hi = min(ys), max(ys)
    pad = 0.08 * (hi - lo) if hi - lo > 1e-9 else 0.5
    return lo - pad, hi + pad


def render(fig):
    """The figure as SVG text."""
    x0, x1 = x_range(fig)
    left, right = LEFT, fig.width - RIGHT
    height = TOP + sum(p.height for p in fig.panels) + PANEL_GAP * max(0, len(fig.panels) - 1) + BOTTOM
    bottom = height - BOTTOM

    def sx(v):
        return scale(v, x0, x1, left, right)

    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="%s" '
         'data-xmin="%r" data-xmax="%r" data-left="%d" data-right="%d" data-top="%d" data-bottom="%d">'
         % (fig.width, height, fig.width, height, esc(fig.title), x0, x1, left, right, TOP, bottom),
         "<style>%s</style>" % STYLE, '<rect class="sv-bg" width="%d" height="%d"/>' % (fig.width, height),
         '<text class="sv-ink sv-title" x="%d" y="18">%s</text>' % (left, esc(fig.title))]
    if fig.subtitle:
        o.append('<text class="sv-sub" x="%d" y="33">%s</text>' % (left, esc(fig.subtitle)))
    for sp in fig.spans:
        if ok(sp.x0) and ok(sp.x1):
            a, b = sorted((sx(sp.x0), sx(sp.x1)))
            o.append('<rect class="sv-span" x="%.1f" y="%d" width="%.1f" height="%d"/>' % (a, TOP, max(0.5, b - a), bottom - TOP))
    for a, b, name in fig.names:
        if ok(a) and ok(b):
            o.append('<text class="sv-mute" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (0.5 * (sx(a) + sx(b)), TOP - 22, esc(name)))
    y = TOP
    x_ticks = nice_ticks(x0, x1, 10)
    for k, p in enumerate(fig.panels):
        lo, hi = y_range_of(p)
        top, bot = y, y + p.height

        def sy(v, lo=lo, hi=hi, top=top, bot=bot):
            return scale(v, lo, hi, bot, top)

        o.append('<g class="sv-panel" data-ymin="%r" data-ymax="%r" data-y0="%d" data-y1="%d">' % (lo, hi, top, bot))
        ticks = p.ticks
        if not ticks:
            for n in (4, 6, 9, 14):  # at least three ticks inside the range, whatever it is
                ticks = [(v, fmt(v)) for v in nice_ticks(lo, hi, n) if lo - 1e-9 <= v <= hi + 1e-9]
                if len(ticks) >= 3:
                    break
        for v, name in ticks:
            if lo - 1e-9 <= v <= hi + 1e-9:
                o.append('<line class="sv-grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, right, sy(v), sy(v)))
                o.append('<text class="sv-mute" x="%d" y="%.1f" text-anchor="end">%s</text>' % (left - 6, sy(v) + 3.5, esc(name)))
        for r in p.refs:
            if lo <= r <= hi:
                o.append('<line class="sv-ref" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, right, sy(r), sy(r)))
        for v in x_ticks:
            o.append('<line class="sv-grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (sx(v), sx(v), bot, bot + 3))
        o.append('<line class="sv-axis" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, right, bot, bot))
        o.append('<text class="sv-sub sv-ptitle" x="%d" y="%d">%s</text>' % (left, top - 6, esc(p.title)))
        ly = top + 10
        for s in reversed(p.series):  # the first listed is drawn last: on top
            xs, ys = thin(s.xs, s.ys)
            d = path_of(xs, ys, sx, sy, s.step)
            if d:
                o.append('<path class="sv-line sv-%s sv-%s" d="%s"><title>%s</title></path>' % (s.role, s.kind, d, esc(s.label)))
        for s in p.series:
            # The panel's own legend, to its right: a line sample in the series' colour and style, its name in ink.
            o.append('<line class="sv-line sv-%s sv-%s" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (s.role, s.kind, right + 10, right + 32, ly, ly))
            o.append('<text class="sv-sub" x="%d" y="%d">%s</text>' % (right + 37, ly + 3.5, esc(s.label)))
            ly += 14
        o.append("</g>")
        y = bot + PANEL_GAP
    for i, m in enumerate(fig.marks):
        if not ok(m.x):
            continue
        px = sx(m.x)
        o.append('<line class="%s" x1="%.1f" x2="%.1f" y1="%d" y2="%d"><title>%s</title></line>'
                 % ("sv-event" if m.kind == "event" else "sv-mark", px, px, TOP, bottom, esc(m.label)))
        if m.kind == "event":  # events are named on the figure; seams by the stretches' names along the top
            o.append('<text class="sv-ink" x="%.1f" y="%d" transform="rotate(-90 %.1f %d)">%s</text>'
                     % (px - 3, bottom - 4, px - 3, bottom - 4, esc(m.label)))
    for v in x_ticks:
        o.append('<text class="sv-mute" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (sx(v), bottom + 15, fmt(v)))
    o.append('<text class="sv-sub" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (0.5 * (left + right), bottom + 32, esc(fig.x_label)))
    o.append('<line class="sv-xhair" x1="0" x2="0" y1="%d" y2="%d"/>' % (TOP, bottom))
    o.append("</svg>")
    return "\n".join(o)


def write(path, text):
    """Write text to path through a temporary file beside it (never a half-written file)."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
