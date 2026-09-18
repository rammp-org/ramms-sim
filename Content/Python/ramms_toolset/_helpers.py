# Shared lookups for the RAMMS toolset.
#
# These mirror Scripts/pie_tests/base_component/cs_common.py so the MCP tools and
# the PIE runners agree on what "the robot" and "the control surface" mean. Keep
# the two in step: a divergence here shows up as a test that passes under one
# harness and fails under the other.

import json

import unreal

SCRIPT_SOURCE = unreal.RammsControlSource.SCRIPT


def game_world():
    """The PIE world, or None when not playing."""
    sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    return sub.get_game_world() if sub else None


def editor_world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def is_playing():
    return game_world() is not None


def active_world():
    """Prefer the PIE world; fall back to the editor world so read-only tools
    still answer something useful before play starts."""
    return game_world() or editor_world()


def robot_actors(world=None):
    """Every actor carrying a control surface, PIE or editor."""
    world = world or active_world()
    if world is None:
        return []
    out = []
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if actor.get_component_by_class(unreal.RammsRobotControlSurfaceComponent):
            out.append(actor)
    return out


def find_robot(name=""):
    """Resolve a robot by (partial, case-insensitive) name.

    An empty name means "the only one", which is the common case and keeps the
    tool calls short. Ambiguity is an error rather than a silent first-match,
    because picking the wrong chair looks like a physics bug later.
    """
    actors = robot_actors()
    if not actors:
        raise RuntimeError(
            "no actor with a RammsRobotControlSurfaceComponent in the current world "
            "(is PIE running? use begin_pie)"
        )
    if not name:
        if len(actors) == 1:
            return actors[0]
        raise RuntimeError(
            "%d robots present, name one of: %s"
            % (len(actors), ", ".join(a.get_name() for a in actors))
        )
    lowered = name.lower()
    exact = [a for a in actors if a.get_name().lower() == lowered]
    if exact:
        return exact[0]
    partial = [a for a in actors if lowered in a.get_name().lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise RuntimeError(
            "no robot matching '%s'; present: %s"
            % (name, ", ".join(a.get_name() for a in actors))
        )
    raise RuntimeError(
        "'%s' matches %d robots: %s" % (name, len(partial), ", ".join(a.get_name() for a in partial))
    )


def surface_of(actor):
    cs = actor.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
    if not cs:
        raise RuntimeError("%s has no RammsRobotControlSurfaceComponent" % actor.get_name())
    return cs


def component_named(actor, class_name):
    """Find a component by class name string, so the toolset does not hard-fail
    to import when an optional plugin (Newton, MuJoCo) is not in the build."""
    for comp in actor.get_components_by_class(unreal.ActorComponent):
        if comp.get_class().get_name() == class_name:
            return comp
    return None


def axis_records(cs):
    surface = cs.describe_control_surface()
    return list(surface.get_editor_property("axes"))


def axis_named(cs, control_id):
    for a in axis_records(cs):
        if str(a.get_editor_property("id")) == control_id:
            return a
    return None


def enum_name(value):
    """Short, stable name for a UE Python enum value.

    repr() gives '<RammsControlKind.CONTINUOUS: 0>', which is noisy in JSON and
    brittle to parse. Prefer the .name attribute and only fall back to picking
    the name out of the repr, so callers can compare against 'CONTINUOUS'.
    """
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    text = str(value).strip("<>")
    if ":" in text:
        text = text.split(":", 1)[0]
    return text.rsplit(".", 1)[-1].strip()


def dumps(payload):
    """One JSON encoding for every tool, so callers can parse without guessing."""
    return json.dumps(payload, indent=2, sort_keys=False, default=str)
