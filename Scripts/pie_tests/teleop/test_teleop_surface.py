"""Check that keyboard teleop finds what it needs on a robot's control surface.

URammsKeyboardTeleopComponent no longer names controller classes: it resolves
the robot's URammsRobotControlSurfaceComponent and drives control Ids. That
discovery is the part worth testing, and nothing exercised it before -- the
component is on no shipped Blueprint.

Python exposes only READ key APIs (is_input_key_down and friends), so a held
key cannot be simulated from here. What this asserts instead:

  * the pawn the game mode spawned carries a teleop component
  * teleop's discovery finds the surface, the drive axes and the linkage
    controls -- run against the same surface API teleop consumes
  * commanding those Ids is accepted, which is the call teleop makes each tick

Set the expected linkage-control count before running. A 5-bar offers TWO
controls -- height and fore/aft -- so the count is two per linkage: the
Holonomic variant has none, the Linkage variant has two linkages and so four.

    unreal._ramms_expect_linkages = 4

Run inside the editor, with PIE already started on a teleop test level:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/teleop/test_teleop_surface.py
"""

import unreal

EXPECT_LINKAGES = getattr(unreal, "_ramms_expect_linkages", None)

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("no PIE world -- start play on a teleop test level first")

failures = []


def check(ok, msg):
    print("[teleop-test] %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


pawns = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
         if a.get_component_by_class(unreal.RammsKeyboardTeleopComponent)]
check(len(pawns) == 1, "exactly one pawn carries a teleop component (found %d)" % len(pawns))
if not pawns:
    raise RuntimeError("no teleop pawn in the level; nothing further to check")

pawn = pawns[0]
teleop = pawn.get_component_by_class(unreal.RammsKeyboardTeleopComponent)
surface = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
print("[teleop-test] pawn=%s teleop=%s" % (pawn.get_name(), teleop.get_name()))

check(surface is not None, "the pawn has a control surface for teleop to resolve")
if surface is None:
    raise RuntimeError("no control surface; teleop should have warned at BeginPlay")

described = surface.describe_control_surface()
ids = [str(ax.id) for ax in described.axes]
check("drive.forward" in ids and "drive.turn" in ids,
      "surface advertises the shared drive axes")

linkages = [str(ax.id) for ax in described.axes
            if str(ax.group) == "Linkage" and ax.kind == unreal.RammsControlKind.POSITION]
print("[teleop-test] linkage controls: %s" % (linkages or "none"))
if EXPECT_LINKAGES is not None:
    check(len(linkages) == EXPECT_LINKAGES,
          "found %d linkage controls, expected %d" % (len(linkages), EXPECT_LINKAGES))

contributors = [c.get_name() for c in surface.get_contributor_components()]
check(len(contributors) > 0, "surface reports contributors for tick ordering: %s" % contributors)

KB = unreal.RammsControlSource.KEYBOARD
try:
    check(surface.set_control(unreal.Name("drive.forward"), 0.0, KB),
          "surface accepts a drive.forward command from the Keyboard source")
    check(surface.set_control(unreal.Name("drive.turn"), 0.0, KB),
          "surface accepts a drive.turn command from the Keyboard source")
    # The contract is the advertised Range: a panel or an input map only ever
    # sends a value inside it, so the surface has to accept one. Commanding the
    # LIVE value instead reads as a coin flip near a limit -- a 5-bar's
    # reachable set is a curved region, its fore/aft band is about 4.5 cm wide
    # near the top of the travel, and the live endpoint can sit exactly on the
    # edge, so the height command just issued moves the band out from under it.
    by_id = {str(ax.id): ax for ax in described.axes}
    for lid in linkages:
        ax = by_id[lid]
        live = surface.get_control_value(unreal.Name(lid))
        lo, hi = float(ax.range.x), float(ax.range.y)
        if lo >= hi:
            check(False, "%s advertises a usable range (got %.3f..%.3f)" % (lid, lo, hi))
            continue
        mid = 0.5 * (lo + hi)
        ok = surface.set_control(unreal.Name(lid), mid, KB)
        check(ok, "surface accepts %s at the middle of its advertised range "
                  "(%.2f in %.2f..%.2f, live %.2f)" % (lid, mid, lo, hi, live))
        # The advertised range is a slice of a 2-D reachable region taken at
        # one pose, so it goes stale as the endpoint moves. A live value
        # outside the range the surface is publishing means a panel cannot
        # command the pose the robot is already in.
        if not (lo - 1e-3 <= live <= hi + 1e-3):
            print("[teleop-test] NOTE %s reads %.3f, outside its advertised "
                  "%.3f..%.3f -- the published range is a slice at one pose "
                  "and has gone stale" % (lid, live, lo, hi))
finally:
    surface.release_control(unreal.Name("drive.forward"), KB)
    surface.release_control(unreal.Name("drive.turn"), KB)

print("[teleop-test] ---- %d checks failed ----" % len(failures))
for f in failures:
    print("[teleop-test] FAILED: %s" % f)
