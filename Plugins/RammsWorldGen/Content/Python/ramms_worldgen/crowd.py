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
LANE_PROFILES = {
    "wide": ("PedestrianLanes", "8A3C5B1E4F2D47A9B6E1C0D2F3A4B5C6", 300.0),
    "narrow": ("PedestrianLanesNarrow", "5D2E8B7A1C4F4E3B9A6D0C1E2F3B4A57", 150.0),
}


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
            g.add(a, b)
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
        radius[n] = max(min(width * 0.5 + 25.0, (min(lens) if lens else 1e9) * 0.35), 40.0)

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
        sp = []
        for i, p in enumerate(clean):
            z = _ground_z(world, p[0], p[1], p[2]) + 1.0
            sp.append(_pt(p[0], p[1], z, T.AUTO_BEZIER))
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
            r = radius[n] * (1.25 if gap < math.pi else 1.0) + width * 0.25
            poly.append(_pt(c[0] + math.cos(mid) * r, c[1] + math.sin(mid) * r, cz, T.SHARP))
        _shape(poly, unreal.FZoneShapeType.POLYGON, ref, "%s_Junction%02d" % (label_prefix, n))
        shapes += 1
    return shapes, lane_cm


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
    shapes, lane_cm = _emit(g, "narrow" if indoor else "wide", world, "Crowd")
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
    res = {"shapes": shapes, "nodes": len(g.nodes), "edges": len(g.edges), "lane_m": round(lane_cm / 100.0),
           "count": count if spawner else 0, "removed": removed, "indoor": indoor}
    H.log("crowd: %s" % res)
    return res
