"""Shared helpers: the PIE runners command the robots through their
RammsRobotControlSurfaceComponent (the sink every panel / input map / remote
client will use), not through the controllers directly."""
import unreal

SRC = unreal.RammsControlSource.SCRIPT


def surface_of(actor):
    cs = actor.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
    if not cs:
        raise RuntimeError("%s has no RammsRobotControlSurfaceComponent" % actor.get_name())
    return cs


def find_chaos_pawn():
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
        if p.get_component_by_class(unreal.RammsRobotControlSurfaceComponent):
            return w, p
    raise RuntimeError("no pawn with a control surface in PIE")


def quiet_local_input(actor):
    """Pause the legacy per-tick local writers (the polled keyboard teleop, if a
    pawn still carries one, and the chair pawn's own Event Tick joystick) that
    would overwrite a scripted command every frame. RammsAccess stays ticking:
    it drives the surface and only releases once per watchdog episode."""
    for c in actor.get_components_by_class(unreal.ActorComponent):
        if c.get_class().get_name() == "RammsKeyboardTeleopComponent":
            c.set_component_tick_enabled(False)
    actor.set_actor_tick_enabled(False)


def quiet_arm_workspace(actor):
    """Keep the chair Blueprint from taking the arm. Its ArmWorkspaceTrigger (a
    sphere on the arm base) reacts to an actor tagged Target (Map_Demo's two
    buttons) entering it: teleop off, reach for the button, and teleop back after
    the arm retracts (the reach landed, the button left, or 8 s passed). Until
    then the surface refuses arm.* / gripper.*. A run that drives the chair to a
    button would race that sequence, so the trigger's collision goes off: no
    query, no overlaps."""
    for c in actor.get_components_by_class(unreal.PrimitiveComponent):
        if c.get_name() == "ArmWorkspaceTrigger":
            c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            return True
    return False


def arm_teleop_enabled(actor):
    """The arm teleop component's master enable (None without one): arm.* and
    gripper.* controls are refused while it is off."""
    t = actor.get_component_by_class(unreal.RammsEndEffectorTeleopComponent)
    return t.get_editor_property("teleop_enabled") if t else None


def set_control(cs, cid, value):
    ok = cs.set_control(cid, float(value), SRC)
    if not ok:
        raise RuntimeError("set_control(%s, %s) refused" % (cid, value))
    return ok


def release(cs, *ids):
    return [cs.release_control(i, SRC) for i in ids]


def axis(cs, cid):
    for a in cs.describe_control_surface().get_editor_property("axes"):
        if str(a.get_editor_property("id")) == cid:
            return a
    return None
