"""Put the Chaos chair back at its PlayerStart, at rest (ARammsRobotPawn::TeleportRobot),
so a later section starts from the same place whatever the ones before it did."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, p = cs_common.find_chaos_pawn()
starts = unreal.GameplayStatics.get_all_actors_of_class(w, unreal.PlayerStart)
if not starts:
    raise RuntimeError("[reset] no PlayerStart")
xf = starts[0].get_actor_transform()
loc = p.get_actor_location()
# Keep the chair's own resting height above the start's capsule origin.
target = unreal.Transform(unreal.Vector(xf.translation.x, xf.translation.y, loc.z + 2.0), unreal.Rotator(roll=0.0, pitch=0.0, yaw=xf.rotation.rotator().yaw))
p.teleport_robot(target, True)
unreal.log("[reset] chair back at the PlayerStart (%.0f, %.0f), yaw %.0f" % (target.translation.x, target.translation.y, xf.rotation.rotator().yaw))
