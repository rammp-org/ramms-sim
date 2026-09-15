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
