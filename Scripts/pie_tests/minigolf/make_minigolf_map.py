"""Author a mini-golf level from scratch: a Kinova Gen3 putting a free ball on a lane course, under MuJoCo.

The level holds one URLab manager, a game mode with no default pawn, the Gen3
Blueprint with its controllers disabled, a green with a cup cut in it, the hole's
walls as static boxes, the ball as its own small articulation, and (when given) a
putter head attached to the arm's bracelet. See README.md for what is and is not
simulated and why each piece is built the way it is.

Parameterised the way make_newton_map.py is: set these on `unreal` before
running; they are consumed and cleared on read, so they apply to exactly one run.

    unreal._ramms_minigolf_map       target level (default the public one below)
    unreal._ramms_minigolf_hole      1, 2 or 3 (default 1)
    unreal._ramms_minigolf_putter    None (no putter), or a dict with rel_pos (cm),
                                     rel_quat (x, y, z, w) and size (cm): the head's
                                     pose in the bracelet's frame. data/putter_head.json
                                     is one; run_minigolf.py passes it.
    unreal._ramms_minigolf_mount     (x, y, z) cm where the Gen3's base sits
    unreal._ramms_minigolf_base_yaw  yaw in degrees of the Gen3 Blueprint at the mount
    unreal._ramms_minigolf_friction  [slide, torsion, roll] for the green and the ball,
                                     in MuJoCo units
    unreal._ramms_minigolf_gen3_bp   the Gen3 Blueprint (default the fixed-base one;
                                     /Game/Robots/URL/gen3_2f85 has a free base welded to
                                     a mocap body, which the chair-assist stroke slides)
    unreal._ramms_minigolf_contact   {"solref": [timeconst, dampratio], "solimp": [...]}
                                     applied to the ball and the putter head geoms
    unreal._ramms_minigolf_timestep  the manager's scene_option timestep in seconds
    unreal._ramms_minigolf_wall_solref   [timeconst, dampratio] for walls and cup liner
    unreal._ramms_minigolf_wall_friction [slide, torsion, roll] for walls and cup liner

Run inside the editor (run_minigolf.py map does this and passes the parameters):
    python3 Scripts/editor_remote_exec.py --file Scripts/pie_tests/minigolf/make_minigolf_map.py

Units and frames. The level is authored in Unreal centimetres, in a course frame
with x down the lane, y to the side and z up, the green's top face at z 0. Unreal's
frame is left-handed and MuJoCo's is right-handed, and URLab maps one to the other
by mirroring Y (URLabAxisConv.h). So wherever a number crosses into a MuJoCo
element it is converted: positions (x, -y, z) / 100 (cm to metres), quaternions
Unreal (x, y, z, w) -> MuJoCo (w, -x, y, -z).
"""

import json
import math
import time

import unreal


def take_param(name, default):
    """Read an override off the `unreal` module and clear it (see make_newton_map.py
    for why it must be cleared: the module outlives the run, and a stale override
    would silently rebuild the wrong level on the next plain run)."""
    attr = "_ramms_minigolf_" + name
    if not hasattr(unreal, attr):
        return default
    value = getattr(unreal, attr)
    delattr(unreal, attr)
    return value


MAP_DEFAULT = "/Game/Maps/URL/Map_MiniGolf_URL"
MAP = take_param("map", MAP_DEFAULT)
HOLE = int(take_param("hole", 1))
PUTTER = take_param("putter", None)
MOUNT = tuple(take_param("mount", (-35.0, -8.0, 35.0)))
BASE_YAW = float(take_param("base_yaw", -90.0))
FRICTION = take_param("friction", [0.6, 0.005, 0.00135])   # rolling 0.00135 is about 0.5 m/s^2 on a kicked ball
GEN3_BP = take_param("gen3_bp", "/Game/Robots/URL/gen3_2f85_fixed")
CONTACT = take_param("contact", None)
TIMESTEP = take_param("timestep", None)
# Walls bounce and are slippery. MuJoCo's default solref (0.02, 1) is critically damped
# and swallowed a 2 m/s bank shot; 0.004 is twice a 2 ms step, the stiffest MuJoCo
# recommends. Friction matters more: a quick-convert's unset friction is (1, 1, 1), and
# torsional and rolling friction of 1.0 at a wall swallow the ball's spin. These are a
# painted wood bumper's.
WALL_SOLREF = take_param("wall_solref", [0.004, 0.3])
WALL_FRICTION = take_param("wall_friction", [0.3, 0.001, 0.0001])

WALL_H, WALL_T, RAIL_SINK = 8.4, 6.0, 2.0   # rails stand 8.4 cm above the green; walls start 2 cm under it.
                                            # 6 cm thick, set OUTWARD so the inner face is on the measured line:
                                            # a 1 cm wall let a 2.5 m/s ball drive past its mid-plane
CUP_R, CUP_DEPTH, FLOOR_T = 5.4, 10.5, 20.0
BALL_R = 2.135                              # a 42.7 mm ball, 45.9 g
BALL_MASS = 0.0459

# The course. Tiles are 1 m lane pieces: (kind, x, y, yaw degrees, label), placed at
# (x, y) cm. A hole tile's yaw turns its opening toward the incoming ball (270 for a
# ball travelling +X, 180 for -Y). The first tile is centred at X0, Y and the ball
# sits on the lane's centre line.
X0, Y = -40.0, -95.0
HOLE_TILE = "HoleRoundOpen"
HOLES = {
    1: dict(tiles=[("Straight", X0, Y, 90, "Lane_1"), ("Straight", X0 + 100, Y, 90, "Lane_2"),
                   (HOLE_TILE, X0 + 200, Y, 270, "Lane_Hole")],
            cup=(X0 + 200, Y)),
    2: dict(tiles=[("Straight", X0, Y, 90, "Lane_1"), ("Straight", X0 + 100, Y, 90, "Lane_2"),
                   ("SkewCorner", X0 + 200, Y, 0, "Lane_Corner"),            # the 45 degree bank
                   ("Straight", X0 + 200, Y - 100, 0, "Lane_3"), (HOLE_TILE, X0 + 200, Y - 200, 180, "Lane_Hole")],
            cup=(X0 + 200, Y - 200)),
    3: dict(tiles=[("Straight", X0, Y, 90, "Lane_1"), ("Straight", X0 + 100, Y, 90, "Lane_2"),
                   ("Windmill", X0 + 200, Y, 90, "Windmill"), ("Straight", X0 + 300, Y, 90, "Lane_3"),
                   (HOLE_TILE, X0 + 400, Y, 270, "Lane_Hole")],
            cup=(X0 + 400, Y)),
}

# The wall lines of each tile kind, in the tile's own local frame (cm, the inner faces
# at green level), measured from the Kenney Minigolf Kit (CC0, https://kenney.nl/assets/minigolf-kit)
# tiles. Each entry is a list of polylines; walls() turns them into placed segments.
#   Straight       rails at local x +-40 along Y (a lane along X wants yaw 90)
#   HoleRound      legs at x +-40 from y 0 to -50 (the opening, local -Y) and a 40 cm round wall
#                  toward +Y, as a fine circle: the mesh's 12 facets put an odd vertex count at the
#                  apex, which glanced a centre-line ball 15 cm wide of the cup
#   SkewCorner     open at local x -50 and y -50, a 45 degree bank across the +X +Y corner, and
#                  a post at the -X -Y corner
#   Windmill       lane rails at x +-40, the body's faces at y +-40 and a 40 cm tunnel (x +-20)
#                  through it. The blades never come lower than about 35 cm, so they are not walls.
_ARC = [(40.0 * math.cos(math.pi * i / 25), 40.0 * math.sin(math.pi * i / 25)) for i in range(26)]
POLYLINES = {
    "Straight": [[(-40, -50), (-40, 50)], [(40, -50), (40, 50)]],
    "HoleRound": [[(-40, -50)] + _ARC[::-1] + [(40, -50)]],       # the arc runs from (-40, 0) over +Y to (40, 0)
    "SkewCorner": [[(-50, 40), (-48, 39.9), (-46.1, 39.5), (-44.3, 38.9), (-42.5, 38), (-40.9, 36.9), (-39.4, 35.6),
                    (35.6, -39.4), (36.9, -40.9), (38, -42.5), (38.9, -44.3), (39.5, -46.1), (39.9, -48), (40, -50)],
                   [(-50, -40), (-42.5, -42.5), (-40, -50)]],
    "Windmill": [[(-40, -50), (-40, 50)], [(40, -50), (40, 50)],
                 [(-40, -40), (-20, -40), (-20, 40), (-40, 40)], [(40, -40), (20, -40), (20, 40), (40, 40)]],
}
POLYLINES["HoleRoundOpen"] = POLYLINES["HoleRound"]

# The ball's intended centre line on each hole (cm), used only to decide which side of a
# wall is "outward" (away from where the ball travels). It stands in for the keyed ball
# path of a roll model that this repo does not have: hole 1 runs along +x to the cup,
# hole 2 along +x to the bank then along -y to the cup, hole 3 along +x to the cup.
CENTRE_LINES = {
    1: [(10.0, Y), (X0 + 200, Y)],
    2: [(10.0, Y), (X0 + 200, Y), (X0 + 200, Y - 200)],
    3: [(10.0, Y), (X0 + 400, Y)],
}


def sample_polyline(pts, step=1.0):
    out = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step))
        out += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]
    out.append(pts[-1])
    return out


def walls(kind, x, y, yaw=0.0):
    """The wall segments ((x0, y0), (x1, y1)) of tile `kind` placed at (x, y) cm with `yaw` degrees."""
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    out = []
    for line in POLYLINES.get(kind, []):
        pts = [(x + px * c - py * s, y + px * s + py * c) for px, py in line]
        out += list(zip(pts, pts[1:]))
    return out


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
eal = unreal.EditorAssetLibrary
ell = unreal.EditorLevelLibrary
CUBE = eal.load_asset("/Engine/BasicShapes/Cube")


def add_component(actor, cls, name, parent=None):
    """Add a component to a placed actor under `parent`, returning the instance.

    `parent` is a component object, or a component NAME string. Parents are
    resolved on every call rather than by keeping handles (a stale handle silently
    attaches to the root, see make_newton_map.py). The name form exists because a
    Blueprint instance's components do not match by object: the Gen3's bracelet_link
    can only be found by name.
    """
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    parent_handle = handles[0]
    if parent is not None:
        parent_handle = None
        seen = []
        want = parent if isinstance(parent, str) else None
        for h in handles:
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h)
            obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)
            nm = obj.get_name() if obj else "?"
            seen.append(nm)
            # A name matches exactly, or as a prefix before an underscore (Blueprint
            # instance components can carry a suffix).
            if obj == parent or (want is not None and (nm == want or nm.startswith(want + "_"))):
                parent_handle = h
                break
        if parent_handle is None:
            raise RuntimeError("no live handle for parent %s; the instance's subobjects are %s"
                               % (parent if want else parent.get_name(), seen))
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", parent_handle)
    params.set_editor_property("new_class", cls)
    params.set_editor_property("blueprint_context", None)
    handle, fail = sub.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("add %s failed: %s" % (cls.get_name(), fail))
    sub.rename_subobject(handle, unreal.Text(name))
    data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
    return unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)


def find_component(actor, cls):
    for c in actor.get_components_by_class(unreal.ActorComponent):
        if isinstance(c, cls):
            return c
    return None


def vec3d(v):
    out = unreal.Vector3d()                 # the property's struct takes no init args: set its fields
    for k, val in zip(("x", "y", "z"), v):
        out.set_editor_property(k, float(val))
    return out


def box(label, center, size, yaw=0.0, friction=None, solref=None):
    """A static, quick-converted box: the engine cube (100 cm, pivot centred) scaled to
    `size` cm and placed at `center`. Quick-convert is the right tool for walls and the
    green. It is the wrong tool for anything that must move or collide as a moving
    body: see README.md."""
    a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*center), unreal.Rotator(0.0, 0.0, yaw))
    a.set_actor_label(label)
    a.static_mesh_component.set_static_mesh(CUBE)
    # Movable although static in MuJoCo: URLab writes a transform to every converted
    # body every step, and UE logs an error for each write to a Static component.
    a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    a.set_actor_scale3d(unreal.Vector(size[0] / 100.0, size[1] / 100.0, size[2] / 100.0))
    qc = add_component(a, unreal.MjQuickConvertComponent, "MjQuickConvert")
    qc.set_editor_property("static", True)
    # Unset, the quick-convert's friction is (1, 1, 1); default to the wall friction.
    qc.set_editor_property("friction", vec3d(friction if friction is not None else WALL_FRICTION))
    if solref is not None:
        qc.set_editor_property("solref", vec3d(list(solref) + [0.0]))
    return a


def mj_pos(v):
    """Unreal cm (left-handed) -> MuJoCo metres (right-handed): (x, -y, z) / 100."""
    return [v[0] / 100.0, -v[1] / 100.0, v[2] / 100.0]


def mj_quat(q):
    """Unreal (x, y, z, w) -> MuJoCo (w, x, y, z) under the same Y mirror: (w, -x, y, -z)."""
    return [q[3], -q[0], q[1], -q[2]]


if HOLE not in HOLES:
    raise RuntimeError("hole must be one of %s, got %r" % (sorted(HOLES), HOLE))

# Authoring touches the editor world, which is not reachable while PIE owns the level.
if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running: stopped it; re-run this script")

# Author into a unique scratch world and write it out with save_map, for the reasons
# set out at length in make_newton_map.py (new_level, delete_asset and
# save_current_level each report success without doing the work; save_map is the one
# that fails honestly).
SCRATCH = "/Temp/RammsMiniGolfAuthoring_%d" % int(time.time() * 1000)
les.new_level(SCRATCH)
world = ues.get_editor_world()
want_scratch = "%s.%s" % (SCRATCH, SCRATCH.rsplit("/", 1)[-1])
if world.get_path_name() != want_scratch:
    raise RuntimeError("new_level did not open the scratch world %s: the editor is on %s"
                       % (want_scratch, world.get_path_name()))
if eal.does_asset_exist(MAP):
    unreal.SystemLibrary.collect_garbage()
    eal.delete_asset(MAP)
print("[map] authoring into %s -> %s" % (world.get_path_name(), MAP))

# Exactly one manager: AMjManager::GetManager() resolves globally.
manager = ell.spawn_actor_from_class(unreal.AMjManager, unreal.Vector(0, 0, 0))
manager.set_actor_label("MjManager")
if TIMESTEP:
    # At the default 0.002 s a 2 m/s strike closes 4 mm per step, so the launch depends on
    # where the step lands in the contact.
    opt = manager.get_editor_property("scene_option")
    opt.set_editor_property("timestep", float(TIMESTEP))
    print("[map] timestep", TIMESTEP)

# No default pawn. The project's default game mode spawns a chair and a crowd
# character, and a pawn with an end-effector controller would also rewrite the arm's
# targets (below). Set default_game_type, not default_game_mode, which silently does nothing.
ws = world.get_world_settings()
game_mode_class = unreal.GameModeBase.static_class()
ws.set_editor_property("default_game_type", game_mode_class)
if ws.get_editor_property("default_game_type") != game_mode_class:
    raise RuntimeError("game mode override did not take")

# The arm: the Gen3 articulation Blueprint at the mount.
bp = eal.load_asset(GEN3_BP)
if not bp:
    raise RuntimeError("Gen3 Blueprint not found: %s" % GEN3_BP)
art = ell.spawn_actor_from_class(bp.generated_class(), unreal.Vector(*MOUNT), unreal.Rotator(0.0, 0.0, BASE_YAW))
art.set_actor_label("Gen3")

# The Blueprint carries the end-effector (IK) and twist controllers. A bound, enabled
# controller rewrites every actuator target on every step, so no joint command from
# Python would take. They must be disabled HERE, before PIE: setting a controller
# property while PIE runs unbinds the articulation (ramms-sim issue #76).
disabled = []
for c in art.get_components_by_class(unreal.ActorComponent):
    if "Controller" in c.get_class().get_name():
        try:
            c.set_editor_property("enabled", False)      # UMjArticulationController.bEnabled (the twist controller has none)
            disabled.append(c.get_class().get_name())
        except Exception as e:
            print("[map] no enabled flag on", c.get_class().get_name(), e)
print("[map] controllers disabled:", disabled)

# Light, so a capture of the running sim is not black.
sun = ell.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 400), unreal.Rotator(-50, -40, 0))
sun.set_actor_label("Sun")
sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
sun.light_component.set_intensity(5.0)
sky_light = ell.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 400))
sky_light.set_actor_label("SkyLight")
sky_light.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
ell.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))

# The green: four slabs with their top at z 0, cut around the cup, and a liner below
# so the ball can drop in and rest.
cx, cy = HOLES[HOLE]["cup"]
g, L = CUP_R, 3000.0
for lab, x0, x1, y0, y1 in (("Green_W", -L, cx - g, -L, L), ("Green_E", cx + g, L, -L, L),
                            ("Green_S", cx - g, cx + g, -L, cy - g), ("Green_N", cx - g, cx + g, cy + g, L)):
    box(lab, ((x0 + x1) / 2, (y0 + y1) / 2, -FLOOR_T / 2), (x1 - x0, y1 - y0, FLOOR_T), friction=FRICTION)
box("Cup_Floor", (cx, cy, -CUP_DEPTH - 1.0), (2 * g + 2 * WALL_T, 2 * g + 2 * WALL_T, 2.0),
    friction=FRICTION, solref=WALL_SOLREF)
# the liner boxes are thick and sit outside the cup radius
for lab, c, s in (("Cup_N", (cx, cy + g + WALL_T / 2, -CUP_DEPTH / 2), (2 * g, WALL_T, CUP_DEPTH)),
                  ("Cup_S", (cx, cy - g - WALL_T / 2, -CUP_DEPTH / 2), (2 * g, WALL_T, CUP_DEPTH)),
                  ("Cup_E", (cx + g + WALL_T / 2, cy, -CUP_DEPTH / 2), (WALL_T, 2 * g + 2 * WALL_T, CUP_DEPTH)),
                  ("Cup_W", (cx - g - WALL_T / 2, cy, -CUP_DEPTH / 2), (WALL_T, 2 * g + 2 * WALL_T, CUP_DEPTH))):
    box(lab, c, s, solref=WALL_SOLREF)

# The walls: every tile's wall lines as thick static boxes whose inner face lies on the
# measured segment. "Outward" is away from the ball's centre line on this hole.
path = sample_polyline(CENTRE_LINES[HOLE])
n = 0
for kind, x, y, yaw, lab in HOLES[HOLE]["tiles"]:
    for (ax, ay), (bx, by) in walls(kind, x, y, yaw):
        ln = math.hypot(bx - ax, by - ay)
        if ln < 0.5:
            continue
        n += 1
        mx, my = (ax + bx) / 2, (ay + by) / 2
        nx, ny = -(by - ay) / ln, (bx - ax) / ln
        px, py = min(path, key=lambda q: math.hypot(q[0] - mx, q[1] - my))
        if (px - mx) * nx + (py - my) * ny > 0:          # the path is on the +n side: outward is -n
            nx, ny = -nx, -ny
        box("Wall_%s_%d" % (lab, n), (mx + nx * WALL_T / 2, my + ny * WALL_T / 2, (WALL_H - RAIL_SINK) / 2),
            (ln + WALL_T, WALL_T, WALL_H + RAIL_SINK), yaw=math.degrees(math.atan2(by - ay, bx - ax)),
            solref=WALL_SOLREF)
print("[map] walls:", n)

# The ball: an articulation of its own, built from components (the newton test's
# pattern: the first body under the model IS the world body, so the ball hangs one
# level down with its free joint). A true SPHERE geom on a free joint, condim 6 so
# rolling friction exists. Quick-converting a sphere instead gives a faceted hull
# that drifted 20 cm sideways over 2 m and slowed at half the carpet rate.
ball0 = (10.0, Y, BALL_R)
ball_art = ell.spawn_actor_from_class(unreal.MjArticulation, unreal.Vector(*ball0))
ball_art.set_actor_label("BallArt")
model = find_component(ball_art, unreal.MjModel)
if model is None:
    raise RuntimeError("articulation has no MjModel component to build under")
world_body = add_component(ball_art, unreal.MjBody, "World", model)
ball_body = add_component(ball_art, unreal.MjBody, "ball", world_body)
add_component(ball_art, unreal.MjFreeJoint, "ball_free", ball_body)
ball_geom = add_component(ball_art, unreal.MjGeom, "ball_geom", ball_body)
ball_geom.set_editor_property("type", unreal.MjGeomType.SPHERE)
ball_geom.set_editor_property("size", [BALL_R / 100.0])
ball_geom.set_editor_property("mass", BALL_MASS)
ball_geom.set_editor_property("condim", 6)                  # sliding + torsional + rolling friction
ball_geom.set_editor_property("friction", list(FRICTION))
ball_geom.set_editor_property("rgba", unreal.LinearColor(0.83, 0.02, 0.19, 1.0))
if CONTACT:
    for k, v in CONTACT.items():
        ball_geom.set_editor_property(k, [float(x) for x in v])
print("[map] ball articulation at", ball0)

# The putter head: a child body of the Gen3's bracelet_link with a box geom, so it is
# a rigid part of the simulated arm. (Quick-converting the head as a mocap box gave a
# body with no geoms, and the ball sailed through it.) Its pose is in the bracelet's
# frame and goes through the Unreal -> MuJoCo conversion above.
if PUTTER:
    brace = None
    for c in art.get_components_by_class(unreal.MjBody):
        if c.get_name() == "bracelet_link":
            brace = c
    if brace is None:
        raise RuntimeError("no bracelet_link MjBody on the Gen3 instance: %s"
                           % [c.get_name() for c in art.get_components_by_class(unreal.MjBody)][:30])
    # By NAME: a Blueprint instance's components do not match by object.
    head = add_component(art, unreal.MjBody, "putter_head", "bracelet_link")
    head.set_editor_property("pos", mj_pos(PUTTER["rel_pos"]))
    head.set_editor_property("quat", mj_quat(PUTTER["rel_quat"]))
    size = PUTTER.get("size", (10.0, 2.5, 2.0))
    head_geom = add_component(art, unreal.MjGeom, "putter_head_geom", head)
    head_geom.set_editor_property("type", unreal.MjGeomType.BOX)
    head_geom.set_editor_property("size", [size[0] / 200.0, size[1] / 200.0, size[2] / 200.0])   # half sizes, metres
    head_geom.set_editor_property("mass", 0.35)
    head_geom.set_editor_property("friction", [0.6, 0.005, 0.0001])
    head_geom.set_editor_property("rgba", unreal.LinearColor(0.85, 0.85, 0.9, 1.0))
    if CONTACT:
        for k, v in CONTACT.items():
            head_geom.set_editor_property(k, [float(x) for x in v])
    print("[map] putter head under", brace.get_name(), "at (MuJoCo m)", mj_pos(PUTTER["rel_pos"]))

if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
    raise RuntimeError("save_map refused %s. It will not overwrite, so the previous asset is still there: "
                       "stop PIE, open some other level, and re-run." % MAP)

# ramms-sim is public and /RammsPrivateAssets/ is an optional private submodule, so a
# public level must not reference private content. Checked against the saved package's
# real dependencies, as make_newton_map.py does.
if MAP.startswith("/Game/"):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions()
    options.set_editor_property("include_hard_package_references", True)
    options.set_editor_property("include_soft_package_references", True)
    try:
        deps = registry.get_dependencies(MAP, options)
    except TypeError:
        deps = registry.get_dependencies(MAP)
    private = sorted(str(d) for d in (deps or []) if str(d).startswith("/RammsPrivateAssets"))
    if private:
        raise RuntimeError("%s references private content, which must never happen in this public repo: %s"
                           % (MAP, ", ".join(private)))
    print("[map] dependency check: no private references")

# One reply line for the host to parse.
print("MINIGOLFMAP " + json.dumps({"ok": True, "map": MAP, "hole": HOLE, "mount": MOUNT, "base_yaw": BASE_YAW,
                                   "ball": ball0, "walls": n, "putter": bool(PUTTER),
                                   "controllers_disabled": disabled, "ball_art": ball_art.get_name(),
                                   "gen3_bp": GEN3_BP, "contact": CONTACT, "wall_solref": WALL_SOLREF,
                                   "wall_friction": WALL_FRICTION, "timestep": TIMESTEP}), flush=True)
