"""The level-assist course maps' terrain: every course's ground as planes, and the slabs that build them. One
definition for the map builder (make_level_maps.py, inside the editor) and for the course runner and its measures
(plain CPython). No `unreal` import; only the standard library and ../curb_maps/curb_terrain.py (its Plane and Box).

World frame, centimetres. A course is a lane along +X: its centreline is y = 0 and it starts at x = 0. The ground is a
row of planes ("segments"), each given by its length along the centreline and two angles:

    grade   rises along +X (deg): the pitch a robot heading +X stands at (nose up positive)
    cross   rises toward +Y (deg): its roll (positive with the right, +Y, side up -- the sign of level.pref.roll)

Every seam is STEP-FREE: two planes can only meet along the line where they are equal, so the seams are not chosen,
they follow from the planes:

    fold    the grade changes (with or without the cross fall): the planes meet along a line through the joint's
            point on the centreline, square to the path when only the grade changes and skewed when the cross fall
            changes with it (pitch and roll together, the wheels crossing one at a time). A fold whose grade
            increases is a valley, one whose grade decreases a crest.
    twist   only the cross fall changes: the two planes meet along the centreline alone, so no line across the path
            joins them. They are joined by two wedge planes round the joint's point (an X of fold lines, TWIST_K of
            sideways run per unit along the path): the left wedge carries the mean cross fall and climbs, the right
            one carries it and falls, the centreline stays where it was. That is a warp: a wheel pair is twisted
            against the other while it passes.

How a step-free seam is built from boxes ("one cube per plane", exact in UE collision and in MuJoCo, which collides a
mesh as its convex hull): what a trace from above finds is the highest slab top over a point. Across a valley the
ground is the higher of two planes, so the two slabs simply overlap. Across a crest it is the lower, so each slab's
top must END EXACTLY on the fold line: a slab's two edges across its `along` direction lie exactly over lines (as the
curb maps' sidewalk lip does), so a slab that ends on a crest is laid out along that fold's normal. A twist is one
crest line through the joint (the "ridge") with two planes on each side, each pair a valley: four slabs with an edge
on the ridge. A plane that needs exact edges on two lines that are not parallel gets two slabs (coplanar: they
overlap without a seam). Layout.flush() proves it for every course: what the slabs build equals the planes meant,
everywhere on the lane, and no seam has a step.

The robot never drives from the level's floor onto a slab: every course starts and ends on its own run-in and
run-out slabs (the curb maps' road stands 1 cm over their floor, and that lip stalls a robot at half stick).

The maps name no robot. What a robot is expected to do on each is its owner's business, kept with the robot.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_CURB = os.path.normpath(os.path.join(HERE, "..", "curb_maps"))
if _CURB not in sys.path:
    sys.path.insert(0, _CURB)
import curb_terrain as ct  # noqa: E402

MAPS = "/Game/Maps/Level"
FLOOR_TOP_Z = ct.FLOOR_TOP_Z
FLOOR_CLEAR = 1.0  # the lowest point of a lane stays this far over the level's floor
START_ABOVE_SURFACE = ct.START_ABOVE_SURFACE
LANE_W = 300.0  # a lane's width (cm)
E_MARGIN = 20.0  # the slabs reach this far past the lane's sides
PAD = 6.0  # how far a slab overlaps past a valley, or stops short of a line it must not cross
SLAB_THICK = 30.0
RUN = 480.0  # the flat run-in and run-out
START_IN = 120.0  # a start's distance from its end of the lane
END_MARGIN = 120.0  # a run ends this far before the lane does
TWIST_K = 0.75  # a twist's fold lines: sideways run per unit along the path
MAX_SKEW_DEG = 60.0  # a fold more skewed than this is refused (make it a twist, or change the planes)
REF_FOOTPRINT = ((30.0, 30.0), (30.0, -30.0), (-30.0, 30.0), (-30.0, -30.0))  # a stand-in wheel footprint (cm)
FLUSH_TOL_CM = 1e-3  # built against meant
SEAM_DELTA_CM = 0.01  # a seam's step is looked for this far either side of it
SEAM_STEP_TOL_CM = 0.02
DIRECTIONS = ("fwd", "rev")


def map_name(cid):
    return "Map_Level_%s_URL" % cid


def map_path(cid):
    return "%s/%s" % (MAPS, map_name(cid))


def tand(deg):
    return math.tan(math.radians(deg))


def atand(x):
    return math.degrees(math.atan(x))


def fit_gradient(points):
    """(dz/dx, dz/dy) of the least-squares plane through [(x, y, z), ...] (three or more, not in a line), or None."""
    n = len(points)
    if n < 3:
        return None
    sx = sum(p[0] for p in points) / n
    sy = sum(p[1] for p in points) / n
    sz = sum(p[2] for p in points) / n
    xx = sum((p[0] - sx) ** 2 for p in points)
    yy = sum((p[1] - sy) ** 2 for p in points)
    xy = sum((p[0] - sx) * (p[1] - sy) for p in points)
    xz = sum((p[0] - sx) * (p[2] - sz) for p in points)
    yz = sum((p[1] - sy) * (p[2] - sz) for p in points)
    det = xx * yy - xy * xy
    if abs(det) < 1e-9 * max(1.0, xx * yy):
        return None
    return ((xz * yy - yz * xy) / det, (yz * xx - xz * xy) / det)


def tilt_of(gradient, yaw_deg):
    """(pitch, roll) (deg) of a body standing on a plane of this gradient at heading yaw: the elevation of its forward
    axis (nose up positive) and of its right (+Y at yaw 0) axis (right side up positive) -- the level assist's
    convention, and curb_terrain.Plane.tilt_deg's."""
    return ct.Plane("fit", (0.0, 0.0), 0.0, gradient).tilt_deg(yaw_deg)


class Seg(object):
    """One plane of a course: `length` cm along the centreline, `grade` and `cross` in degrees."""

    def __init__(self, name, length, grade=0.0, cross=0.0):
        self.name = name
        self.length = float(length)
        self.grade = float(grade)
        self.cross = float(cross)

    def gradient(self):
        return (tand(self.grade), tand(self.cross))

    def slope_deg(self):
        return atand(math.hypot(*self.gradient()))


class Course(object):
    """A course's ground: its id, what it shows, its segments along +X (kind "path"), or a crown (kind "crown": two
    planes falling `crown` deg either side of a ridge that runs along the centreline, `length` long). `starts`: the
    named places a run can start from, beside the ones every course has (DEFAULT_STARTS): {name: {"seg": a segment's
    name and "frac": how far along it (0..1) -- or neither: START_IN from the lane's end the run starts at;
    "lateral": cm to the robot's right of the centreline; "path_yaw": the path's own direction off the lane's (deg,
    clockwise from above); "yaw": the robot's first heading off the path's}}."""

    def __init__(self, cid, title, segs=None, lane=LANE_W, kind="path", crown=0.0, length=None, starts=None,
                 twist_k=TWIST_K):
        self.id = cid
        self.title = title
        self.kind = kind
        self.segs = list(segs or [])
        self.lane = float(lane)
        self.crown = float(crown)
        self.length = float(length) if length is not None else sum(s.length for s in self.segs)
        self.twist_k = float(twist_k)
        self.starts = dict(DEFAULT_STARTS)
        self.starts.update(starts or {})

    def as_dict(self):
        return {"id": self.id, "title": self.title, "kind": self.kind, "lane": self.lane, "length": self.length,
                "crown": self.crown, "map": map_path(self.id), "starts": sorted(self.starts),
                "segments": [{"name": s.name, "length": s.length, "grade": s.grade, "cross": s.cross} for s in self.segs]}


DEFAULT_STARTS = {
    "centre": {},
    "left20": {"lateral": -20.0},
    "right20": {"lateral": 20.0},
    "yaw5": {"yaw": 5.0},
}

RAMP_1_12 = atand(1.0 / 12.0)  # 4.76 deg
FOLD_SLOPE, FOLD_SKEW = 6.0, 30.0  # a 6 deg plane whose fall line is 30 deg off the path
FOLD_GRADE = atand(tand(FOLD_SLOPE) * math.cos(math.radians(FOLD_SKEW)))  # 5.21
FOLD_CROSS = atand(tand(FOLD_SLOPE) * math.sin(math.radians(FOLD_SKEW)))  # 3.01


def _flat(name, length=RUN):
    return Seg(name, length)


COURSES = [
    Course("FLAT", "12 m of flat ground: the control", [_flat("flat", 1200.0)]),
    Course("RAMP5", "a 1:12 ramp (4.76 deg): 6 m up, a landing, 6 m down",
           [_flat("in"), Seg("up", 600.0, RAMP_1_12), _flat("landing", 360.0), Seg("down", 600.0, -RAMP_1_12), _flat("out")]),
    Course("RAMP8", "an 8 deg ramp: 4 m up, a landing, 4 m down",
           [_flat("in"), Seg("up", 400.0, 8.0), _flat("landing", 360.0), Seg("down", 400.0, -8.0), _flat("out")]),
    Course("RAMP12", "a 12 deg ramp: 3.6 m up, a landing, 3.6 m down",
           [_flat("in"), Seg("up", 360.0, 12.0), _flat("landing", 360.0), Seg("down", 360.0, -12.0), _flat("out")]),
    Course("CROSS2", "a lane falling 2 % (1.15 deg) to one side; the robot starts on it",
           [Seg("cross", 800.0, 0.0, atand(0.02))], lane=600.0),
    Course("CROSS6", "a lane falling 6 deg to one side; the robot starts on it", [Seg("cross", 800.0, 0.0, 6.0)], lane=600.0),
    Course("BREAK6", "flat, 6 deg up for 3.6 m, 6 deg down for 3.6 m, flat: a sag, a crest, a sag",
           [_flat("in"), Seg("up", 360.0, 6.0), Seg("down", 360.0, -6.0), _flat("out")]),
    Course("STEEPEN", "a grade breaking to a steeper one: 3 deg, then 6 deg, a landing, 6 deg down, then 3 deg",
           [_flat("in"), Seg("up3", 360.0, 3.0), Seg("up6", 360.0, 6.0), _flat("landing", 360.0), Seg("down6", 360.0, -6.0),
            Seg("down3", 360.0, -3.0), _flat("out")]),
    Course("WARP", "the cross fall changes sign along the path: flat, 6 deg one way, 6 deg the other, flat (three twists)",
           [_flat("in"), Seg("fall_left", 540.0, 0.0, 6.0), Seg("fall_right", 540.0, 0.0, -6.0), _flat("out")]),
    Course("CROWN", "two planes falling 2.3 deg either side of a ridge along the lane", kind="crown", crown=2.3,
           lane=600.0, length=1400.0,
           starts={"straddle": {}, "left": {"lateral": -80.0}, "right": {"lateral": 80.0},
                   "cross20": {"lateral": -150.0, "path_yaw": 20.0}}),
    Course("FOLD", "a 6 deg plane entered and left across fold lines 30 deg off square (pitch and roll together)",
           [_flat("in"), Seg("plane", 480.0, FOLD_GRADE, FOLD_CROSS), _flat("out")]),
    Course("COMBO", "a 5 deg grade carrying 3 deg of cross fall, breaking to 2 deg of the opposite cross fall (a twist on "
           "the grade), then a skewed crest onto the flat",
           [_flat("in"), Seg("grade_cross", 540.0, 5.0, 3.0), Seg("opposite", 540.0, 5.0, -2.0), _flat("out")]),
    Course("PARK", "two pads to stand on: a 6 deg grade and a 6 deg cross fall",
           [_flat("in"), Seg("pad_grade", 420.0, 6.0), _flat("landing"), Seg("pad_cross", 540.0, 0.0, 6.0), _flat("out")],
           starts={"pad_grade": {"seg": "pad_grade", "frac": 0.5}, "pad_cross": {"seg": "pad_cross", "frac": 0.5}}),
    Course("TRANSITIONS", "one run through them all: flat, grade up, flat, cross fall left, cross fall right, "
           "grade down with cross fall, flat",
           [_flat("in"), Seg("up", 360.0, 5.0), _flat("top"), Seg("fall_left", 540.0, 0.0, 4.0),
            Seg("fall_right", 480.0, 0.0, -4.0), Seg("down_cross", 360.0, -5.0, -4.0), _flat("out")]),
]
BY_ID = {c.id: c for c in COURSES}


class Slab(ct.Box):
    """A curb_terrain Box (an oriented box, its top on a plane, its two edges across `along` exactly over lines), with
    its top's true outline: on a plane with grade and cross fall together the other two edges are only roughly along
    `along`, so a point is in the slab when the plane's point over it is on the top face."""

    def placed(self):
        if getattr(self, "_placed", None) is None:
            centre, x_axis, normal, size = self.placement()
            y_axis = ct.cross(normal, x_axis)
            top = ct.add(centre, ct.mul(normal, 0.5 * size[2]))
            self._placed = (centre, x_axis, y_axis, normal, size, top)
        return self._placed

    def contains(self, x, y, eps=1e-6):
        _, x_axis, y_axis, _, size, top = self.placed()
        d = ct.sub((x, y, self.plane.z(x, y)), top)
        return abs(ct.dot(d, x_axis)) <= 0.5 * size[0] + eps and abs(ct.dot(d, y_axis)) <= 0.5 * size[1] + eps

    def shift(self):
        """How far the top's far edge is displaced sideways from its near edge (cm along side())."""
        _, x_axis, _, _, size, _ = self.placed()
        return size[0] * ct.dot(x_axis[:2], self.side())

    def body_points(self, depths=(2.0, 10.0, None), per_edge=7):
        """Points of the box's body under its top's rim (the top's outline pushed down along the normal): where a
        leaning side could come up through a neighbour."""
        _, x_axis, y_axis, normal, size, top = self.placed()
        out = []
        for i in range(per_edge):
            f = -0.5 + i / float(per_edge - 1)
            for u, w in ((f, -0.5), (f, 0.5), (-0.5, f), (0.5, f)):
                rim = ct.add(top, ct.add(ct.mul(x_axis, u * size[0]), ct.mul(y_axis, w * size[1])))
                for depth in depths:
                    out.append(ct.sub(rim, ct.mul(normal, size[2] if depth is None else depth)))
        return out


class Joint(object):
    """Where segment j ends and segment j + 1 begins: a fold or a twist through `p` on the centreline."""

    def __init__(self, j, p, g_a, g_b, k):
        self.j = j
        self.p = p
        d = (g_b[0] - g_a[0], g_b[1] - g_a[1])
        size = math.hypot(*d)
        if size < 1e-9:
            raise ValueError("segments %d and %d are one plane: make them one segment" % (j, j + 1))
        if abs(d[0]) > 1e-9:
            self.kind = "fold"
            s = 1.0 if d[0] > 0.0 else -1.0
            self.n = (s * d[0] / size, s * d[1] / size)  # the fold's normal, pointing on along the path
            self.valley = d[0] > 0.0
            self.skew_deg = math.degrees(math.atan2(self.n[1], self.n[0]))
            if abs(self.skew_deg) > MAX_SKEW_DEG:
                raise ValueError("the fold between segments %d and %d is %.0f deg off square (over %.0f): too little "
                                 "change of grade for its change of cross fall" % (j, j + 1, self.skew_deg, MAX_SKEW_DEG))
        else:
            self.kind = "twist"
            self.k = k
            self.ds = d[1]
            self.kappa = k if d[1] > 0.0 else -k  # the ridge: v = kappa x'
            root = math.sqrt(1.0 + k * k)
            # The ridge as a fold line: its normal pointing on along the path.
            self.n = (k / root, (-1.0 if self.kappa > 0.0 else 1.0) / root)
            self.valley = False
            self.skew_deg = math.degrees(math.atan2(self.n[1], self.n[0]))

    def side(self, x, y):
        """Which of the joint's regions (x, y) is in: "before", "after", and a twist's "left" and "right" wedges."""
        xr, v = x - self.p[0], y - self.p[1]
        if self.kind == "fold":
            return "after" if xr * self.n[0] + v * self.n[1] > 0.0 else "before"
        if v > self.k * abs(xr):
            return "left"
        if v < -self.k * abs(xr):
            return "right"
        return "before" if xr < 0.0 else "after"

    def line_x(self, v):
        """Where the joint's exact line (a fold's line, a twist's ridge) is at sideways offset v."""
        return self.p[0] - v * self.n[1] / self.n[0]

    def extent(self, half):
        """(x_lo, x_hi): what the joint's lines cover of the path within `half` of the centreline."""
        if self.kind == "twist":
            return (self.p[0] - half / self.k, self.p[0] + half / self.k)
        xs = (self.line_x(-half), self.line_x(half))
        return (min(xs), max(xs))

    def seams(self, half):
        """The joint's fold lines within `half` of the centreline: [((x, y), (x, y)), ...]."""
        if self.kind == "fold":
            return [((self.line_x(-half), -half), (self.line_x(half), half))]
        x, r = self.p[0], half / self.k
        return [((x, 0.0), (x + sx * r, sv * half)) for sx in (-1.0, 1.0) for sv in (-1.0, 1.0)]


class Layout(object):
    """Everything about one course's ground, placed in the world: its planes, its joints, the slabs that build it."""

    def __init__(self, course):
        self.c = course
        self.half = 0.5 * course.lane
        self.wm = self.half + E_MARGIN
        self.planes = {}
        self.joints = []
        self.slabs = []
        self.stations = [0.0]
        if course.kind == "crown":
            self._crown()
        else:
            self._path()
        low = min(self.intended_z(x, y) for x in _steps(0.0, course.length, 20.0) for y in _steps(-self.wm, self.wm, 20.0))
        self.lift = (FLOOR_TOP_Z + FLOOR_CLEAR) - low
        for p in self.planes.values():
            p.z_ref += self.lift
        self.check()

    # --- construction ---------------------------------------------------------------------------------------------
    def _crown(self):
        c, t = self.c, tand(self.c.crown)
        mid = (0.5 * c.length, 0.0)
        self.planes = {"crown_right": ct.Plane("crown_right", mid, 0.0, (0.0, -t)),  # +Y of the ridge: falls away
                       "crown_left": ct.Plane("crown_left", mid, 0.0, (0.0, t))}
        self.stations = [0.0, c.length]
        # Each slab's near edge exactly on the ridge (a crest), its `along` pointing away from it.
        self.slabs = [Slab("Level_crown_right", self.planes["crown_right"], mid, (0.0, 1.0), (0.0, self.wm),
                           (-0.5 * c.length, 0.5 * c.length), SLAB_THICK),
                      Slab("Level_crown_left", self.planes["crown_left"], mid, (0.0, -1.0), (0.0, self.wm),
                           (-0.5 * c.length, 0.5 * c.length), SLAB_THICK)]

    def _path(self):
        c = self.c
        names = [s.name for s in c.segs]
        if len(set(names)) != len(names):
            raise ValueError("%s: two segments share a name" % c.id)
        x = z = 0.0
        self.seg_planes = []
        for s in c.segs:
            p = ct.Plane(s.name, (x, 0.0), z, s.gradient())
            self.seg_planes.append(p)
            self.planes[s.name] = p
            z += s.gradient()[0] * s.length
            x += s.length
            self.stations.append(x)
        for j in range(len(c.segs) - 1):
            a, b = self.seg_planes[j], self.seg_planes[j + 1]
            jt = Joint(j, (self.stations[j + 1], 0.0), a.gradient, b.gradient, c.twist_k)
            if jt.kind == "twist":
                # The wedges: the plane before plus half the change of cross fall, climbing (left) or falling (right).
                zj = a.z(*jt.p)
                for sign, name in ((1.0, "twist%d_left" % j), (-1.0, "twist%d_right" % j)):
                    g = (a.gradient[0] + sign * 0.5 * jt.ds * jt.k, a.gradient[1] + 0.5 * jt.ds)
                    self.planes[name] = ct.Plane(name, jt.p, zj, g)
                jt.left, jt.right = self.planes["twist%d_left" % j], self.planes["twist%d_right" % j]
            self.joints.append(jt)
        for i in range(len(c.segs)):
            self._segment_slabs(i)
        for jt in self.joints:
            if jt.kind == "twist":
                self._twist_slabs(jt)

    def _n_at(self, origin, along, x, v):
        return (x - origin[0]) * along[0] + (v - origin[1]) * along[1]

    def _limit(self, origin, along, which, kind, jt):
        """Where a slab laid along `along` from `origin` ends, at its near or far end, measured along `along`:
        "free" the lane's end; "overlap" past a valley everywhere on the lane; "stop" short of a line everywhere on it
        (a crest it is not laid out on); "twist" short of a twist's lines."""
        far = which == "far"
        pick = max if far else min
        if kind == "free":
            x = self.c.length if far else 0.0
            return pick(self._n_at(origin, along, x, v) for v in (-self.wm, self.wm))
        if kind == "twist":
            x = jt.extent(self.wm)[0 if far else 1]
            ns = [self._n_at(origin, along, x, v) for v in (-self.wm, self.wm)]
            return (min(ns) - PAD) if far else (max(ns) + PAD)
        ns = [self._n_at(origin, along, jt.line_x(v), v) for v in (-self.wm, self.wm)]
        if kind == "overlap":
            return (max(ns) + PAD) if far else (min(ns) - PAD)
        return (min(ns) - PAD) if far else (max(ns) + PAD)  # "stop"

    def _end_kind(self, jt):
        if jt is None:
            return "free"
        if jt.kind == "twist":
            return "twist"
        return "overlap" if jt.valley else "exact"

    def _add_slab(self, label, plane, origin, along, n_range, cover):
        """A slab whose top covers the points `cover` sideways (and E_MARGIN more), whatever its top's skew."""
        if n_range[1] - n_range[0] < 1.0:
            return None
        side = (-along[1], along[0])
        es = [(p[0] - origin[0]) * side[0] + (p[1] - origin[1]) * side[1] for p in cover]
        e0, e1 = min(es) - E_MARGIN, max(es) + E_MARGIN
        shift = Slab(label, plane, origin, along, n_range, (e0, e1), SLAB_THICK).shift()
        slab = Slab(label, plane, origin, along, n_range, (e0 - max(shift, 0.0), e1 - min(shift, 0.0)), SLAB_THICK)
        self.slabs.append(slab)
        return slab

    def _lane_corners(self, origin, along, n_range):
        """Where a slab's two edges across `along` meet the lane's sides."""
        out = []
        for n in n_range:
            for v in (-self.half, self.half):
                # origin + along n + side e, at y = v.
                e = (v - origin[1] - along[1] * n) / along[0]
                out.append((origin[0] + along[0] * n - along[1] * e, v))
        return out

    def _segment_slabs(self, i):
        """A segment's slabs: one laid out square to the path between its seams, and, for each skewed crest at an
        end, one laid out along that fold with its edge exactly on it. The skewed one reaches as far toward the
        other end as that end allows, so the two together leave nothing uncovered (coplanar: no seam)."""
        c = self.c
        plane = self.seg_planes[i]
        near = self.joints[i - 1] if i > 0 else None
        far = self.joints[i] if i < len(c.segs) - 1 else None
        kn, kf = self._end_kind(near), self._end_kind(far)
        label = "Level_%02d_%s" % (i, c.segs[i].name)

        def skewed(kind, jt):
            return kind == "exact" and abs(jt.n[1]) > 1e-9

        def other(kind):
            return "stop" if kind == "exact" else kind

        whole = False  # a skewed slab already covers the whole segment
        if skewed(kn, near) and skewed(kf, far) and abs(near.n[0] * far.n[1] - near.n[1] * far.n[0]) < 1e-9:
            n1 = self._n_at(near.p, near.n, far.p[0], far.p[1])
            self._add_slab(label + "_skew", plane, near.p, near.n, (0.0, n1), self._lane_corners(near.p, near.n, (0.0, n1)))
            whole = True
        else:
            for which, kind, jt, k_other, j_other in (("near", kn, near, kf, far), ("far", kf, far, kn, near)):
                if not skewed(kind, jt):
                    continue
                lim = self._limit(jt.p, jt.n, "far" if which == "near" else "near", other(k_other), j_other)
                need = 2.0 * self.wm * abs(jt.n[1]) + 2.0 * PAD  # past the triangle a square slab cannot reach
                if other(k_other) in ("stop", "twist") and abs(lim) < need:
                    raise ValueError("%s: segment %s is too short for the skewed seam at its %s end" % (c.id, c.segs[i].name, which))
                rng = (0.0, lim) if which == "near" else (lim, 0.0)
                self._add_slab(label + "_skew_" + which, plane, jt.p, jt.n, rng, self._lane_corners(jt.p, jt.n, rng))
                whole = whole or other(k_other) in ("free", "overlap")
        if whole:
            return
        origin, along = (self.stations[i], 0.0), (1.0, 0.0)
        n0 = self._limit(origin, along, "near", other(kn) if skewed(kn, near) else kn, near) if kn != "exact" or skewed(kn, near) else 0.0
        n1 = (self._limit(origin, along, "far", other(kf) if skewed(kf, far) else kf, far) if kf != "exact" or skewed(kf, far)
              else c.segs[i].length)
        slab = self._add_slab(label, plane, origin, along, (n0, n1), self._lane_corners(origin, along, (n0, n1)))
        if slab is None and not (skewed(kn, near) or skewed(kf, far)):
            raise ValueError("%s: segment %s is too short for the seams at its ends" % (c.id, c.segs[i].name))

    def _twist_slabs(self, jt):
        """A twist's four slabs, each with an edge exactly on the ridge: the planes before and after it, and the two
        wedges. On each side of the ridge the ground is the higher of two of them."""
        root = math.sqrt(1.0 + jt.k * jt.k)
        upper = (-jt.kappa / root, 1.0 / root)  # the ridge's normal toward v > kappa x'
        up = 1.0 if jt.kappa > 0.0 else -1.0
        x, reach, h = jt.p[0], self.wm / jt.k, self.wm
        base = "Level_twist%02d" % jt.j
        plans = [
            (base + "_before", self.seg_planes[jt.j], up, [(x - reach - 3.0 * PAD, -h), (x - reach - 3.0 * PAD, h), jt.p]),
            (base + "_after", self.seg_planes[jt.j + 1], -up, [(x + reach + 3.0 * PAD, -h), (x + reach + 3.0 * PAD, h), jt.p]),
            (base + "_left", jt.left, 1.0, [(x - reach, h), (x + reach, h), jt.p]),
            (base + "_right", jt.right, -1.0, [(x - reach, -h), (x + reach, -h), jt.p]),
        ]
        for label, plane, sign, cover in plans:
            along = (upper[0] * sign, upper[1] * sign)
            depth = max((p[0] - jt.p[0]) * along[0] + (p[1] - jt.p[1]) * along[1] for p in cover)
            self._add_slab(label, plane, jt.p, along, (0.0, depth), cover)

    # --- the ground -----------------------------------------------------------------------------------------------
    def piece_at(self, x, y):
        """The name of the plane meant at (x, y) (the planes go on past the lane's sides and ends)."""
        if self.c.kind == "crown":
            return "crown_right" if y >= 0.0 else "crown_left"
        for jt in self.joints:
            s = jt.side(x, y)
            if s == "before":
                return self.c.segs[jt.j].name
            if s == "left":
                return jt.left.name
            if s == "right":
                return jt.right.name
        return self.c.segs[-1].name

    def intended_z(self, x, y):
        """The ground meant at (x, y): the course's planes, joined at their seams."""
        return self.planes[self.piece_at(x, y)].z(x, y)

    def surface_z(self, x, y):
        """The topmost surface under (x, y) as built: what a trace from above would hit (the floor off the slabs)."""
        z = FLOOR_TOP_Z
        for b in self.slabs:
            if b.contains(x, y):
                z = max(z, b.plane.z(x, y))
        return z

    def in_lane(self, x, y, margin=0.0):
        return -margin <= x <= self.c.length + margin and abs(y) <= self.half + margin

    def ground_attitude(self, points, yaw_deg):
        """(pitch, roll) (deg, tilt_of's convention) of the ground under a robot at heading yaw whose standing wheels
        are over `points` [(x, y), ...]: the plane through the surface under them (least squares), so it turns
        smoothly as the wheels cross a seam one by one. With fewer than three points, or points in a line: the plane
        under their middle."""
        pts = [(p[0], p[1], self.surface_z(p[0], p[1])) for p in points]
        g = fit_gradient(pts)
        if g is None:
            n = max(1, len(pts))
            mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
            g = self.planes[self.piece_at(mx, my)].gradient
        return tilt_of(g, yaw_deg)

    def plane_attitude(self, x, y, yaw_deg):
        """(pitch, roll) of the one plane meant at (x, y), at heading yaw."""
        return self.planes[self.piece_at(x, y)].tilt_deg(yaw_deg)

    def seams(self):
        """Every fold line on the lane: [(label, (x, y), (x, y)), ...]."""
        if self.c.kind == "crown":
            return [("ridge", (0.0, 0.0), (self.c.length, 0.0))]
        out = []
        for jt in self.joints:
            a, b = self.c.segs[jt.j].name, self.c.segs[jt.j + 1].name
            for k, (p, q) in enumerate(jt.seams(self.half - 1.0)):
                out.append(("%s>%s%s" % (a, b, "" if jt.kind == "fold" else " twist %d" % k), p, q))
        return out

    def seam_points(self, per_seam=25):
        """(label, (x, y) before the seam, (x, y) after it): pairs SEAM_DELTA_CM either side of every seam."""
        out = []
        for label, p, q in self.seams():
            d = ct.sub(q, p)
            length = math.hypot(*d)
            n = (-d[1] / length, d[0] / length)
            for i in range(per_seam):
                f = (i + 0.5) / per_seam
                m = (p[0] + f * d[0], p[1] + f * d[1])
                out.append((label, (m[0] - n[0] * SEAM_DELTA_CM, m[1] - n[1] * SEAM_DELTA_CM),
                            (m[0] + n[0] * SEAM_DELTA_CM, m[1] + n[1] * SEAM_DELTA_CM)))
        return out

    # --- checks ---------------------------------------------------------------------------------------------------
    def flush(self, step=5.0):
        """How well the slabs build the planes meant: {"max_dev_cm": the worst of |built - meant| over the lane (a
        grid of `step` cm, and both sides of every seam), "at": where, "max_seam_step_cm": the worst change of the
        built surface across a seam (SEAM_DELTA_CM either side), "seam": which, "poke_cm": how far a slab's body
        comes up through the ground meant (0: none), "ok"}."""
        worst, at = 0.0, None
        for x in _steps(0.0, self.c.length, step):
            for y in _steps(-self.half, self.half, step):
                d = abs(self.surface_z(x, y) - self.intended_z(x, y))
                if d > worst:
                    worst, at = d, (round(x, 2), round(y, 2))
        seam_worst, seam_at = 0.0, None
        for label, a, b in self.seam_points():
            za, zb = self.surface_z(*a), self.surface_z(*b)
            for p, z in ((a, za), (b, zb)):
                d = abs(z - self.intended_z(*p))
                if d > worst:
                    worst, at = d, (round(p[0], 2), round(p[1], 2))
            if abs(zb - za) > seam_worst:
                seam_worst, seam_at = abs(zb - za), label
        poke = 0.0
        for slab in self.slabs:
            for p in slab.body_points():
                if self.in_lane(p[0], p[1]):
                    poke = max(poke, p[2] - self.intended_z(p[0], p[1]))
        return {"max_dev_cm": worst, "at": at, "max_seam_step_cm": seam_worst, "seam": seam_at, "poke_cm": poke,
                "ok": worst <= FLUSH_TOL_CM and seam_worst <= SEAM_STEP_TOL_CM and poke <= FLUSH_TOL_CM}

    def check(self):
        """The joints in order along the lane, none reaching into the next; the planes equal on every seam."""
        last = 0.0
        for jt in self.joints:
            lo, hi = jt.extent(self.wm)
            if lo < last - 1e-6:
                raise ValueError("%s: the seam after %s reaches back into the one before it: make %s longer"
                                 % (self.c.id, self.c.segs[jt.j].name, self.c.segs[jt.j].name))
            last = hi
        if last > self.c.length + 1e-6:
            raise ValueError("%s: the last seam runs off the lane's end" % self.c.id)
        for label, a, b in self.seam_points():
            m = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
            za = self.planes[self.piece_at(*a)].z(*m)
            zb = self.planes[self.piece_at(*b)].z(*m)
            if abs(za - zb) > 1e-6:
                raise ValueError("%s: the planes either side of the seam %s differ by %.4f cm on it" % (self.c.id, label, abs(za - zb)))

    # --- starts and paths -----------------------------------------------------------------------------------------
    def start(self, name="centre", direction="fwd"):
        """A named start, for a direction: {"name", "dir", "origin": [x, y] the path's first point, "path_yaw": the
        path's heading (deg, world), "yaw": the robot's first heading (deg, world), "xyz", "x_axis", "z_axis": the
        PlayerStart's pose (START_ABOVE_SURFACE over the ground, lying on the plane under the stand-in footprint),
        "length": how far along the path the run goes (END_MARGIN short of the lane's end, or of its side)}."""
        if direction not in DIRECTIONS:
            raise ValueError("a direction is %s, not %r" % (" or ".join(DIRECTIONS), direction))
        spec = self.c.starts.get(name)
        if spec is None:
            raise ValueError("%s has no start %r (it has %s)" % (self.c.id, name, ", ".join(sorted(self.c.starts))))
        sign = 1.0 if direction == "fwd" else -1.0
        if spec.get("seg"):
            i = [s.name for s in self.c.segs].index(spec["seg"])
            x = self.stations[i] + float(spec.get("frac", 0.5)) * self.c.segs[i].length
        else:
            x = START_IN if direction == "fwd" else self.c.length - START_IN
        y = sign * float(spec.get("lateral", 0.0))  # the robot's right is +Y heading +X, -Y heading -X
        path_yaw = (0.0 if direction == "fwd" else 180.0) + float(spec.get("path_yaw", 0.0))
        yaw = path_yaw + float(spec.get("yaw", 0.0))
        h = (math.cos(math.radians(path_yaw)), math.sin(math.radians(path_yaw)))
        # How far the path goes before it is END_MARGIN from the lane's end or 2/3 of the way to its side.
        length = 1e9
        if abs(h[0]) > 1e-9:
            length = min(length, ((self.c.length - END_MARGIN if h[0] > 0.0 else END_MARGIN) - x) / h[0])
        if abs(h[1]) > 1e-9:
            side = self.half * 2.0 / 3.0
            length = min(length, ((side if h[1] > 0.0 else -side) - y) / h[1])
        g = fit_gradient([(p[0], p[1], self.intended_z(p[0], p[1])) for p in footprint_at((x, y), yaw, REF_FOOTPRINT)])
        plane = ct.Plane("start", (x, y), self.intended_z(x, y), g)
        normal = plane.normal()
        f = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0.0)
        x_axis = ct.norm(ct.sub(f, ct.mul(normal, ct.dot(f, normal))))
        xyz = ct.add((x, y, plane.z(x, y)), ct.mul(normal, START_ABOVE_SURFACE))
        return {"name": name, "dir": direction, "origin": [x, y], "path_yaw": path_yaw, "yaw": yaw, "xyz": list(xyz),
                "x_axis": list(x_axis), "z_axis": list(normal), "length": max(0.0, length)}

    def profile(self, start, footprint=REF_FOOTPRINT, step=2.0, min_seg=30.0, length=None):
        """The ground along a start's path, as a robot with wheels at `footprint` ([(ahead, right), ...] cm from its
        reference point) meets it: {"origin", "path_yaw", "length", "segments": [{"name", "d0", "d1", "pitch", "roll",
        "slope"}] the stretches (cm along the path) where every wheel stands on one unchanging ground attitude, and
        "transitions": [{"d0", "d1", "d", "from", "to", "pitch_change", "roll_change"}] the stretches between them:
        d0 where the first wheel reaches the seam, d1 where the last one leaves it, d their middle}. The attitude is
        ground_attitude's (the plane through the ground under the wheels) at the path's heading."""
        origin, yaw = start["origin"], start["path_yaw"]
        length = start["length"] if length is None else length
        h = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)))
        rows = []
        n = max(1, int(math.ceil(length / step)))
        for i in range(n + 1):
            d = min(length, i * step)
            c = (origin[0] + h[0] * d, origin[1] + h[1] * d)
            pts = footprint_at(c, yaw, footprint)
            g = fit_gradient([(p[0], p[1], self.intended_z(p[0], p[1])) for p in pts])
            att = tilt_of(g, yaw) if g else self.plane_attitude(c[0], c[1], yaw)
            rows.append((d, att, tuple(sorted(set(self.piece_at(p[0], p[1]) for p in pts)))))
        runs = []  # [i0, i1]: rows of one attitude and one set of planes
        for i, (d, att, pieces) in enumerate(rows):
            if runs:
                a0, p0 = rows[runs[-1][0]][1], rows[runs[-1][0]][2]
                if abs(att[0] - a0[0]) < 1e-6 and abs(att[1] - a0[1]) < 1e-6 and pieces == p0:
                    runs[-1][1] = i
                    continue
            runs.append([i, i])
        segs = []
        for i0, i1 in runs:
            if rows[i1][0] - rows[i0][0] >= min_seg:
                att = rows[i0][1]
                segs.append({"name": "+".join(rows[i0][2]), "d0": rows[i0][0], "d1": rows[i1][0], "pitch": att[0],
                             "roll": att[1], "slope": atand(math.hypot(tand(att[0]), tand(att[1])))})
        trans = []
        for a, b in zip(segs, segs[1:]):
            trans.append({"d0": a["d1"], "d1": b["d0"], "d": 0.5 * (a["d1"] + b["d0"]), "from": a["name"], "to": b["name"],
                          "pitch_change": b["pitch"] - a["pitch"], "roll_change": b["roll"] - a["roll"]})
        return {"origin": list(origin), "path_yaw": yaw, "length": length, "segments": segs, "transitions": trans}

    def describe(self):
        c = self.c
        lines = ["%s: %s (%.0f x %.0f cm, lift %+.1f cm, %d slabs)" % (c.id, c.title, c.length, c.lane, self.lift, len(self.slabs))]
        for i, s in enumerate(c.segs):
            lines.append("  %-12s x %6.0f..%6.0f  grade %+5.2f  cross %+5.2f" % (s.name, self.stations[i], self.stations[i + 1],
                                                                              s.grade, s.cross))
        for jt in self.joints:
            lo, hi = jt.extent(self.half)
            lines.append("  seam at x %6.0f: %s%s, %+.0f deg off square, x %.0f..%.0f across the lane"
                         % (jt.p[0], jt.kind, "" if jt.kind == "twist" else (" (valley)" if jt.valley else " (crest)"),
                            jt.skew_deg, lo, hi))
        return "\n".join(lines)


def _steps(lo, hi, step):
    n = max(1, int(round((hi - lo) / step)))
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def footprint_at(centre, yaw_deg, footprint):
    """World (x, y) of footprint points [(ahead, right), ...] for a robot at `centre` heading yaw (UE: +Y is the
    right of +X, yaw positive clockwise from above)."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return [(centre[0] + a * c - r * s, centre[1] + a * s + r * c) for a, r in footprint]


_LAYOUTS = {}


def layout(cid):
    """A course's Layout (built once)."""
    if cid not in _LAYOUTS:
        _LAYOUTS[cid] = Layout(BY_ID[cid])
    return _LAYOUTS[cid]


if __name__ == "__main__":
    bad = 0
    for course in COURSES:
        L = layout(course.id)
        print(L.describe())
        r = L.flush()
        print("  flush: built - meant %.6f cm at %s; seam step %.5f cm (%s); poke %.5f cm: %s"
              % (r["max_dev_cm"], r["at"], r["max_seam_step_cm"], r["seam"], r["poke_cm"], "ok" if r["ok"] else "NOT FLUSH"))
        bad += 0 if r["ok"] else 1
    sys.exit(1 if bad else 0)
