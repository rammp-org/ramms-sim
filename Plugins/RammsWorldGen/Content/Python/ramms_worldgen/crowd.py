"""Pedestrian lanes and a crowd for a generated level (RammsCrowd: Mass + ZoneGraph).

After generation, the manifest's routes become a ZoneGraph network:

- outdoors, each block's sidewalk sides and each park's paths are straight runs; they are cut where they
  cross (block corners, the park's cross paths) into a graph, short dangling stubs are dropped, and the
  corners of neighbouring blocks are joined across the street (pedestrians cross at the corners, where
  the crosswalks are);
- indoors, every room's door-to-centre routes (already bent around the furniture) join at the shared
  door centres and room centres.

Nodes where three or more runs meet (and one node per closed loop) become polygon junctions
(AZoneShape, polygon type, a lane-profile point per connecting run); every run between them becomes a
spline AZoneShape whose ends sit on those points, so ZoneGraph links the lanes. Lanes use the project's
"PedestrianLanes" profile (two 150 cm lanes, Crowd | Sidewalk | DensityStd tags); indoors the narrower
"PedestrianLanesNarrow" (2 x 75 cm) when the project defines it. Then the ZoneGraph is rebuilt and an
ARammsCrowdSpawner in ZoneGraphLanes mode is placed with /Game/NPCs/DA_CrowdAgentProfile.

    import ramms_worldgen.crowd as C
    C.build_crowd(H.find_generator())     # editor only; save the level afterwards

Every actor made here carries the tag RammsCrowd and sits in the WorldGen/Crowd outliner folder, so a
rebuild replaces it.
"""
import math

import unreal

from . import _helpers as H

TAG = "RammsCrowd"
FOLDER = "WorldGen/Crowd"
PROFILE_ASSET = "/Game/NPCs/DA_CrowdAgentProfile"
SPAWNER_CLASS = "/Script/RammsCrowd.RammsCrowdSpawner"
# Lane profiles from Config/DefaultPlugins.ini ([/Script/ZoneGraph.ZoneGraphSettings]).
# (name, guid, total width): two opposite lanes each. Generated levels use the narrower ones so a lane
# fits the clear part of a sidewalk or a doorway: agents walk a lane's centre line and Mass avoidance only
# steers around other agents, not around static geometry, so the lanes themselves must be clear.
LANE_PROFILES = {
    "wide": ("PedestrianLanes", "8A3C5B1E4F2D47A9B6E1C0D2F3A4B5C6", 300.0),
    "sidewalk": ("PedestrianLanesSidewalk", "7B1D4C9E2A3F4B5C8D6E0F1A2B3C4D5E", 120.0),
    "narrow": ("PedestrianLanesNarrow", "5D2E8B7A1C4F4E3B9A6D0C1E2F3B4A57", 50.0),
}
AGENT_RADIUS = 30.0     # a little under the profile's 35 cm: agents brush past a door jamb rather than refuse it
CELL = 25.0             # clearance grid for rerouting a lane around furniture and props


# --- geometry -------------------------------------------------------------------------------------

def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _mul(a, k): return (a[0] * k, a[1] * k)
def _len(a): return math.hypot(a[0], a[1])


def _unit(a):
    n = _len(a)
    return (a[0] / n, a[1] / n) if n > 1e-6 else (1.0, 0.0)


def _seg_hit(p, p2, q, q2, ext=0.0):
    """Parameters (t, u) where segment p-p2 meets q-q2 (each may be extended by `ext` cm past its ends),
    or None when they are parallel or miss."""
    r = _sub(p2, p); s = _sub(q2, q)
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-6:
        return None
    qp = _sub(q, p)
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    et, eu = ext / max(_len(r), 1.0), ext / max(_len(s), 1.0)
    if -et <= t <= 1.0 + et and -eu <= u <= 1.0 + eu:
        return t, u
    return None


class _Graph:
    """Undirected graph of 2D nodes; an edge keeps its interior polyline points (from a to b)."""

    def __init__(self, snap):
        self.snap = snap
        self.nodes = []      # [(x, y)]
        self.z = []          # node heights
        self.edges = {}      # id -> [a, b, [interior (x, y, z)...]]
        self._eid = 0
        self.links = set()   # edge ids that cross a doorway between two rooms

    def node(self, p, z=0.0):
        for i, n in enumerate(self.nodes):
            if _len(_sub(n, p)) <= self.snap:
                return i
        self.nodes.append((p[0], p[1]))
        self.z.append(z)
        return len(self.nodes) - 1

    def add(self, a, b, pts=()):
        if a == b:
            return None
        for e in self.edges.values():
            if {e[0], e[1]} == {a, b}:
                return None  # one run per pair (a room's door-to-door routes come in both directions)
        self._eid += 1
        self.edges[self._eid] = [a, b, list(pts)]
        return self._eid

    def incident(self, n):
        return [k for k, e in self.edges.items() if e[0] == n or e[1] == n]

    def degree(self, n):
        return len(self.incident(n))

    def length(self, k):
        a, b, pts = self.edges[k]
        chain = [self.nodes[a]] + [(p[0], p[1]) for p in pts] + [self.nodes[b]]
        return sum(_len(_sub(chain[i + 1], chain[i])) for i in range(len(chain) - 1))

    def prune_stubs(self, max_len):
        """Drop dead-end edges shorter than max_len (the overhang of sidewalk sides past a corner)."""
        changed = True
        while changed:
            changed = False
            for k in list(self.edges):
                a, b, _ = self.edges[k]
                if (self.degree(a) == 1 or self.degree(b) == 1) and self.length(k) < max_len and self.degree(a) + self.degree(b) > 2:
                    del self.edges[k]
                    changed = True


def _outdoor_graph(routes):
    """Straight runs (sidewalk sides, park paths) cut at every crossing into a graph."""
    segs = []
    for r in routes:
        pts = r.get("points") or []
        if len(pts) < 2:
            continue
        a = (pts[0]["x"], pts[0]["y"]); b = (pts[-1]["x"], pts[-1]["y"])
        if _len(_sub(b, a)) < 50.0:
            continue
        segs.append({"a": a, "b": b, "z": pts[0].get("z", 0.0), "cuts": [0.0, 1.0], "name": r.get("name", "")})
    # Crossings and T-junctions: sidewalk sides overrun the corners a little, so allow 120 cm of extension.
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            h = _seg_hit(segs[i]["a"], segs[i]["b"], segs[j]["a"], segs[j]["b"], ext=120.0)
            if h:
                segs[i]["cuts"].append(min(max(h[0], 0.0), 1.0))
                segs[j]["cuts"].append(min(max(h[1], 0.0), 1.0))
    g = _Graph(snap=60.0)
    for s in segs:
        cuts = sorted(set(round(c, 5) for c in s["cuts"]))
        pts = [_add(s["a"], _mul(_sub(s["b"], s["a"]), c)) for c in cuts]
        ids = [g.node(p, s["z"]) for p in pts]
        for k in range(len(ids) - 1):
            if _len(_sub(pts[k + 1], pts[k])) > 40.0:
                g.add(ids[k], ids[k + 1])
    g.prune_stubs(450.0)
    # Join each block's corners to the nearest corner of a neighbouring block straight across the street.
    corner_of = {}
    for s in segs:
        if s["name"].startswith("Block"):
            blk = s["name"].split("_")[0]
            for n in range(len(g.nodes)):
                p = g.nodes[n]
                if g.degree(n) >= 2 and min(_len(_sub(p, s["a"])), _len(_sub(p, s["b"]))) < 400.0:
                    corner_of.setdefault(n, blk)
    corners = [n for n in corner_of if g.degree(n) > 0]
    for n in corners:
        best = {}
        for m in corners:
            if corner_of[m] == corner_of[n]:
                continue
            d = _sub(g.nodes[m], g.nodes[n])
            dist = _len(d)
            if dist < 200.0 or dist > 2600.0:
                continue
            ax = abs(d[0]) < 0.15 * dist     # straight across along Y
            ay = abs(d[1]) < 0.15 * dist     # straight across along X
            if not (ax or ay):
                continue
            key = ("y" if ax else "x") + ("+" if (d[1] if ax else d[0]) > 0 else "-")
            if key not in best or dist < best[key][0]:
                best[key] = (dist, m)
        for _dist, m in best.values():
            g.add(n, m)
    return g


def _indoor_graph(routes, features=()):
    """Room routes (door to door, or door to the room's centre, bent around the furniture) joined into one
    network: route ends in different rooms that face each other through a doorway are linked, and a shop's
    aisles become a ladder (each aisle's centre line, its ends joined to the next aisle's) tied to the routes."""
    g = _Graph(snap=45.0)
    room_of = {}
    door_end = set()
    per_room = {}
    for r in routes:
        per_room[r.get("name", "").split("_")[0]] = per_room.get(r.get("name", "").split("_")[0], 0) + 1
    for r in routes:
        pts = r.get("points") or []
        if len(pts) < 2:
            continue
        room = r.get("name", "").split("_")[0]
        a = g.node((pts[0]["x"], pts[0]["y"]), pts[0].get("z", 0.0))
        b = g.node((pts[-1]["x"], pts[-1]["y"]), pts[-1].get("z", 0.0))
        room_of.setdefault(a, set()).add(room)
        room_of.setdefault(b, set()).add(room)
        # A room with several doors has routes from door to door; a room with one door has a single route
        # from its door to its centre (the centre is not a doorway).
        door_end.add(a)
        if per_room[room] > 1:
            door_end.add(b)
        inner = [(p["x"], p["y"], p.get("z", 0.0)) for p in pts[1:-1]]
        g.add(a, b, inner)
    # Through the doorways: each door end links to the nearest door end of another room when that one
    # links back (mutual nearest) and they are no farther apart than a wall plus both approaches.
    ends = sorted(door_end)
    nearest = {}
    for a in ends:
        best = None
        for b in ends:
            if b == a or room_of[a] & room_of[b]:
                continue
            d = _len(_sub(g.nodes[a], g.nodes[b]))
            if d < 110.0 and (best is None or d < best[0]):
                best = (d, b)
        if best:
            nearest[a] = best[1]
    for a, b in nearest.items():
        if nearest.get(b) == a and a < b:
            k = g.add(a, b)
            if k:
                g.links.add(k)
    # Shop aisles: a ladder.
    aisles = []
    for f in features:
        if f.get("kind") != "Aisle":
            continue
        c = (f["location"]["x"], f["location"]["y"]); sz = f["size"]
        if sz["x"] >= sz["y"]:
            a, b = (c[0] - sz["x"] * 0.5 + 60.0, c[1]), (c[0] + sz["x"] * 0.5 - 60.0, c[1]); across = c[1]
        else:
            a, b = (c[0], c[1] - sz["y"] * 0.5 + 60.0), (c[0], c[1] + sz["y"] * 0.5 - 60.0); across = c[0]
        aisles.append((across, g.node(a, f["location"].get("z", 0.0)), g.node(b, f["location"].get("z", 0.0))))
    aisles.sort()
    for k, (_c, a, b) in enumerate(aisles):
        g.add(a, b)
        if k + 1 < len(aisles):
            g.add(a, aisles[k + 1][1])
            g.add(b, aisles[k + 1][2])
    if aisles:
        # Tie the ladder to the nearest route end (the shop's door routes), at both of its ends.
        route_nodes = [n for n in door_end]
        for corner in (aisles[0][1], aisles[0][2], aisles[-1][1], aisles[-1][2]):
            if route_nodes:
                m = min(route_nodes, key=lambda n: _len(_sub(g.nodes[n], g.nodes[corner])))
                if _len(_sub(g.nodes[m], g.nodes[corner])) < 1500.0:
                    g.add(corner, m)
    return g


# --- keeping lanes clear of walls, furniture and props ----------------------------------------------

class _Clearance:
    """Is a pedestrian of a given radius free to stand at (x, y) on the floor at height z? A capsule from
    30 cm above the floor (thresholds, curbs and floor slabs do not count) to head height, tested against
    everything that blocks (walls, furniture, props, vehicles). Results are cached on a 25 cm grid."""

    def __init__(self, world):
        self.world = world
        self.cache = {}
        self.types = [unreal.ObjectTypeQuery.OBJECT_TYPE_QUERY1, unreal.ObjectTypeQuery.OBJECT_TYPE_QUERY2]
        self.calls = 0

    def free(self, x, y, z, r):
        # Cached at 5 cm, not the 25 cm search grid: a doorway is only ~8 cm wider than a person, and
        # snapping a test point to the grid would close it.
        key = (int(round(x / 5.0)), int(round(y / 5.0)), int(round(z / 20.0)), int(r))
        hit = self.cache.get(key)
        if hit is None:
            self.calls += 1
            cx, cy = key[0] * 5.0, key[1] * 5.0
            half = 70.0
            # Returns the overlapping components, or None when there are none (the bool return is folded in).
            res = unreal.SystemLibrary.capsule_overlap_components(
                self.world, unreal.Vector(cx, cy, z + 30.0 + half), r, max(half, r), self.types,
                unreal.PrimitiveComponent.static_class(), [])
            if isinstance(res, tuple):
                res = res[-1] if res and res[0] else None
            hit = bool(res)
            self.cache[key] = hit
        return not hit

    def segment_free(self, a, b, za, zb, r):
        d = _len(_sub(b, a))
        n = max(1, int(d / 15.0))
        for i in range(n + 1):
            t = i / n
            if not self.free(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, za + (zb - za) * t, r):
                return False
        return True

    def nearest_free(self, p, z, r, reach=120.0):
        if self.free(p[0], p[1], z, r):
            return p
        best = None
        steps = int(reach / CELL)
        for i in range(-steps, steps + 1):
            for j in range(-steps, steps + 1):
                q = (p[0] + i * CELL, p[1] + j * CELL)
                d = _len(_sub(q, p))
                if d <= reach and (best is None or d < best[0]) and self.free(q[0], q[1], z, r):
                    best = (d, q)
        return best[1] if best else None


def _astar(clr, a, b, za, zb, r, margin):
    """Shortest 8-connected path on the 25 cm grid from a to b keeping radius r free, inside the pair's
    bounding box grown by margin. Returns a list of points (a ... b) or None."""
    import heapq
    # The grid is laid so the start sits exactly on a cell centre: from a doorway, a path straight out
    # along the door's axis then keeps its full clearance (a misaligned grid would close an 80 cm door).
    x0 = a[0] - math.ceil((a[0] - (min(a[0], b[0]) - margin)) / CELL) * CELL
    y0 = a[1] - math.ceil((a[1] - (min(a[1], b[1]) - margin)) / CELL) * CELL
    x1, y1 = max(a[0], b[0]) + margin, max(a[1], b[1]) + margin
    nx, ny = int((x1 - x0) / CELL) + 1, int((y1 - y0) / CELL) + 1
    if nx * ny > 60000:
        return None
    L = _len(_sub(b, a)) or 1.0

    def cell(p): return (int(round((p[0] - x0) / CELL)), int(round((p[1] - y0) / CELL)))
    def pos(c): return (x0 + c[0] * CELL, y0 + c[1] * CELL)
    def zat(p):
        t = max(0.0, min(1.0, _len(_sub(p, a)) / L))
        return za + (zb - za) * t

    s, g = cell(a), cell(b)
    openq = [(0.0, s)]
    cost = {s: 0.0}
    came = {}
    nbrs = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    while openq:
        _f, c = heapq.heappop(openq)
        pc = pos(c)
        # Done at the goal cell, or anywhere close to the goal with a clear straight run onto it (the goal
        # is usually off-grid, often in a doorway).
        if c == g or (_len(_sub(pc, b)) < 75.0 and clr.segment_free(pc, b, zat(pc), zb, r)):
            path = [b] if c == g else [b, pc]
            while c in came:
                c = came[c]
                path.append(pos(c))
            if len(path) > 1:
                path[-1] = a
            else:
                path.append(a)
            return list(reversed(path))
        for dx, dy, w in nbrs:
            n = (c[0] + dx, c[1] + dy)
            if not (0 <= n[0] < nx and 0 <= n[1] < ny):
                continue
            p = pos(n)
            if n != g and not clr.free(p[0], p[1], zat(p), r):
                continue
            nc = cost[c] + w
            if nc < cost.get(n, 1e18):
                cost[n] = nc
                came[n] = c
                h = math.hypot(g[0] - n[0], g[1] - n[1])
                heapq.heappush(openq, (nc + h, n))
    return None


def _pull(clr, pts, za, zb, r):
    """String-pull a grid path: keep a point only where the straight line to a later one is blocked."""
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not clr.segment_free(pts[i], pts[j], za, zb, r):
            j -= 1
        out.append(pts[j])
        i = j
    return out


def _doorway(clr, a, b, z):
    """A doorway between route ends a and b (either side of a wall): its centre in the wall, found by
    scanning across the crossing for the free span, and the crossing direction. None when no gap is found."""
    d = _sub(b, a)
    ax = (1.0 if d[0] > 0 else -1.0, 0.0) if abs(d[0]) >= abs(d[1]) else (0.0, 1.0 if d[1] > 0 else -1.0)
    lat = (-ax[1], ax[0])
    mid = _mul(_add(a, b), 0.5)
    free = [o for o in range(-80, 81, 5) if clr.free(mid[0] + lat[0] * o, mid[1] + lat[1] * o, z, 12.0)]
    if not free:
        return None
    # The longest run of consecutive free offsets is the opening.
    runs, cur = [], [free[0]]
    for o in free[1:]:
        if o - cur[-1] == 5:
            cur.append(o)
        else:
            runs.append(cur); cur = [o]
    runs.append(cur)
    best = max(runs, key=len)
    c = (best[0] + best[-1]) * 0.5
    return _add(mid, _mul(lat, c)), ax


def _clear_lanes(g, world, lane_half, indoor):
    """Make every run of the graph clear for a pedestrian walking either of its lanes.

    Doorway crossings are straightened through the middle of the opening. Every other run end is nudged
    off furniture and out of door jambs, back toward its own room. A run whose line hits something is
    rerouted around it on a grid (first with room for both lanes, then with room for one person); a run
    with no way through is dropped."""
    clr = _Clearance(world)
    r_lane = lane_half + AGENT_RADIUS          # both lanes clear
    r_min = AGENT_RADIUS + 6.0                 # one person squeezing through a pinch point
    stats = {"rerouted": 0, "dropped": 0, "doorways": 0}
    z = {n: _ground_z(world, g.nodes[n][0], g.nodes[n][1], g.z[n]) for n in range(len(g.nodes))}
    links = getattr(g, "links", set())

    # 1. Doorways: the crossing becomes a straight run through the opening's centre, 45 cm either side
    #    of the wall line, so the lane never clips a jamb.
    for k in list(links):
        if k not in g.edges:
            continue
        a, b, _pts = g.edges[k]
        dw = _doorway(clr, g.nodes[a], g.nodes[b], z[a])
        if dw is None:
            continue
        c, ax = dw
        p0, p1 = _sub(c, _mul(ax, 45.0)), _add(c, _mul(ax, 45.0))
        g.edges[k][2] = [(p0[0], p0[1], z[a]), (c[0], c[1], z[a]), (p1[0], p1[1], z[b])]
        stats["doorways"] += 1

    # 2. Run ends: off furniture and jambs, moving back along the node's own (non-doorway) runs.
    for n in range(len(g.nodes)):
        inc = g.incident(n)
        if not inc or clr.free(g.nodes[n][0], g.nodes[n][1], z[n], r_min):
            continue
        dirs = []
        for k in inc:
            if k in links:
                continue
            a, b, pts = g.edges[k]
            chain = [g.nodes[a]] + [(p[0], p[1]) for p in pts] + [g.nodes[b]]
            nxt = chain[1] if a == n else chain[-2]
            dirs.append(_unit(_sub(nxt, g.nodes[n])))
        q = None
        if dirs:
            dv = _unit((sum(d[0] for d in dirs), sum(d[1] for d in dirs)))
            for step in range(1, 31):
                cand = _add(g.nodes[n], _mul(dv, step * 5.0))
                if clr.free(cand[0], cand[1], z[n], r_min):
                    q = cand
                    break
        if q is None:
            q = clr.nearest_free(g.nodes[n], z[n], r_min, 150.0)
        if q is None:
            for k in inc:
                del g.edges[k]
                stats["dropped"] += 1
            continue
        g.nodes[n] = q

    # 3. Runs.
    margin = 300.0 if indoor else 450.0
    for k in list(g.edges):
        a, b, pts = g.edges[k]
        chain = [g.nodes[a]] + [(p[0], p[1]) for p in pts] + [g.nodes[b]]
        za, zb = z[a], z[b]
        segs = range(len(chain) - 1)
        if all(clr.segment_free(chain[i], chain[i + 1], za, zb, r_lane) for i in segs):
            continue
        if k in links:
            # A doorway: passable if a person fits along the straightened line; otherwise rerouted.
            if all(clr.segment_free(chain[i], chain[i + 1], za, zb, 15.0) for i in segs):
                continue
        ok_min = all(clr.segment_free(chain[i], chain[i + 1], za, zb, r_min) for i in segs)
        path = _astar(clr, chain[0], chain[-1], za, zb, r_lane, margin)
        r_used = r_lane
        if path is None and not ok_min:
            path = _astar(clr, chain[0], chain[-1], za, zb, r_min, margin)
            r_used = r_min
        if path is None and not ok_min:
            path = _astar(clr, chain[0], chain[-1], za, zb, 24.0, margin)
            r_used = 24.0
        if path is None:
            if ok_min:
                continue            # tight but passable as laid out: keep it
            del g.edges[k]
            stats["dropped"] += 1
            stats.setdefault("dropped_runs", []).append([round(v) for v in chain[0] + chain[-1]])
            continue
        path = _pull(clr, path, za, zb, r_used)
        g.edges[k][2] = [(p[0], p[1], za + (zb - za) * (i / max(len(path) - 1, 1))) for i, p in enumerate(path[1:-1], 1)]
        stats["rerouted"] += 1
    stats["queries"] = clr.calls
    return stats


# --- level actors ---------------------------------------------------------------------------------

def _clear():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    old = [a for a in eas.get_all_level_actors() if a.actor_has_tag(TAG)]
    if old:
        eas.destroy_actors(old)
    return len(old)


def _profile_ref(kind):
    name, guid_s, width = LANE_PROFILES[kind]
    ref = unreal.ZoneLaneProfileRef()
    ref.set_editor_property("name", unreal.Name(name))
    guid, ok = unreal.GuidLibrary.parse_string_to_guid(guid_s)
    if ok:
        ref.set_editor_property("id", guid)
    return ref, width


def _ground_z(world, x, y, z):
    """Walking surface height at (x, y): the first hit going down from just above the route, ignoring
    anything standing more than 40 cm above it (props, furniture)."""
    s = unreal.Vector(x, y, z + 60.0)
    e = unreal.Vector(x, y, z - 120.0)
    hit = unreal.SystemLibrary.line_trace_single(world, s, e, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [],
                                                 unreal.DrawDebugTrace.NONE, True)
    if hit:
        t = hit.to_tuple()
        if t and t[0]:
            loc = next((v for v in t if isinstance(v, unreal.Vector)), None)
            if loc is not None and loc.z <= z + 40.0:
                return loc.z
    return z


def _shape(points, shape_type, profile_ref, label):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = eas.spawn_actor_from_class(unreal.ZoneShape, unreal.Vector(0, 0, 0))
    actor.set_actor_label(label)
    actor.tags = [unreal.Name(TAG)]
    actor.set_folder_path(unreal.Name(FOLDER))
    comp = actor.get_component_by_class(unreal.ZoneShapeComponent)
    comp.set_shape_type(shape_type)
    comp.set_editor_property("lane_profile", profile_ref)
    comp.set_editor_property("points", points)
    unreal.RammsCrowdZoneGraphLibrary.update_zone_shape(comp)
    return actor


def _pt(x, y, z, ptype, yaw=0.0):
    p = unreal.ZoneShapePoint()
    p.position = unreal.Vector(x, y, z)
    p.type = ptype
    p.rotation = unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw)
    return p


def _emit(g, profile_kind, world, label_prefix):
    """Polygon junctions at branch nodes, splines along the runs between them. Returns (shapes, lane cm)."""
    ref, width = _profile_ref(profile_kind)
    clr = _Clearance(world)
    T = unreal.FZoneShapePointType
    # Junctions: nodes of degree >= 3, plus one node on any loop without one.
    junction = {n for n in range(len(g.nodes)) if g.degree(n) >= 3}
    # Walk chains between junctions / dead ends.
    used = set()
    chains = []

    def neighbours(n, k):
        a, b, pts = g.edges[k]
        if a == n:
            return b, list(pts)
        return a, list(reversed(pts))

    def walk(start, k):
        nodes = [start]
        inner = []
        cur = start
        while True:
            used.add(k)
            nxt, pts = neighbours(cur, k)
            inner += [(p[0], p[1]) + ((p[2],) if len(p) > 2 else (g.z[cur],)) for p in pts]
            if nxt in junction or g.degree(nxt) != 2:
                nodes.append(nxt)
                return nodes, inner
            inner.append((g.nodes[nxt][0], g.nodes[nxt][1], g.z[nxt]))
            nodes.append(nxt)
            ks = [x for x in g.incident(nxt) if x not in used]
            if not ks:
                return nodes, inner
            cur, k = nxt, ks[0]

    for n in sorted(junction) + [n for n in range(len(g.nodes)) if g.degree(n) == 1]:
        for k in g.incident(n):
            if k not in used:
                chains.append(walk(n, k))
    # What is left are closed loops with no junction: make their first node one and walk them.
    for k in list(g.edges):
        if k in used:
            continue
        n = g.edges[k][0]
        junction.add(n)
        for k2 in g.incident(n):
            if k2 not in used:
                chains.append(walk(n, k2))

    # Junction radius: half the lane profile plus a margin, smaller when runs are short.
    radius = {}
    for n in junction:
        lens = [g.length(k) for k in g.incident(n)]
        radius[n] = max(min(width * 0.5 + 25.0, (min(lens) if lens else 1e9) * 0.35), 30.0)
        # The junction's lanes curve inside this circle: keep it clear of walls, jambs and props.
        zc = _ground_z(world, g.nodes[n][0], g.nodes[n][1], g.z[n])
        while radius[n] > 30.0 and not clr.free(g.nodes[n][0], g.nodes[n][1], zc, max(radius[n], width * 0.5) + AGENT_RADIUS * 0.5):
            radius[n] -= 5.0

    shapes = 0
    lane_cm = 0.0
    entries = {n: [] for n in junction}
    for idx, (nodes, inner) in enumerate(chains):
        a, b = nodes[0], nodes[-1]
        pts = [(g.nodes[a][0], g.nodes[a][1], g.z[a])] + inner + [(g.nodes[b][0], g.nodes[b][1], g.z[b])]
        if len(pts) < 2:
            continue
        # Pull each end back onto its junction's boundary, along the run's first / last direction.
        if a in junction:
            d = _unit(_sub(pts[1][:2], pts[0][:2]))
            p0 = _add(pts[0][:2], _mul(d, radius[a]))
            pts[0] = (p0[0], p0[1], pts[0][2])
            entries[a].append((math.atan2(d[1], d[0]), p0, pts[0][2]))
        if b in junction:
            d = _unit(_sub(pts[-2][:2], pts[-1][:2]))
            p1 = _add(pts[-1][:2], _mul(d, radius[b]))
            pts[-1] = (p1[0], p1[1], pts[-1][2])
            entries[b].append((math.atan2(d[1], d[0]), p1, pts[-1][2]))
        # Drop interior points that the pulled-back ends now pass (very short runs).
        clean = [pts[0]]
        for p in pts[1:-1]:
            if _len(_sub(p[:2], clean[-1][:2])) > 30.0 and _len(_sub(p[:2], pts[-1][:2])) > 30.0:
                clean.append(p)
        clean.append(pts[-1])
        if _len(_sub(clean[-1][:2], clean[0][:2])) < 30.0:
            continue
        # Sharp points with a small turn radius: auto-bezier corners bulge out over the street.
        sp = []
        for i, p in enumerate(clean):
            z = _ground_z(world, p[0], p[1], p[2]) + 1.0
            q = _pt(p[0], p[1], z, T.SHARP)
            q.inner_turn_radius = 40.0
            sp.append(q)
        _shape(sp, unreal.FZoneShapeType.SPLINE, ref, "%s_Lane%02d" % (label_prefix, idx))
        shapes += 1
        lane_cm += sum(_len(_sub(clean[i + 1][:2], clean[i][:2])) for i in range(len(clean) - 1))

    for n, ents in entries.items():
        if len(ents) < 2:
            continue
        c = g.nodes[n]
        cz = _ground_z(world, c[0], c[1], g.z[n]) + 1.0
        ents.sort(key=lambda e: e[0])
        poly = []
        for i, (ang, p, _z) in enumerate(ents):
            # Lane-profile point on the boundary, facing into the junction.
            poly.append(_pt(p[0], p[1], cz, T.LANE_PROFILE, math.degrees(ang) + 180.0))
            # A sharp corner between this run and the next one, out along the bisector.
            nxt = ents[(i + 1) % len(ents)][0]
            gap = (nxt - ang) % (2.0 * math.pi)
            if gap < 1e-3:
                gap = 2.0 * math.pi
            mid = ang + gap * 0.5
            # On the junction's (cleared) circle, not beyond it: the outline must not poke through a wall.
            r = radius[n] * (1.0 if gap < math.pi else 0.85)
            poly.append(_pt(c[0] + math.cos(mid) * r, c[1] + math.sin(mid) * r, cz, T.SHARP))
        _shape(poly, unreal.FZoneShapeType.POLYGON, ref, "%s_Junction%02d" % (label_prefix, n))
        shapes += 1
    return shapes, lane_cm


def check_lanes(world=None):
    """Audit the level's crowd shapes against the geometry: (spline segments whose centre line comes within
    15 cm of something, polygon outline edges that cross something). Both should be 0."""
    world = world or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    clr = _Clearance(world)
    bad_lane = bad_poly = 0
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if not isinstance(a, unreal.ZoneShape) or not a.actor_has_tag(TAG):
            continue
        comp = a.get_component_by_class(unreal.ZoneShapeComponent)
        P = [(p.position.x, p.position.y, p.position.z - 1.0) for p in comp.get_editor_property("points")]
        poly = "POLYGON" in str(comp.get_shape_type())
        segs = list(zip(P, P[1:] + ([P[0]] if poly else [])))
        for p0, p1 in segs:
            if not clr.segment_free(p0[:2], p1[:2], p0[2], p1[2], 4.0 if poly else 15.0):
                if poly:
                    bad_poly += 1
                else:
                    bad_lane += 1
    return bad_lane, bad_poly


def build_crowd(gen, count=None):
    """Lay ZoneGraph lanes along the generated level's routes, rebuild the ZoneGraph and place a crowd
    spawner. Returns a summary dict. Editor only; the caller saves the level."""
    m = H.manifest_to_dict(gen)
    routes = m.get("routes", [])
    removed = _clear()
    if not routes:
        return {"shapes": 0, "removed": removed, "note": "no routes"}
    indoor = str(m.get("sceneKind", "")).lower().startswith("indoor") or all(r.get("name", "").startswith("Room") for r in routes)
    g = _indoor_graph(routes, m.get("features", [])) if indoor else _outdoor_graph(routes)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    kind = "narrow" if indoor else "sidewalk"
    lane_half = LANE_PROFILES[kind][2] * 0.25        # each lane's centre sits a quarter of the profile off the run
    cleared = _clear_lanes(g, world, lane_half, indoor)
    par = list(range(len(g.nodes)))

    def _root(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a, b, _p in g.edges.values():
        par[_root(a)] = _root(b)
    cleared["components"] = len({_root(n) for n in range(len(g.nodes)) if g.degree(n) > 0})
    shapes, lane_cm = _emit(g, kind, world, "Crowd")
    unreal.RammsCrowdZoneGraphLibrary.rebuild_zone_graph()
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if isinstance(a, unreal.ZoneGraphData):
            a.set_folder_path(unreal.Name(FOLDER))

    # One pedestrian per ~9 m of lane outdoors, per ~8 m indoors; a packed corridor is not the point.
    if count is None:
        count = int(max(3, min(25 if indoor else 80, lane_cm / (800.0 if indoor else 900.0))))
    spawner = None
    cls = unreal.load_class(None, SPAWNER_CLASS)
    profile = unreal.load_asset(PROFILE_ASSET) if H.EAL.does_asset_exist(PROFILE_ASSET) else None
    if cls and profile and shapes:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        c = g.nodes[0] if g.nodes else (0.0, 0.0)
        spawner = eas.spawn_actor_from_class(cls, unreal.Vector(c[0], c[1], 100.0))
        spawner.set_actor_label("CrowdSpawner")
        spawner.tags = [unreal.Name(TAG)]
        spawner.set_folder_path(unreal.Name(FOLDER))
        spawner.set_editor_property("crowd_profile", profile)
        spawner.set_editor_property("spawn_mode", unreal.RammsCrowdSpawnMode.ZONE_GRAPH_LANES)
        spawner.set_editor_property("desired_count", count)
        zs = spawner.get_editor_property("zone_graph_spawn_settings")
        zs.set_editor_property("min_gap_cm", 250.0 if indoor else 400.0)
        zs.set_editor_property("max_gap_cm", 600.0 if indoor else 1200.0)
        spawner.set_editor_property("zone_graph_spawn_settings", zs)
        spawner.apply_crowd_configuration()
    elif not profile:
        H.warn("crowd: %s not found; lanes laid, no spawner" % PROFILE_ASSET)
    bad_lane, bad_poly = check_lanes(world)
    res = {"cleared": cleared, "blocked_lane_segments": bad_lane, "blocked_junction_edges": bad_poly, "shapes": shapes, "nodes": len(g.nodes), "edges": len(g.edges), "lane_m": round(lane_cm / 100.0),
           "count": count if spawner else 0, "removed": removed, "indoor": indoor}
    H.log("crowd: %s" % res)
    return res
