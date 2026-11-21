"""The curb test maps' terrain: every scenario's surfaces as planes, and the boxes that build them. One definition
for the map builder (make_curb_maps.py, inside the editor) and for any runner and its metrics (plain CPython). No
`unreal` import.

World frame, centimetres. A robot starts at START heading +X. The near curb edge crosses its path (y = START[1]) at
E0. Everything else is measured in the edge's own frame:

    n = (cos a, sin a)    the edge normal, pointing from the road onto the sidewalk; `a` is the approach angle, the
                          angle between the robot's heading and n
    e = (-sin a, cos a)   along the edge

Three surfaces, each a plane:

    near   the road the robot starts on
    top    the sidewalk, `depth` deep along n
    far    the road beyond the sidewalk's far edge, for the descent

A plane's slope is given as two angles: `cross` along n (positive rises in +n, the direction the robot crosses the curb
in) and `grade` along e. Its gradient is tan(cross) n + tan(grade) e, so a 6 deg cross-slope with a 6 deg grade is an
8.5 deg slope; "6 deg in any direction" means a resultant of 6 deg, as 4.24 deg + 4.24 deg. The grade is shared by all
three surfaces, as a street's is; `twist` is extra grade on the sidewalk alone, which makes the step height change
along the edge.

The step heights are the ones the robot's centreline meets: `step_up` at E0 and `step_down` (negative) at E1, where
the path crosses the far edge.

Each surface is built from one oriented box whose top face lies on the plane (MuJoCo collides a mesh as its convex
hull, so one box per surface). The roads' boxes reach under the sidewalk so no crack shows at the foot of a curb face
that leans; the sidewalk box is deep enough to bury them. A plane's box is trimmed along the edge to the stretch where
the curb stays at least MIN_STEP_CM high: a twisted sidewalk otherwise dips below the road beside the crossing. The
whole scenario is lifted until every box top clears the level's floor (z = FLOOR_TOP_Z), so no floor pokes through a
sloped road.

The maps (MAPS) name no robot: they start whichever one is chosen (ARammsRobotGameMode; ?Robot=<id>, ramms.Robot).
What a given robot is expected to do on each is its owner's business, kept with the robot.
"""

import math

FLOOR_TOP_Z = -200.0
START = (270.0, 700.0)
E0 = (450.0, 700.0)
START_ABOVE_SURFACE = 5.0  # the PlayerStart's height over the surface, as on the flat maps

NEAR_BACK = 350.0  # how far the near road reaches back from the edge, along n
FAR_REACH = 350.0  # how far the far road reaches past the far edge, along n
UNDER = 30.0  # how far each road reaches under the sidewalk
ROAD_THICK = 40.0
SIDEWALK_THICK = 100.0
MARGIN_E = 250.0  # along the edge, either side of what the robot covers
ROBOT_E = 100.0  # the least of that a trimmed box may keep
TRACK_E = 30.0  # half a robot's track, roughly, along the edge (where the step is measured either side of the path)
# The descent's detection gate starts a robot on the sidewalk (Layout.top_start_pose):
# its centre this far past the near edge on the path, plus SCAN_HALF_E tan|approach|,
# so that the step detection's lanes, which start 10 cm behind the rear wheels and
# reach SCAN_HALF_E either side, stay clear of the curb it would have climbed.
TOP_START_PAST = 150.0
SCAN_HALF_E = 42.0
# A descent run from the sidewalk on one falling towards the
# far curb starts this far past the near edge instead: neither robot stands
# still on a slope in its drive mode, and from TOP_START_PAST it rolled over the
# far edge before the crossing began. The detection lanes behind its rear wheels
# still clear the near curb.
TOP_DOWNHILL_PAST = 100.0
MIN_STEP_CM = 3.0  # trim a box where its curb would be lower than this
KINK_HALF_E = 100.0  # a kinked sidewalk's yawed half reaches this far along the edge (cm)
RIDGE_THICK = 10.0  # a ridge's box: its top over the sidewalk, the rest buried in it
MIN_BURY_CM = 2.0  # a road's buried part stays this far under the sidewalk top
FLOOR_CLEAR = 1.0  # box tops stay this far over the floor

DIRECTIONS = ("up", "down")

# Where the maps are, and their names (make_curb_maps.py writes them).
MAPS = "/Game/Maps/Curb"
FLAT = "Flat"


def map_name(sid=None):
    """Map_Curb_<id>_URL, or the flat test map's (Map_Curb_Flat_URL) with no id."""
    return "Map_Curb_%s_URL" % (sid or FLAT)


def map_path(sid=None):
    return "%s/%s" % (MAPS, map_name(sid))


G4 = math.degrees(math.atan(math.tan(math.radians(6.0)) / math.sqrt(2.0)))  # 4.24: half a 6 deg resultant each way


class Terrain(object):
    """One scenario's terrain: its id, what it tests, and its surfaces.

    `need`: which requirement it exercises -- 0 baseline, 1 approach angle, 2 slopes, 3 both, 4 runtime safety (other
    curb heights, a combination past the robots, a ridge a detection would not see, maps a detection must refuse).
    The extra geometry of need 4: the sidewalk's edge yawed `kink` deg on its -e half (two boxes meeting on the
    path); the curb a ramp of `ramp` deg rather than a face; a ridge (height, cm past the near edge, width; cm)
    across the sidewalk. `dirs`: the directions the map tests (a map whose far side is an ordinary curb, or that has
    no sidewalk to start a descent on, tests its climb only). `robot_e`: how much of the curb (cm along the edge
    either side of what the robot covers) a trimmed box must keep -- ROBOT_E, or less where the curb changes height
    fast along the edge.
    """

    FIELDS = ("id", "title", "need", "approach", "grade", "near_cross", "top_cross", "far_cross", "twist", "step_up",
              "step_down", "depth", "kink", "ramp", "ridge", "robot_e", "dirs")

    def __init__(self, sid, title, need, approach=0.0, grade=0.0, near=0.0, top=0.0, far=0.0, twist=0.0,
                 step_up=15.24, step_down=-15.24, depth=300.0, kink=0.0, ramp=0.0, ridge=None, robot_e=None,
                 dirs=DIRECTIONS):
        self.id = sid
        self.title = title
        self.need = need
        self.approach = approach
        self.grade = grade
        self.near_cross = near
        self.top_cross = top
        self.far_cross = far
        self.twist = twist
        self.step_up = step_up
        self.step_down = step_down
        self.depth = depth
        self.kink = kink
        self.ramp = ramp
        self.ridge = tuple(ridge) if ridge else None
        self.robot_e = ROBOT_E if robot_e is None else robot_e
        self.dirs = tuple(dirs)

    def terrain_kwargs(self):
        """The arguments that build this terrain again (Terrain(**kwargs))."""
        return dict(sid=self.id, title=self.title, need=self.need, approach=self.approach, grade=self.grade,
                    near=self.near_cross, top=self.top_cross, far=self.far_cross, twist=self.twist,
                    step_up=self.step_up, step_down=self.step_down, depth=self.depth, kink=self.kink, ramp=self.ramp,
                    ridge=self.ridge, robot_e=self.robot_e, dirs=self.dirs)

    def as_dict(self):
        return dict(id=self.id, title=self.title, need=self.need, approach=self.approach, grade=self.grade,
                    near_cross=self.near_cross, top_cross=self.top_cross, far_cross=self.far_cross,
                    twist=self.twist, step_up=self.step_up, step_down=self.step_down, depth=self.depth,
                    kink=self.kink, ramp=self.ramp, ridge=self.ridge, robot_e=self.robot_e, dirs=list(self.dirs),
                    map=map_path(self.id))


TERRAINS = [
    Terrain("S0", "flat road, straight on", 0),
    Terrain("A15", "15 deg approach", 1, approach=15.0),
    Terrain("A30", "30 deg approach", 1, approach=30.0),
    Terrain("A30N", "30 deg approach from the other side", 1, approach=-30.0),
    Terrain("X6", "6 deg gutters: roads fall toward both curbs", 2, near=-6.0, far=6.0),
    Terrain("X6P", "roads rise 6 deg toward both curbs", 2, near=6.0, far=-6.0),
    Terrain("G6", "6 deg street grade along the curb", 2, grade=6.0),
    Terrain("T6", "sidewalk rises 6 deg away from the road", 2, top=6.0),
    Terrain("TN6", "sidewalk falls 6 deg away from the road", 2, top=-6.0),
    Terrain("W6", "sidewalk twisted 6 deg: the curb is taller at one track", 2, twist=6.0),
    Terrain("A30_G6", "30 deg approach on a 6 deg street grade", 3, approach=30.0, grade=6.0),
    Terrain("A30_X6", "30 deg approach across 6 deg gutters, 2% sidewalk", 3, approach=30.0, near=-6.0, top=1.15,
            far=6.0),
    Terrain("A30N_G4X4", "-30 deg approach, 6 deg resultant road (grade + gutter)", 3, approach=-30.0, grade=G4,
            near=-G4, far=G4),
    Terrain("A30_G4X4_W2", "stress: 30 deg, 6 deg resultant roads, sidewalk twisted 2 deg", 3, approach=30.0,
            grade=G4, near=-G4, far=G4, twist=2.0),
    Terrain("S4", "4 in curb, flat", 4, step_up=10.16, step_down=-10.16),
    Terrain("S8", "8 in curb, flat", 4, step_up=20.32, step_down=-20.32),
    Terrain("X6P_G", "road rising 6 deg into the curb, sidewalk 6 deg along it", 4, near=6.0, far=-6.0, twist=6.0,
            robot_e=60.0),
    # The climb only: its ridge lies on the sidewalk 25 cm past the near edge, and a descent starts on the sidewalk
    # past it and drives off the far edge, the ridge behind it -- an S0 descent.
    Terrain("BUMP", "6 in curb, a 2.5 cm ridge 4 cm wide across the sidewalk 25 cm past the edge", 4,
            ridge=(2.5, 25.0, 4.0), dirs=("up",)),
    Terrain("R_A40", "40 deg approach: past what a robot should try", 4, approach=40.0),
    Terrain("R_NARROW", "sidewalk 80 cm deep", 4, depth=80.0, dirs=("up",)),
    Terrain("R_RAMP", "10 deg curb cut, no face", 4, ramp=10.0, dirs=("up",)),
    Terrain("R_KINK", "edge kinked 20 deg where the path crosses it", 4, kink=20.0),
]
BY_ID = {t.id: t for t in TERRAINS}
# The 14 terrains of the base matrix.
BASE_IDS = ("S0", "A15", "A30", "A30N", "X6", "X6P", "G6", "T6", "TN6", "W6", "A30_G6", "A30_X6", "A30N_G4X4",
            "A30_G4X4_W2")


# --- small vector helpers (tuples) --------------------------------------------------
def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    length = math.sqrt(dot(a, a))
    return mul(a, 1.0 / length)


def tand(deg):
    return math.tan(math.radians(deg))


class Plane(object):
    """z = z_ref + gradient . (p - p_ref), over the horizontal plane."""

    def __init__(self, name, p_ref, z_ref, gradient):
        self.name = name
        self.p_ref = p_ref
        self.z_ref = z_ref
        self.gradient = gradient

    def z(self, x, y):
        return self.z_ref + self.gradient[0] * (x - self.p_ref[0]) + self.gradient[1] * (y - self.p_ref[1])

    def normal(self):
        return norm((-self.gradient[0], -self.gradient[1], 1.0))

    def slope_deg(self):
        return math.degrees(math.atan(math.hypot(*self.gradient)))

    def tilt_deg(self, yaw_deg):
        """(pitch, roll) the controller measures standing on this plane with the
        given heading: the elevation of the chassis' forward axis and of its +Y
        axis (UE's right), both lying in the plane."""
        f = (math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)))
        forward = norm((f[0], f[1], dot(self.gradient, f)))
        side = norm(cross(self.normal(), forward))  # UE is left-handed: N x F points right
        if dot(side[:2], (-f[1], f[0])) < 0:
            side = mul(side, -1.0)
        return math.degrees(math.asin(forward[2])), math.degrees(math.asin(side[2]))


class Box(object):
    """An oriented box: top face on `plane`, its x axis the in-plane direction
    over `along`, spanning [n0, n1] along `along` and [e0, e1] across it, both
    measured horizontally from `origin`."""

    def __init__(self, label, plane, origin, along, n_range, e_range, thick):
        self.label = label
        self.plane = plane
        self.origin = origin
        self.along = along
        self.n_range = n_range
        self.e_range = e_range
        self.thick = thick

    def side(self):
        return (-self.along[1], self.along[0])

    def corners2d(self):
        s = self.side()
        return [add(self.origin, add(mul(self.along, n), mul(s, e)))
                for n in self.n_range for e in self.e_range]

    def contains(self, x, y):
        d = sub((x, y), self.origin)
        u, v = dot(d, self.along), dot(d, self.side())
        return self.n_range[0] <= u <= self.n_range[1] and self.e_range[0] <= v <= self.e_range[1]

    def placement(self):
        """(centre, x axis, z axis, size) of the box in the world, cm.

        Built from the side that runs along the edge: the in-plane line over
        `side()`. The top's near and far edges then lie exactly over lines
        parallel to the curb edge, so the sidewalk's lip is the edge line
        itself; the other two sides are only roughly along `along` on a plane
        with both grade and cross-slope, which moves nothing the robot drives
        over.
        """
        N = self.plane.normal()
        s = self.side()
        y_axis = norm((s[0], s[1], dot(self.plane.gradient, s)))
        x_axis = cross(y_axis, N)  # in the plane, over `along`; and N x x_axis = y_axis
        length_x = (self.n_range[1] - self.n_range[0]) / dot(x_axis[:2], self.along)
        length_y = (self.e_range[1] - self.e_range[0]) / dot(y_axis[:2], s)
        m = add(self.origin, add(mul(self.along, self.n_range[0]), mul(s, 0.5 * sum(self.e_range))))
        near_mid = (m[0], m[1], self.plane.z(*m))
        top_mid = add(near_mid, mul(x_axis, 0.5 * length_x))
        centre = sub(top_mid, mul(N, 0.5 * self.thick))
        return centre, x_axis, N, (length_x, length_y, self.thick)


class Layout(object):
    """Everything about one scenario's terrain, placed in the world."""

    def __init__(self, s):
        self.s = s
        a = math.radians(s.approach)
        self.n = (math.cos(a), math.sin(a))
        self.e = (-math.sin(a), math.cos(a))
        # Where the path y = E0.y meets the far edge, (p - E0) . n = depth.
        self.e1 = (E0[0] + s.depth / math.cos(a), E0[1])

        g_near = add(mul(self.n, tand(s.near_cross)), mul(self.e, tand(s.grade)))
        g_top = add(mul(self.n, tand(s.top_cross)), mul(self.e, tand(s.grade + s.twist)))
        g_far = add(mul(self.n, tand(s.far_cross)), mul(self.e, tand(s.grade)))
        near = Plane("near", E0, 0.0, g_near)
        top = Plane("top", E0, s.step_up, g_top)
        far = Plane("far", self.e1, top.z(*self.e1) + s.step_down, g_far)
        self.planes = {"near": near, "top": top, "far": far}

        # How far along the edge the robot reaches: from its start, across both
        # crossings. Each box keeps at least ROBOT_E either side of what the
        # robot covers on it, after trimming.
        start_e, cross_e = self.edge_coord(START), [0.0, self.edge_coord(self.e1)]
        cover = [start_e] + cross_e
        lo, hi = min(cover) - MARGIN_E, max(cover) + MARGIN_E
        side_e = self.trim_both((lo, hi), cross_e)
        # A kinked edge: the sidewalk's -e half yawed `kink` deg about E0, its
        # edge receding from the road; the near road reaching under it.
        under = UNDER
        kink_e = KINK_HALF_E
        if s.kink:
            k = math.radians(s.kink)
            under = UNDER + kink_e * math.sin(k)
        self.boxes = [
            Box("Curb_Road_Near", near, E0, self.n, (-NEAR_BACK, under),
                self.trim(near, (lo, hi), (0.0, under), [start_e, 0.0]), ROAD_THICK),
            Box("Curb_Sidewalk", top, E0, self.n, (0.0, s.depth),
                (max(side_e[0], 0.0), side_e[1]) if s.kink else side_e, SIDEWALK_THICK),
            Box("Curb_Road_Far", far, E0, self.n, (s.depth - UNDER, s.depth + FAR_REACH),
                self.trim(far, (lo, hi), (s.depth - UNDER, s.depth), [cross_e[1]]), ROAD_THICK),
        ]
        if s.kink:
            a_k = math.radians(s.approach + s.kink)
            self.boxes.append(Box("Curb_Sidewalk_Kinked", top, E0, (math.cos(a_k), math.sin(a_k)), (0.0, s.depth),
                                  (-kink_e, 0.0), SIDEWALK_THICK))
        if s.ramp:
            # A curb cut: the road rising `ramp` deg along n to the sidewalk's top,
            # no face. Its plane meets the near road where the ramp begins and
            # the sidewalk at the edge.
            run = s.step_up / tand(s.ramp)
            ramp = Plane("ramp", E0, s.step_up, add(g_near, mul(self.n, tand(s.ramp))))
            self.planes["ramp"] = ramp
            self.boxes.append(Box("Curb_Ramp", ramp, E0, self.n, (-run, 0.0), side_e, SIDEWALK_THICK))
        if s.ridge:
            # A ridge across the sidewalk: its top `height` over the sidewalk's,
            # `past` to `past + width` past the near edge, its bottom buried.
            height, past, width = s.ridge
            bump = Plane("bump", E0, s.step_up + height, g_top)
            self.planes["bump"] = bump
            self.boxes.append(Box("Curb_Ridge", bump, E0, self.n, (past, past + width), side_e, RIDGE_THICK))
        # Lift the whole scenario until every box top clears the floor.
        low = min(b.plane.z(*c) for b in self.boxes for c in b.corners2d())
        self.lift = (FLOOR_TOP_Z + FLOOR_CLEAR) - low
        for p in self.planes.values():
            p.z_ref += self.lift
        self.check()

    def edge_coord(self, p):
        return dot(sub(p, E0), self.e)

    def normal_coord(self, p):
        return dot(sub(p, E0), self.n)

    def step_at(self, which, e):
        """The curb's height where it is `e` along the edge: near (up) or far (down)."""
        top = self.planes["top"]
        if which == "near":
            p = add(E0, mul(self.e, e))
            return top.z(*p) - self.planes["near"].z(*p)
        p = add(add(E0, mul(self.n, self.s.depth)), mul(self.e, e))
        return top.z(*p) - self.planes["far"].z(*p)

    def trim(self, road, e_range, n_span, need):
        """The stretch of e_range, holding every edge coordinate in `need` with
        ROBOT_E to spare, where `road` stays at least MIN_STEP_CM under the
        sidewalk across n_span (measured along n from E0)."""
        top = self.planes["top"]
        good = []
        for i in range(int(e_range[0]), int(e_range[1]) + 1):
            ok = True
            for nn in n_span:
                p = add(add(E0, mul(self.n, nn)), mul(self.e, float(i)))
                if top.z(*p) - road.z(*p) < MIN_STEP_CM:
                    ok = False
            good.append((i, ok))
        return self._run(good, (min(need) - self.s.robot_e, max(need) + self.s.robot_e))

    def trim_both(self, e_range, need):
        near = self.trim(self.planes["near"], e_range, (0.0, UNDER), need)
        far = self.trim(self.planes["far"], e_range, (self.s.depth - UNDER, self.s.depth), need)
        return (max(near[0], far[0]), min(near[1], far[1]))

    def _run(self, good, need):
        # The contiguous run of good samples that holds `need`.
        runs, cur = [], None
        for i, ok in good:
            if ok and cur is None:
                cur = [i, i]
            elif ok:
                cur[1] = i
            elif cur is not None:
                runs.append(cur)
                cur = None
        if cur is not None:
            runs.append(cur)
        for r in runs:
            if r[0] <= need[0] and r[1] >= need[1]:
                return (float(r[0]), float(r[1]))
        raise ValueError("%s: no stretch of curb at least %.1f cm high covers e = %.0f..%.0f"
                         % (self.s.id, MIN_STEP_CM, need[0], need[1]))

    def check(self):
        for b in self.boxes:
            if b.plane.name not in ("near", "far"):
                continue
            # A road's buried part stays under the sidewalk top.
            for c in b.corners2d():
                u = self.normal_coord(c)
                if 0.0 <= u <= self.s.depth:
                    gap = self.planes["top"].z(*c) - b.plane.z(*c)
                    if gap < MIN_BURY_CM:
                        raise ValueError("%s: %s pokes %.1f cm through the sidewalk" % (self.s.id, b.label, -gap))
        e_side = self.boxes[1].e_range
        if e_side[1] - e_side[0] < 150.0:
            raise ValueError("%s: only %.0f cm of curb is tall enough" % (self.s.id, e_side[1] - e_side[0]))

    def surface_z(self, x, y):
        """The topmost surface under (x, y): what a trace from above would hit."""
        z = FLOOR_TOP_Z
        for b in self.boxes:
            if b.contains(x, y):
                z = max(z, b.plane.z(x, y))
        return z

    def start_pose(self):
        """PlayerStart (location, x axis, z axis): over the near road at START,
        heading +X along it."""
        return self._pose_on("near", START)

    def top_start_pose(self, past=None):
        """PlayerStart (location, x axis, z axis) on the sidewalk, heading +X:
        where the descent's detection gate starts a robot without climbing
        first (TOP_START_PAST past the near edge, or `past`)."""
        x = E0[0] + (TOP_START_PAST if past is None else past) + SCAN_HALF_E * abs(tand(self.s.approach))
        return self._pose_on("top", (x, START[1]))

    def top_cross_past(self):
        """Where (cm past the near edge) a descent run from the sidewalk starts:
        TOP_START_PAST, or TOP_DOWNHILL_PAST on a sidewalk falling towards the far
        curb, which the robots roll down before the crossing takes them over."""
        return TOP_DOWNHILL_PAST if self.s.top_cross < -0.5 else TOP_START_PAST

    def _pose_on(self, plane, xy):
        surface = self.planes[plane]
        N = surface.normal()
        x_axis = norm(sub((1.0, 0.0, 0.0), mul(N, N[0])))
        p = (xy[0], xy[1], surface.z(*xy))
        return add(p, mul(N, START_ABOVE_SURFACE)), x_axis, N

    def expected(self):
        """What each crossing should find: the step on the robot's centreline,
        and the range of steps across its tracks (+-TRACK_E along the edge).

        For a detection check (a runner's), also: the
        approach angle (deg, of the edge normal from +X; less the robot's yaw
        it is the angle the controller reports), the plane gradients
        (dz/dx, dz/dy) of the side it starts on (`near_gradient`) and the side
        it crosses to (`far_gradient`), where the path (y = START[1]) crosses
        the edge (`edge_point`) and the edge normal, the two points at
        +-TRACK_E along the edge and the step at each (`track_points`,
        `track_steps`, unrounded), and how deep the far side goes, along the
        normal, to the next edge or the end of its box (`far_depth`)."""
        e1 = self.edge_coord(self.e1)
        up = [self.step_at("near", e) for e in (-TRACK_E, TRACK_E)]
        down = [-self.step_at("far", e1 + d) for d in (-TRACK_E, TRACK_E)]
        far_edge = add(E0, mul(self.n, self.s.depth))
        return {
            "up": {"step": self.s.step_up, "from": "near", "to": "top",
                   "step_range": [round(min(up), 2), round(max(up), 2)],
                   "alpha": self.s.approach,
                   "near_gradient": list(self.planes["near"].gradient),
                   "far_gradient": list(self.planes["top"].gradient),
                   "edge_point": list(E0), "normal": list(self.n),
                   "track_points": [list(add(E0, mul(self.e, d))) for d in (-TRACK_E, TRACK_E)],
                   "track_steps": up,
                   "far_depth": self.s.depth},
            "down": {"step": self.s.step_down, "from": "top", "to": "far",
                     "step_range": [round(min(down), 2), round(max(down), 2)],
                     "alpha": self.s.approach,
                     "near_gradient": list(self.planes["top"].gradient),
                     "far_gradient": list(self.planes["far"].gradient),
                     "edge_point": list(self.e1), "normal": list(self.n),
                     "track_points": [list(add(far_edge, mul(self.e, e1 + d))) for d in (-TRACK_E, TRACK_E)],
                     "track_steps": down,
                     "far_depth": FAR_REACH},
        }

    def describe(self):
        lines = ["%s: %s (lift %+.1f cm)" % (self.s.id, self.s.title, self.lift)]
        for name in ("near", "top", "far"):
            p = self.planes[name]
            pitch, roll = p.tilt_deg(0.0)
            lines.append("  %-4s slope %4.1f deg, heading +X: pitch %+5.1f roll %+5.1f"
                         % (name, p.slope_deg(), pitch, roll))
        for b in self.boxes:
            lines.append("  %-16s n %s e %s" % (b.label, b.n_range, b.e_range))
        ex = self.expected()
        lines.append("  up %+.2f (tracks %s), down %+.2f (tracks %s)"
                     % (ex["up"]["step"], ex["up"]["step_range"], ex["down"]["step"], ex["down"]["step_range"]))
        return "\n".join(lines)


def layout(sid):
    return Layout(BY_ID[sid])


if __name__ == "__main__":
    for t in TERRAINS:
        print(Layout(t).describe())
