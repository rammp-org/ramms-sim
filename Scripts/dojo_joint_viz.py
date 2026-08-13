"""Dojo Joint Viz — Blender addon to inspect and exercise dojo_* annotations.

Overlay (3D viewport):
  - joint AXIS through each part origin (orange=revolute/continuous,
    green=prismatic, grey=fixed),
  - LIMITS (arc fan for revolute, travel segment for prismatic),
  - loop-closure EMPTIES (dojo_connect): magenta cross + line to target.

Exercise: select a part, drag "Preview" — the part sweeps through its
limits about its annotated pivot+axis. With "Solve Closures" on, every
other part in the same closure-connected mechanism is numerically posed to
keep the closure pins together, so the WHOLE linkage moves like the real
four-bar. The panel shows the residual pin separation: a residual that
won't go near zero means an anchor/axis/limit is wrong — which is exactly
what this tool is for. "Reset Previews" restores everything.

Install: Edit > Preferences > Add-ons > Install... > this file, or open in
the Text Editor and Run Script. Panel: 3D Viewport > N-sidebar > "Dojo".
NOTE: start previews from the assembly's rest pose (closure reference
points are captured on first use).
"""
bl_info = {
    "name": "Dojo Joint Viz",
    "author": "RAMMS pipeline",
    "version": (2, 8),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Dojo",
    "description": "Author, visualize and exercise dojo_* joint annotations",
    "category": "3D View",
}

import math
import os
import subprocess

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

AXIS_LEN = 0.14
ARC_R = 0.07
COLORS = {
    "revolute": (1.0, 0.55, 0.1, 1.0),
    "continuous": (1.0, 0.35, 0.1, 1.0),
    "prismatic": (0.2, 0.9, 0.3, 1.0),
    "fixed": (0.55, 0.55, 0.55, 0.6),
}
CLOSURE_COLOR = (1.0, 0.2, 0.9, 1.0)

_handle = None
_closure_refs = {}   # empty name -> (target name, target-local ref point)
_solving = False
_graph = None        # cached annotation graph (the blend has thousands of
                     # raw-CAD objects; scanning bpy.data.objects per solve
                     # or per redraw is what made v1.1 unusably slow)


def _build_graph():
    global _graph
    parts, closures = {}, []
    for o in bpy.data.objects:
        if o.get("dojo_joint") is None:
            continue
        if o.type == "EMPTY":
            if o.get("dojo_connect") is not None:
                # host = nearest MOVABLE annotated ancestor: fixed parts are
                # rigid with their parent (the exporter merges them), so the
                # pin belongs to whatever they are welded onto.
                host = o.parent
                while host is not None and (
                        host.get("dojo_joint") is None
                        or str(host.get("dojo_joint")) == "fixed"):
                    host = host.parent
                if host is not None:
                    closures.append((o.name, host.name, str(o["dojo_connect"])))
            continue
        parts[o.name] = o
    _graph = {"parts": parts, "closures": closures, "mech": {}}
    return _graph


def _get_graph():
    return _graph if _graph is not None else _build_graph()


def _root_of(o):
    while o.parent is not None:
        o = o.parent
    return o


def _axis_world_rest(o):
    ax = o.get("dojo_axis")
    v = Vector(ax) if ax is not None else Vector((0, 0, 1))
    if v.length < 1e-9:
        v = Vector((0, 0, 1))
    return (_root_of(o).matrix_world.to_3x3() @ v).normalized()


def _joint_kind(o):
    return str(o.get("dojo_joint", "fixed"))


def _limits(o, kind):
    lim = o.get("dojo_limits")
    if lim is not None and len(lim) == 2:
        if kind in ("revolute", "continuous"):
            return math.radians(float(lim[0])), math.radians(float(lim[1]))
        return float(lim[0]), float(lim[1])
    return (-math.pi / 4, math.pi / 4) if kind in ("revolute", "continuous") else (-0.05, 0.05)


def _ensure_rest(o):
    """Capture rest basis + local axis once (call while at rest pose)."""
    if o.get("_dojo_rest_basis") is None:
        o["_dojo_rest_basis"] = [c for row in o.matrix_basis for c in row]
        aw = _axis_world_rest(o)
        o["_dojo_local_axis"] = list(o.matrix_world.to_3x3().inverted() @ aw)
    rb = o["_dojo_rest_basis"]
    return (Matrix([rb[0:4], rb[4:8], rb[8:12], rb[12:16]]),
            Vector(o["_dojo_local_axis"]).normalized())


def _ref(o, kind):
    """dojo_ref: joint value of the MODELED pose (rad / m internally)."""
    v = o.get("dojo_ref")
    if v is None:
        return 0.0
    return math.radians(float(v)) if kind in ("revolute", "continuous") else float(v)


def _park_slider(o):
    """Set the Preview slider to o's current value — or, if o is UNPOSED,
    its modeled/rest value (stale _dojo_preview IDProps saved in old blends
    must not override ref)."""
    global _solving
    if o is None or o.get("dojo_joint") is None or o.type == "EMPTY":
        return
    if o.get("_dojo_rest_basis") is None:
        if o.get("_dojo_preview") is not None:
            del o["_dojo_preview"]  # stale: part is physically at rest
        v = _rest_value(o)
    else:
        v = float(o.get("_dojo_preview", _rest_value(o)))
    _solving = True
    try:
        bpy.context.scene.dojo_preview_value = v
    finally:
        _solving = False


def _rest_value(o):
    """Slider value [0,1] at which the part sits in its modeled pose."""
    kind = _joint_kind(o)
    if kind == "fixed":
        return 0.5
    lo, hi = _limits(o, kind)
    if hi <= lo:
        return 0.5
    return min(1.0, max(0.0, (_ref(o, kind) - lo) / (hi - lo)))


def _pose(o, value):
    """Pose o's joint at `value` in [0,1] across its ABSOLUTE limits; the
    modeled pose corresponds to joint value dojo_ref (MuJoCo `ref`)."""
    kind = _joint_kind(o)
    if kind == "fixed":
        return
    rest, axis_l = _ensure_rest(o)
    lo, hi = _limits(o, kind)
    t = lo + (hi - lo) * value - _ref(o, kind)
    if kind in ("revolute", "continuous"):
        o.matrix_basis = rest @ Matrix.Rotation(t, 4, axis_l)
    else:
        o.matrix_basis = rest @ Matrix.Translation(axis_l * t)


def _mechanism_of(driven):
    """Connected component of `driven` over closure edges + annotated
    parent-child links (cached; the root object stays fixed)."""
    g = _get_graph()
    hit = g["mech"].get(driven.name)
    if hit is not None:
        free_n, cl = hit
        return ([bpy.data.objects[n] for n in free_n],
                [(bpy.data.objects[e], bpy.data.objects[h], bpy.data.objects[t])
                 for e, h, t in cl])
    parts = g["parts"]
    edges = {}

    def link(a, b):
        edges.setdefault(a, set()).add(b)
        edges.setdefault(b, set()).add(a)

    def _movable(name):
        o_ = parts.get(name)
        if o_ is None:
            return name
        while o_ is not None and _joint_kind(o_) == "fixed":
            p_ = o_.parent
            while p_ is not None and p_.name not in parts:
                p_ = p_.parent
            o_ = p_
        return o_.name if o_ is not None else name

    for ename, hname, tname in g["closures"]:
        if tname in parts:
            link(_movable(hname), _movable(tname))
    for o in parts.values():
        if _joint_kind(o) == "fixed":
            continue  # rigid with parent; connectivity passes through below
        p = o.parent
        while p is not None and (p.name not in parts
                                 or _joint_kind(parts[p.name]) == "fixed"):
            p = p.parent
        if p is not None:
            link(o.name, p.name)

    comp, stack = {driven.name}, [driven.name]
    while stack:
        for nb in edges.get(stack.pop(), ()):
            if nb not in comp:
                comp.add(nb)
                stack.append(nb)
    cl = [(e, h, t) for e, h, t in g["closures"]
          if (h in comp or t in comp) and bpy.data.objects.get(t) is not None]
    free_n = [n for n in comp
              if n != driven.name and _joint_kind(parts[n]) in ("revolute", "continuous", "prismatic")]
    g["mech"][driven.name] = (free_n, cl)
    return ([bpy.data.objects[n] for n in free_n],
            [(bpy.data.objects[e], bpy.data.objects[h], bpy.data.objects[t])
             for e, h, t in cl])


def _violation(closures, depsgraph):
    total = 0.0
    for e, host, tgt in closures:
        ref = _closure_refs.get(e.name)
        if ref is None:
            _closure_refs[e.name] = (tgt.name,
                                     list(tgt.matrix_world.inverted() @ e.matrix_world.translation))
            continue
        _, local = ref
        pin_on_target = tgt.matrix_world @ Vector(local)
        total += (e.matrix_world.translation - pin_on_target).length_squared
    return total


def _prime_refs(ctx):
    """Capture every closure's target-local pin point. MUST run at rest."""
    ctx.view_layer.update()
    for ename, hname, tname in _get_graph()["closures"]:
        e = bpy.data.objects.get(ename)
        tgt = bpy.data.objects.get(tname)
        if e is not None and tgt is not None and ename not in _closure_refs:
            _closure_refs[ename] = (
                tname, list(tgt.matrix_world.inverted() @ e.matrix_world.translation))


def _joint_xform(o, value):
    kind = _joint_kind(o)
    rest, axis_l = _ensure_rest(o)
    lo, hi = _limits(o, kind)
    t = lo + (hi - lo) * value - _ref(o, kind)
    if kind in ("revolute", "continuous"):
        return rest @ Matrix.Rotation(t, 4, axis_l)
    if kind == "prismatic":
        return rest @ Matrix.Translation(axis_l * t)
    return rest


class _FK:
    """Analytic forward kinematics over the Blender hierarchy: world
    matrices from matrix_basis composition, NO depsgraph updates. Posed
    parts get basis = rest @ joint(value); everything else keeps its
    current basis."""

    def __init__(self, values):
        self.values = values          # name -> value in [0,1]
        self.cache = {}

    def world(self, o):
        m = self.cache.get(o.name)
        if m is not None:
            return m
        v = self.values.get(o.name)
        basis = _joint_xform(o, v) if v is not None else o.matrix_basis
        if o.parent is None:
            m = basis
        else:
            m = self.world(o.parent) @ o.matrix_parent_inverse @ basis
        self.cache[o.name] = m
        return m


def _violation_fk(closures, values):
    fk = _FK(values)
    total = 0.0
    for e, host, tgt in closures:
        ref = _closure_refs.get(e.name)
        if ref is None:
            continue
        pin_on_target = fk.world(tgt) @ Vector(ref[1])
        total += (fk.world(e).translation - pin_on_target).length_squared
    return total


def _residuals_fk(closures, values):
    """Flat residual vector: 3 components per mated pin."""
    fk = _FK(values)
    r = []
    for e, host, tgt in closures:
        ref = _closure_refs.get(e.name)
        if ref is None:
            continue
        d = fk.world(e).translation - (fk.world(tgt) @ Vector(ref[1]))
        r.extend((d.x, d.y, d.z))
    return r


def _solve_lin(A, b):
    """Tiny Gaussian elimination with partial pivoting (n <= ~12)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r_: abs(M[r_][col]))
        if abs(M[piv][col]) < 1e-14:
            return None
        M[col], M[piv] = M[piv], M[col]
        inv = 1.0 / M[col][col]
        for r_ in range(col + 1, n):
            f = M[r_][col] * inv
            if f == 0.0:
                continue
            for c_ in range(col, n + 1):
                M[r_][c_] -= f * M[col][c_]
    x = [0.0] * n
    for r_ in range(n - 1, -1, -1):
        acc = M[r_][n] - sum(M[r_][c_] * x[c_] for c_ in range(r_ + 1, n))
        x[r_] = acc / M[r_][r_]
    return x


def _solve_closures(driven, ctx):
    """Damped Gauss-Newton over ALL free joints simultaneously (analytic
    FK). Coordinate descent (kept as a warm start) stalls when the driven
    joint needs coordinated multi-link motion — e.g. driving a motor rod."""
    free, closures = _mechanism_of(driven)
    n_locked = sum(1 for o in free if o.get("_dojo_locked"))
    free = [o for o in free if not o.get("_dojo_locked")]
    closures = [c for c in closures if c[0].name in _closure_refs]
    if not closures:
        return -1.0   # no pins in this mechanism
    if not free:
        return -2.0 - n_locked  # pins exist but nothing may move
    values = {o.name: o.get("_dojo_preview", _rest_value(o)) for o in free}
    values[driven.name] = driven.get("_dojo_preview", _rest_value(driven))
    debug = ctx.scene.dojo_solve_debug

    # warm start: two coordinate-descent sweeps to land in the right basin
    best_total = _violation_fk(closures, values)
    for sweep in range(2):
        span = 0.6 / (2 ** sweep)
        for o in free:
            base_v = values[o.name]
            best_v, best_c = base_v, best_total
            for v in (max(0.0, base_v - span), min(1.0, base_v + span),
                      max(0.0, base_v - span / 3), min(1.0, base_v + span / 3)):
                values[o.name] = v
                c = _violation_fk(closures, values)
                if c < best_c:
                    best_v, best_c = v, c
            values[o.name] = best_v
            best_total = min(best_total, best_c)

    # damped Gauss-Newton
    names = [o.name for o in free]
    n = len(names)
    lam = 1e-4
    cost = best_total
    H = 1e-3
    for it in range(30):
        r0 = _residuals_fk(closures, values)
        m = len(r0)
        if m == 0:
            break
        J = [[0.0] * n for _ in range(m)]
        for j, nm in enumerate(names):
            v0 = values[nm]
            h = H if v0 + H <= 1.0 else -H
            values[nm] = v0 + h
            r1 = _residuals_fk(closures, values)
            values[nm] = v0
            inv_h = 1.0 / h
            for i in range(m):
                J[i][j] = (r1[i] - r0[i]) * inv_h
        JtJ = [[sum(J[k][a] * J[k][b] for k in range(m)) for b in range(n)]
               for a in range(n)]
        Jtr = [sum(J[k][a] * r0[k] for k in range(m)) for a in range(n)]
        stepped = False
        for _try in range(4):
            A = [[JtJ[a][b] + (lam if a == b else 0.0) for b in range(n)]
                 for a in range(n)]
            delta = _solve_lin(A, [-g for g in Jtr])
            if delta is None:
                lam *= 10
                continue
            trial = {nm: min(1.0, max(0.0, values[nm] + delta[j]))
                     for j, nm in enumerate(names)}
            merged = dict(values)
            merged.update(trial)
            c = _violation_fk(closures, merged)
            if c < cost:
                values.update(trial)
                cost = c
                lam = max(1e-7, lam / 3)
                stepped = True
                break
            lam *= 10
        if debug:
            print("[dojo] GN it %d residual %.3f mm (lam %.1e)" % (
                it, math.sqrt(cost / len(closures)) * 1000, lam))
        if not stepped or cost < (0.0002 ** 2) * len(closures):
            break
    best_total = cost

    # apply the solution to the real objects, ONE depsgraph update
    for o in free:
        _pose(o, values[o.name])
        o["_dojo_preview"] = values[o.name]
    ctx.view_layer.update()
    if debug:
        for e, host, tgt in closures:
            ref = _closure_refs[e.name]
            d = (e.matrix_world.translation
                 - (tgt.matrix_world @ Vector(ref[1]))).length
            print("[dojo]   pin %s -> %s : %.2f mm" % (host.name, tgt.name, d * 1000))
    return math.sqrt(_violation_fk(closures, values) / len(closures))


def _preview_update(scene):
    global _solving
    if _solving:
        return
    ctx = bpy.context
    o = ctx.active_object
    if o is None or o.get("dojo_joint") is None or o.type == "EMPTY":
        return
    _solving = True
    try:
        if not _closure_refs:
            _prime_refs(ctx)  # first use: capture pin refs at rest
        _pose(o, scene.dojo_preview_value)
        o["_dojo_preview"] = scene.dojo_preview_value
        if scene.dojo_solve_closures:
            res = _solve_closures(o, ctx)
            scene.dojo_last_residual = res * 1000.0 if res >= 0 else res * 1000.0
        else:
            ctx.view_layer.update()
    finally:
        _solving = False


# ------------------------------------------------------------------ overlay
def _joint_parts(ctx):
    g = _get_graph()
    sel = ({o.name for o in ctx.selected_objects}
           if ctx.scene.dojo_viz_selected_only else None)
    for name, o in g["parts"].items():
        if sel is None or name in sel:
            yield o, _joint_kind(o)
    for ename, hname, tname in g["closures"]:
        e = bpy.data.objects.get(ename)
        if e is not None and (sel is None or ename in sel or hname in sel):
            yield e, "closure"


def _perp(a):
    p = a.cross(Vector((0, 0, 1)))
    if p.length < 1e-6:
        p = a.cross(Vector((0, 1, 0)))
    return p.normalized()


def _draw():
    ctx = bpy.context
    if not getattr(ctx.scene, "dojo_viz_enabled", False):
        return
    lines, colors = [], []
    for o, kind in _joint_parts(ctx):
        pivot = o.matrix_world.translation
        if kind == "closure":
            s = 0.02
            for d in (Vector((s, 0, 0)), Vector((0, s, 0)), Vector((0, 0, s))):
                lines += [pivot - d, pivot + d]
                colors += [CLOSURE_COLOR, CLOSURE_COLOR]
            ref = _closure_refs.get(o.name)
            tgt = bpy.data.objects.get(str(o["dojo_connect"]))
            if ref is not None and tgt is not None:
                pin = tgt.matrix_world @ Vector(ref[1])
                sep = (pin - pivot).length
                c = (1.0, 0.1, 0.1, 1.0) if sep > 0.005 else CLOSURE_COLOR
                lines += [pivot, pin]
                colors += [c, c]
            elif tgt is not None:
                lines += [pivot, tgt.matrix_world.translation]
                colors += [CLOSURE_COLOR, (1.0, 0.2, 0.9, 0.25)]
            continue
        col = COLORS.get(kind, COLORS["fixed"])
        a = _axis_world_rest(o)
        lines += [pivot - a * AXIS_LEN, pivot + a * AXIS_LEN]
        colors += [col, col]
        lim = o.get("dojo_limits")
        if lim is not None and len(lim) == 2:
            if kind in ("revolute", "continuous"):
                p0 = _perp(a)
                lo, hi = math.radians(float(lim[0])), math.radians(float(lim[1]))
                steps = max(4, int(abs(hi - lo) / 0.12))
                prev = None
                for i in range(steps + 1):
                    t = lo + (hi - lo) * i / steps
                    pt = pivot + (Matrix.Rotation(t, 4, a).to_3x3() @ p0) * ARC_R
                    if prev is not None:
                        lines += [prev, pt]
                        colors += [col, col]
                    if i in (0, steps):
                        lines += [pivot, pt]
                        colors += [col, col]
                    prev = pt
            elif kind == "prismatic":
                lo, hi = float(lim[0]), float(lim[1])
                t0, t1 = pivot + a * lo, pivot + a * hi
                p0 = _perp(a) * 0.015
                lines += [t0, t1, t0 - p0, t0 + p0, t1 - p0, t1 + p0]
                colors += [col] * 6
    if ctx.scene.dojo_show_mechanism:
        act = ctx.active_object
        if act is not None and act.get("dojo_joint") is not None and act.type != "EMPTY":
            free, closures = _mechanism_of(act)
            members = {act.name} | {o.name for o in free}
            ecol = (0.2, 0.8, 1.0, 0.9)
            for name in members:
                o = bpy.data.objects[name]
                p = o.parent
                while p is not None and p.get("dojo_joint") is None:
                    p = p.parent
                if p is not None and (p.name in members or p.parent is None):
                    lines += [o.matrix_world.translation, p.matrix_world.translation]
                    colors += [ecol, (0.2, 0.8, 1.0, 0.25)]
                d = 0.012
                pv = o.matrix_world.translation
                hl = (1.0, 1.0, 0.2, 1.0) if name == act.name else ecol
                for dd in (Vector((d, 0, 0)), Vector((0, d, 0)), Vector((0, 0, d))):
                    lines += [pv - dd, pv + dd]
                    colors += [hl, hl]
    if not lines:
        return
    shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, "LINES",
                             {"pos": [tuple(v) for v in lines], "color": colors})
    batch.draw(shader)
    gpu.state.line_width_set(1.0)




# ========================================================================
# AUTHORING (v2.0): typed UI over the dojo_* custom properties.
# The IDProperties stay the exporter's source of truth; the PropertyGroup
# below is a synced mirror that gives dropdowns/sliders/object pickers.
# ========================================================================
_ui_syncing = False
_msgbus_owner = object()

_JOINT_ITEMS = [
    ("NONE", "(not a part)", "no dojo_joint property"),
    ("fixed", "Fixed", "merged into parent at export"),
    ("revolute", "Revolute", "limited hinge"),
    ("continuous", "Continuous", "unlimited hinge (wheels)"),
    ("prismatic", "Prismatic", "linear slide"),
]
_COLLISION_ITEMS = [
    ("AUTO", "(auto)", "cylinder for continuous joints, island boxes otherwise"),
    ("cylinder", "Cylinder", ""), ("box", "Box", ""), ("boxes", "Boxes", ""),
    ("convex", "Convex", ""), ("sphere", "Sphere", ""), ("none", "None", ""),
]


def _dirty():
    """Authoring changed the model: drop caches so viz/solve see it."""
    global _graph
    _graph = None
    _closure_refs.clear()


def _w(o, key, value):
    o["dojo_" + key] = value
    _dirty()


def _wdel(o, key):
    if o.get("dojo_" + key) is not None:
        del o["dojo_" + key]
        _dirty()


def _upd(key, transform=None):
    def cb(self, context):
        if _ui_syncing:
            return
        o = self.id_data
        v = getattr(self, key)
        if transform:
            v = transform(v)
        if key == "joint_type":
            if v == "NONE":
                _wdel(o, "joint")
            else:
                _w(o, "joint", v)
        elif key == "collision":
            if v == "AUTO":
                _wdel(o, "collision")
            else:
                _w(o, "collision", v)
        elif key == "axis":
            _w(o, "axis", list(v))
        elif key == "use_limits":
            if v:
                _w(o, "limits", [self.limit_lo, self.limit_hi])
            else:
                _wdel(o, "limits")
        elif key in ("limit_lo", "limit_hi"):
            if self.use_limits:
                _w(o, "limits", [self.limit_lo, self.limit_hi])
                _park_slider(o)
        elif key == "mimic_target":
            if v is not None:
                _w(o, "mimic", v.name)
            else:
                _wdel(o, "mimic")
        elif key == "mimic_ratio":
            _w(o, "mimic_ratio", v)
        else:
            _w(o, key, v)
            if key == "ref":
                _park_slider(o)
    return cb


class DojoUIProps(bpy.types.PropertyGroup):
    joint_type: bpy.props.EnumProperty(name="Joint", items=_JOINT_ITEMS,
                                       default="NONE", update=_upd("joint_type"))
    axis: bpy.props.FloatVectorProperty(name="Axis (root frame)", size=3,
                                        default=(0.0, 1.0, 0.0), update=_upd("axis"))
    use_limits: bpy.props.BoolProperty(name="Limits", default=False,
                                       update=_upd("use_limits"))
    ref: bpy.props.FloatProperty(
        name="Rest / ref", default=0.0, update=_upd("ref"),
        description="Joint value of the MODELED pose (deg for revolute, m "
                    "for prismatic). Limits are absolute: a part modeled at "
                    "its -30 stop gets ref=-30, limits [-30, 30]")
    limit_lo: bpy.props.FloatProperty(name="Lo", default=-30.0, update=_upd("limit_lo"))
    limit_hi: bpy.props.FloatProperty(name="Hi", default=30.0, update=_upd("limit_hi"))
    mass: bpy.props.FloatProperty(name="Mass (kg, 0=auto)", default=0.0, min=0.0,
                                  update=_upd("mass"))
    motor_torque: bpy.props.FloatProperty(name="Motor force/torque", default=0.0,
                                          min=0.0, update=_upd("motor_torque"))
    motor_velocity: bpy.props.FloatProperty(name="Motor velocity", default=0.0,
                                            min=0.0, update=_upd("motor_velocity"))
    spring_stiffness: bpy.props.FloatProperty(name="Spring stiffness", default=0.0,
                                              min=0.0, update=_upd("spring_stiffness"))
    spring_damping: bpy.props.FloatProperty(name="Spring damping", default=0.0,
                                            min=0.0, update=_upd("spring_damping"))
    spring_rest: bpy.props.FloatProperty(name="Spring rest", default=0.0,
                                         update=_upd("spring_rest"))
    friction: bpy.props.FloatProperty(name="Joint friction", default=0.0, min=0.0,
                                      update=_upd("friction"))
    collision: bpy.props.EnumProperty(name="Collision", items=_COLLISION_ITEMS,
                                      default="AUTO", update=_upd("collision"))
    mimic_target: bpy.props.PointerProperty(name="Mimic joint", type=bpy.types.Object,
                                            update=_upd("mimic_target"))
    mimic_ratio: bpy.props.FloatProperty(name="Mimic ratio", default=1.0,
                                         update=_upd("mimic_ratio"))


def _sync_ui(o):
    """IDProps -> UI mirror (never triggers write-backs)."""
    global _ui_syncing
    if o is None:
        return
    _ui_syncing = True
    try:
        ui = o.dojo_ui
        jt = o.get("dojo_joint")
        ui.joint_type = str(jt) if jt in ("fixed", "revolute", "continuous",
                                          "prismatic") else "NONE"
        ax = o.get("dojo_axis")
        if ax is not None and len(ax) == 3:
            ui.axis = tuple(float(v) for v in ax)
        lim = o.get("dojo_limits")
        ui.use_limits = lim is not None and len(lim) == 2
        if ui.use_limits:
            ui.limit_lo, ui.limit_hi = float(lim[0]), float(lim[1])
        for k in ("mass", "motor_torque", "motor_velocity", "spring_stiffness",
                  "spring_damping", "spring_rest", "friction", "ref"):
            v = o.get("dojo_" + k)
            setattr(ui, k, float(v) if v is not None else 0.0)
        col = o.get("dojo_collision")
        ui.collision = str(col) if col in ("cylinder", "box", "boxes", "convex",
                                           "sphere", "none") else "AUTO"
        mim = o.get("dojo_mimic")
        ui.mimic_target = bpy.data.objects.get(str(mim)) if mim else None
        v = o.get("dojo_mimic_ratio")
        ui.mimic_ratio = float(v) if v is not None else 1.0
    finally:
        _ui_syncing = False


def _on_active_changed():
    try:
        _sync_ui(bpy.context.view_layer.objects.active)
    except Exception:
        pass


_last_sync = None


def _sync_check(scene=None, depsgraph=None):
    """Reliable Author-panel sync: msgbus on LayerObjects.active does not
    fire on plain viewport clicks in 4.x/5.x, so poll the active object on
    depsgraph updates (name-change guarded — terminates, no ping-pong)."""
    global _last_sync
    try:
        o = bpy.context.view_layer.objects.active
    except Exception:
        return
    if o is not None and o.name != _last_sync:
        _last_sync = o.name
        _sync_ui(o)
        if not _solving:
            _park_slider(o)


from bpy.app.handlers import persistent


@persistent
def _on_file_load(_dummy):
    """New file in this session: every cache holds dead references."""
    global _graph, _last_sync
    _graph = None
    _closure_refs.clear()
    _last_sync = None


class DOJO_OT_axis_preset(bpy.types.Operator):
    bl_idname = "dojo.axis_preset"
    bl_label = "Axis Preset"
    bl_description = "Set the joint axis (root frame)"
    axis: bpy.props.EnumProperty(items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")])

    def execute(self, context):
        o = context.active_object
        v = {"X": [1.0, 0.0, 0.0], "Y": [0.0, 1.0, 0.0], "Z": [0.0, 0.0, 1.0]}[self.axis]
        _w(o, "axis", v)
        _sync_ui(o)
        return {"FINISHED"}


class DOJO_OT_origin_to_cursor(bpy.types.Operator):
    bl_idname = "dojo.origin_to_cursor"
    bl_label = "Pivot = 3D Cursor"
    bl_description = ("Move the part's origin (= its joint pivot) to the 3D "
                     "cursor. Tip: Alt+Click a bore's edge loop in Edit Mode, "
                     "Shift+S Cursor-to-Selected, then this")

    def execute(self, context):
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        _dirty()
        return {"FINISHED"}


class DOJO_OT_add_closure(bpy.types.Operator):
    bl_idname = "dojo.add_closure"
    bl_label = "Add Closure @ Cursor"
    bl_description = ("Create a loop-closure pin at the 3D cursor between the "
                     "ACTIVE object (host) and the other selected object. "
                     "Put the cursor ON the pin axis first")

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and len(context.selected_objects) == 2)

    def execute(self, context):
        host = context.active_object
        other = [o for o in context.selected_objects if o is not host][0]
        ename = "closure_%s__%s" % (host.name, other.name)
        if bpy.data.objects.get(ename):
            self.report({"WARNING"}, "closure already exists: %s" % ename)
            return {"CANCELLED"}
        e = bpy.data.objects.new(ename, None)
        e.empty_display_type = "SPHERE"
        e.empty_display_size = 0.01
        context.scene.collection.objects.link(e)
        e.parent = host
        context.view_layer.update()
        e.matrix_world = Matrix.Translation(context.scene.cursor.location.copy())
        e["dojo_joint"] = "fixed"
        e["dojo_connect"] = other.name
        e["dojo_axis"] = [0.0, 0.0, 1.0]
        _dirty()
        self.report({"INFO"}, "added %s" % ename)
        return {"FINISHED"}


class DOJO_OT_delete_closure(bpy.types.Operator):
    bl_idname = "dojo.delete_closure"
    bl_label = "Delete Closure"
    ename: bpy.props.StringProperty()

    def execute(self, context):
        e = bpy.data.objects.get(self.ename)
        if e:
            bpy.data.objects.remove(e, do_unlink=True)
            _dirty()
        return {"FINISHED"}


class DOJO_OT_toggle_lock(bpy.types.Operator):
    bl_idname = "dojo.toggle_lock"
    bl_label = "Toggle Solver Lock"
    bl_description = ("Locked joints are excluded from the closure solve "
                     "(non-back-drivable: carriages, idle leadscrews)")
    part: bpy.props.StringProperty()

    def execute(self, context):
        o = bpy.data.objects.get(self.part)
        if o is None:
            return {"CANCELLED"}
        if o.get("_dojo_locked"):
            del o["_dojo_locked"]
        else:
            o["_dojo_locked"] = 1
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class DOJO_OT_clear_part(bpy.types.Operator):
    bl_idname = "dojo.clear_part"
    bl_label = "Clear Dojo Data"
    bl_description = "Remove every dojo_* property from the active object"

    def execute(self, context):
        o = context.active_object
        for k in list(o.keys()):
            if k.startswith("dojo_"):
                del o[k]
        _dirty()
        _sync_ui(o)
        return {"FINISHED"}


class DOJO_PT_author(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dojo"
    bl_label = "Author"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        lay = self.layout
        o = context.active_object
        if o is None:
            lay.label(text="no active object")
            return
        if o.type == "EMPTY" and o.get("dojo_connect") is not None:
            lay.label(text="closure: %s" % o.name, icon="LINKED")
            lay.label(text="-> %s" % o.get("dojo_connect"))
            lay.label(text="(its position IS the pin anchor)")
            op = lay.operator("dojo.delete_closure", icon="X")
            op.ename = o.name
            return
        ui = o.dojo_ui
        lay.prop(ui, "joint_type")
        if ui.joint_type != "NONE":
            row = lay.row(align=True)
            row.prop(ui, "axis", text="")
            row2 = lay.row(align=True)
            for ax in ("X", "Y", "Z"):
                row2.operator("dojo.axis_preset", text=ax).axis = ax
            lay.operator("dojo.origin_to_cursor", icon="PIVOT_CURSOR")
            if ui.joint_type in ("revolute", "prismatic"):
                row = lay.row(align=True)
                row.prop(ui, "use_limits")
                if ui.use_limits:
                    row.prop(ui, "limit_lo")
                    row.prop(ui, "limit_hi")
                    lay.label(text="(degrees for revolute, metres for prismatic)")
            lay.prop(ui, "ref")
            lay.label(text="modeled pose sits at slider %.2f" % _rest_value(o))
            box = lay.box()
            box.label(text="Motor", icon="AUTO")
            box.prop(ui, "motor_torque")
            box.prop(ui, "motor_velocity")
            box = lay.box()
            box.label(text="Spring / Damper", icon="FORCE_HARMONIC")
            box.prop(ui, "spring_stiffness")
            box.prop(ui, "spring_damping")
            box.prop(ui, "spring_rest")
            lay.prop(ui, "friction")
            lay.prop(ui, "mass")
            lay.prop(ui, "collision")
            box = lay.box()
            box.label(text="Mimic", icon="DRIVER")
            box.prop(ui, "mimic_target")
            if ui.mimic_target is not None:
                box.prop(ui, "mimic_ratio")
        lay.separator()
        lay.operator("dojo.add_closure", icon="LINKED")
        lay.operator("dojo.clear_part", icon="TRASH")


# ------------------------------------------------------------------ ops/UI
class DOJO_OT_reset_previews(bpy.types.Operator):
    bl_idname = "dojo.reset_previews"
    bl_label = "Reset Previews"
    bl_description = "Restore every part posed by the preview slider"

    def execute(self, context):
        global _graph
        n = 0
        for o in bpy.data.objects:
            rb = o.get("_dojo_rest_basis")
            if rb is not None:
                o.matrix_basis = Matrix([rb[0:4], rb[4:8], rb[8:12], rb[12:16]])
                for k in ("_dojo_rest_basis", "_dojo_local_axis", "_dojo_preview"):
                    if o.get(k) is not None:
                        del o[k]
                n += 1
        for o in bpy.data.objects:
            if o.get("_dojo_preview") is not None and o.get("_dojo_rest_basis") is None:
                del o["_dojo_preview"]  # stale from older sessions
        _closure_refs.clear()
        _graph = None
        act = context.active_object
        context.scene.dojo_preview_value = _rest_value(act) if (
            act is not None and act.get("dojo_joint") is not None
            and act.type != "EMPTY") else 0.5
        context.scene.dojo_last_residual = -1.0
        context.view_layer.update()
        self.report({"INFO"}, "restored %d parts" % n)
        return {"FINISHED"}


class DOJO_PT_panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dojo"
    bl_label = "Dojo Joint Viz"

    def draw(self, context):
        lay = self.layout
        s = context.scene
        lay.prop(s, "dojo_viz_enabled", text="Show Joint Overlay")
        lay.prop(s, "dojo_viz_selected_only", text="Selected Only")
        lay.prop(s, "dojo_solve_closures", text="Solve Closures")
        row = lay.row(align=True)
        row.prop(s, "dojo_show_mechanism", text="Show Mechanism")
        row.prop(s, "dojo_solve_debug", text="Debug Prints")
        box = lay.box()
        o = context.active_object
        if o is not None and o.get("dojo_joint") is not None and o.type != "EMPTY":
            box.label(text="%s  [%s]" % (o.name, o.get("dojo_joint")))
            lim = o.get("dojo_limits")
            if lim is not None:
                box.label(text="limits: %s" % list(lim))
            box.prop(s, "dojo_preview_value", text="Preview", slider=True)
            if s.dojo_last_residual >= 0:
                icon = "CHECKMARK" if s.dojo_last_residual < 5.0 else "ERROR"
                box.label(text="closure residual: %.1f mm" % s.dojo_last_residual,
                          icon=icon)
            elif s.dojo_last_residual <= -2000.0:
                box.label(text="SOLVE SKIPPED: all %d mechanism joints are "
                               "LOCKED (padlocks below)" % int(-s.dojo_last_residual - 2000),
                          icon="ERROR")
            elif s.dojo_last_residual == -1000.0:
                box.label(text="no closure pins in this mechanism", icon="INFO")
            if s.dojo_show_mechanism:
                free, closures = _mechanism_of(o)
                mb = lay.box()
                mb.label(text="mechanism (%d parts, %d pins)" % (len(free) + 1, len(closures)),
                         icon="CONSTRAINT")
                col = mb.column(align=True)
                for part in [o] + sorted(free, key=lambda x: x.name):
                    v = part.get("_dojo_preview")
                    row = col.row(align=True)
                    row.label(text="%s%s [%s]%s" % (
                        "> " if part is o else "   ", part.name,
                        _joint_kind(part),
                        ("  @%.2f" % v) if v is not None else ""))
                    locked = bool(part.get("_dojo_locked"))
                    op = row.operator("dojo.toggle_lock", text="",
                                      icon="LOCKED" if locked else "UNLOCKED",
                                      emboss=False)
                    op.part = part.name
                for e, h, t in closures:
                    ref = _closure_refs.get(e.name)
                    if ref is not None:
                        d = (e.matrix_world.translation
                             - (t.matrix_world @ Vector(ref[1]))).length * 1000
                        col.label(text="   %s <-pin-> %s  (%.1f mm)" % (h.name, t.name, d))
                    else:
                        col.label(text="   %s <-pin-> %s" % (h.name, t.name))
        else:
            box.label(text="select an annotated part to preview")
        lay.operator("dojo.reset_previews", icon="LOOP_BACK")




# ========================================================================
# EXPORT (v2.3): run robot_export.py on chosen roots in a BACKGROUND
# Blender subprocess against the saved .blend — the open session is never
# mutated. Any annotated object can be a root, so selecting a sub-assembly
# exports just that subsystem.
# ========================================================================
_export_proc = None
_export_roots = ""


def _detect_roots():
    """Topmost ancestors of annotated parts = assembly root candidates
    (the root object itself usually has no dojo_joint — e.g. 'mebot')."""
    g = _get_graph()
    roots = set()
    for o in g["parts"].values():
        top = o
        while top.parent is not None:
            top = top.parent
        roots.add(top.name)
    return sorted(roots)


def _export_selected_roots(ctx):
    sel = [o.name for o in ctx.selected_objects if o.get("dojo_joint") is not None
           and o.type != "EMPTY"]
    return sel if sel else _detect_roots()


class DOJO_OT_export(bpy.types.Operator):
    bl_idname = "dojo.export"
    bl_label = "Export Roots"
    bl_description = ("Run robot_export.py on the selected annotated objects "
                     "(or all detected roots) in a background Blender "
                     "process. Requires the file to be saved")

    _timer = None

    @classmethod
    def poll(cls, context):
        global _export_proc
        return _export_proc is None

    def execute(self, context):
        global _export_proc, _export_roots
        s_ = context.scene
        if not bpy.data.filepath:
            self.report({"ERROR"}, "save the .blend first")
            return {"CANCELLED"}
        if bpy.data.is_dirty:
            self.report({"ERROR"}, "unsaved changes — save first (the export "
                                   "runs against the file on disk)")
            return {"CANCELLED"}
        script = bpy.path.abspath(s_.dojo_export_script)
        if not os.path.isfile(script):
            self.report({"ERROR"}, "exporter not found: %s" % script)
            return {"CANCELLED"}
        roots = _export_selected_roots(context)
        if not roots:
            self.report({"ERROR"}, "no annotated roots found/selected")
            return {"CANCELLED"}
        env = dict(os.environ)
        env["ROBOT_ROOTS"] = ",".join(roots)
        if s_.dojo_export_dir.strip():
            env["ROBOT_OUT"] = bpy.path.abspath(s_.dojo_export_dir)
        env["ROBOT_BAKE_RES"] = str(s_.dojo_export_bake_res)
        if s_.dojo_export_bake_force:
            env["ROBOT_BAKE_FORCE"] = "1"
        _export_roots = ",".join(roots)
        _export_proc = subprocess.Popen(
            [bpy.app.binary_path, "-b", bpy.data.filepath, "--python", script],
            env=env, cwd=os.path.dirname(script),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, "exporting %s in background..." % _export_roots)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _export_proc
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if _export_proc is None:
            return {"FINISHED"}
        rc = _export_proc.poll()
        if rc is None:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        out = context.scene.dojo_export_dir.strip() or "(default output dir)"
        if rc == 0:
            self.report({"INFO"}, "export DONE: %s -> %s" % (_export_roots, out))
        else:
            self.report({"ERROR"}, "export FAILED (exit %d) — run headless to "
                                   "see the log" % rc)
        _export_proc = None
        return {"FINISHED"}


class DOJO_PT_export(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Dojo"
    bl_label = "Export"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        lay = self.layout
        s_ = context.scene
        lay.prop(s_, "dojo_export_script", text="Exporter")
        lay.prop(s_, "dojo_export_dir", text="Output")
        row = lay.row(align=True)
        row.prop(s_, "dojo_export_bake_res", text="Bake res")
        row.prop(s_, "dojo_export_bake_force", text="Force bake")
        roots = _export_selected_roots(context)
        box = lay.box()
        box.label(text="roots (%s):" % ("selection" if any(
            o.get("dojo_joint") is not None for o in context.selected_objects)
            else "auto-detected"))
        for r in roots[:8]:
            box.label(text="  " + r)
        if len(roots) > 8:
            box.label(text="  ... +%d more" % (len(roots) - 8))
        running = _export_proc is not None
        lay.operator("dojo.export",
                     text="Exporting..." if running else "Export Roots",
                     icon="EXPORT")
        if bpy.data.is_dirty:
            lay.label(text="unsaved changes — save first", icon="ERROR")


classes = (DojoUIProps, DOJO_OT_reset_previews, DOJO_OT_axis_preset,
           DOJO_OT_toggle_lock,
           DOJO_OT_origin_to_cursor, DOJO_OT_add_closure,
           DOJO_OT_delete_closure, DOJO_OT_clear_part,
           DOJO_OT_export,
           DOJO_PT_panel, DOJO_PT_author, DOJO_PT_export)


def register():
    global _handle
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.dojo_viz_enabled = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.dojo_viz_selected_only = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.dojo_solve_closures = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.dojo_solve_debug = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.dojo_show_mechanism = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.dojo_last_residual = bpy.props.FloatProperty(default=-1.0)
    bpy.types.Scene.dojo_preview_value = bpy.props.FloatProperty(
        default=0.5, min=0.0, max=1.0,
        update=lambda self, ctx: _preview_update(self))
    bpy.types.Object.dojo_ui = bpy.props.PointerProperty(type=DojoUIProps)
    bpy.types.Scene.dojo_export_script = bpy.props.StringProperty(
        subtype="FILE_PATH", default=r"C:\Users\waemf\data\robot_export.py")
    bpy.types.Scene.dojo_export_dir = bpy.props.StringProperty(
        subtype="DIR_PATH", default="",
        description="ROBOT_OUT override; empty = exporter default")
    bpy.types.Scene.dojo_export_bake_res = bpy.props.IntProperty(
        default=1024, min=64, max=4096)
    bpy.types.Scene.dojo_export_bake_force = bpy.props.BoolProperty(default=False)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"),
                             owner=_msgbus_owner, args=(),
                             notify=_on_active_changed)
    bpy.app.handlers.depsgraph_update_post.append(_sync_check)
    bpy.app.handlers.load_post.append(_on_file_load)
    _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    if _sync_check in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_check)
    if _on_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_file_load)
    del bpy.types.Object.dojo_ui
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    for p in ("dojo_viz_enabled", "dojo_viz_selected_only", "dojo_solve_closures",
              "dojo_solve_debug", "dojo_show_mechanism",
              "dojo_last_residual", "dojo_preview_value",
              "dojo_export_script", "dojo_export_dir",
              "dojo_export_bake_res", "dojo_export_bake_force"):
        delattr(bpy.types.Scene, p)


if __name__ == "__main__":
    register()
