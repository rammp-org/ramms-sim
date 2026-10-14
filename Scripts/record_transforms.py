"""Record every visible mesh on an actor each editor tick, keyed on the physics clock.

For filming a simulated run: the physics backend does not run in real time under
the Movie Render Queue, so record the run first and play the recording back in a
Level Sequence afterwards. One operation per call, chosen by unreal._record_op:

    begin <out.json> [<actor label>]   start sampling (default: the first Pawn with
                                       a RammsRobotBaseComponent)
    status                             one JSON line: recording?, samples, last sim time
    end                                stop and write <out.json>

Run in the editor through Scripts/editor_remote_exec.py while PIE is running, for
example from the pie_curb runner's op() helper, or directly:

    python Scripts/editor_remote_exec.py --code "import unreal; unreal._record_op = 'begin C:/runs/curb.json'; exec(open('Scripts/record_transforms.py').read())"
    ... drive the run ...
    python Scripts/editor_remote_exec.py --code "import unreal; unreal._record_op = 'end'; exec(open('Scripts/record_transforms.py').read())"

What a sample holds: the physics clock (RammsRobotBaseComponent.GetSimulationTime,
mjData time on the MuJoCo backend; -1 when the actor has no clock), wall time
since `begin`, and the world transform of every visible StaticMeshComponent on
the actor, plus every bone of any visible PoseableMeshComponent. URLab moves
those components on the game thread from the physics snapshot, so a transform
and the clock read in the same tick agree. The file also lists the components
(mesh, materials, attach parent and grandparent names, which for a MuJoCo
articulation are the geom and the body) and, once, every other visible static
mesh in the level with its transform, so a playback scene can be rebuilt.

The callback only appends to a list; the file is written at `end`, so sampling
costs the game thread as little as possible.

Format "ramms-transform-recording/1":
    components: [{name, class, mesh, materials, parent, grandparent}]
    poseables:  {component name: {mesh, bones: [names]}}
    scene:      [{actor, name, class, mesh, materials, xf}]
    samples:    [[sim_s, wall_s, [xf per component], {poseable: [xf per bone]}], ...]
    xf = [tx, ty, tz, qx, qy, qz, qw, sx, sy, sz], centimetres, Unreal world space
"""

import json
import time

import unreal

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
MAX_SAMPLES = 20000   # about 5 minutes at 60 Hz


def take_op():
    op = getattr(unreal, "_record_op", "status")
    if hasattr(unreal, "_record_op"):
        delattr(unreal, "_record_op")
    return op.split(None, 2)


def out(d):
    print("RECORD " + json.dumps(d))


def find_actor(label=None):
    world = ues.get_game_world()
    if world is None:
        return None, None
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    if label:
        for a in actors:
            if a.get_actor_label() == label or a.get_name() == label:
                return world, a
        return world, None
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn):
        if a.get_component_by_class(unreal.RammsRobotBaseComponent) is not None:
            return world, a
    return world, None


def xf_row(xf):
    t, q, s = xf.translation, xf.rotation, xf.scale3d
    return [round(t.x, 3), round(t.y, 3), round(t.z, 3),
            round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6),
            round(s.x, 4), round(s.y, 4), round(s.z, 4)]


def asset_path(obj):
    return obj.get_path_name() if obj is not None else None


def mesh_info(comp):
    mesh = comp.static_mesh if isinstance(comp, unreal.StaticMeshComponent) else None
    parent = comp.get_attach_parent()
    grand = parent.get_attach_parent() if parent is not None else None
    return {"name": comp.get_name(), "class": comp.get_class().get_name(), "mesh": asset_path(mesh),
            "materials": [asset_path(comp.get_material(i)) for i in range(comp.get_num_materials())],
            "parent": parent.get_name() if parent else None, "grandparent": grand.get_name() if grand else None}


def unhook():
    old = getattr(unreal, "_record_handle", None)
    if old is not None:
        unreal.unregister_slate_post_tick_callback(old)
    unreal._record_handle = None


def begin(path, label=None):
    unhook()
    world, actor = find_actor(label)
    if world is None:
        raise RuntimeError("PIE is not running")
    if actor is None:
        raise RuntimeError("no actor to record (%s)" % (label or "no Pawn with a RammsRobotBaseComponent"))
    base = actor.get_component_by_class(unreal.RammsRobotBaseComponent)

    statics = [c for c in actor.get_components_by_class(unreal.StaticMeshComponent)
               if c.is_visible() and c.static_mesh is not None]
    poseables = [c for c in actor.get_components_by_class(unreal.PoseableMeshComponent) if c.is_visible()]
    bones = {}
    for c in poseables:
        mesh = c.get_skinned_asset() if hasattr(c, "get_skinned_asset") else c.skeletal_mesh
        bones[c.get_name()] = {"mesh": asset_path(mesh), "bones": [str(c.get_bone_name(i)) for i in range(c.get_num_bones())]}

    scene = []
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if a == actor:
            continue
        for c in a.get_components_by_class(unreal.StaticMeshComponent):
            if c.is_visible() and c.static_mesh is not None:
                info = mesh_info(c)
                info["actor"] = a.get_actor_label()
                info["xf"] = xf_row(c.get_world_transform())
                scene.append(info)

    rec = {
        "format": "ramms-transform-recording/1",
        "map": world.get_name(),
        "actor": actor.get_actor_label(),
        "actor_class": actor.get_class().get_path_name(),
        "units": "cm, UE world space; rotation is a quaternion x y z w",
        "row": "[sim_s, wall_s, [component xf...], {poseable: [bone xf...]}]",
        "components": [mesh_info(c) for c in statics],
        "poseables": bones,
        "scene": scene,
        "samples": [],
    }
    unreal._record = rec
    unreal._record_path = path
    t0 = time.perf_counter()
    handle = []

    def sample(dt, base=base, statics=statics, poseables=poseables, bones=bones, rec=rec, handle=handle, t0=t0):
        rows = rec["samples"]
        try:
            sim = base.get_simulation_time() if base is not None else -1.0
            pose = {c.get_name(): [xf_row(c.get_bone_transform_by_name(n, unreal.BoneSpaces.WORLD_SPACE))
                                   for n in bones[c.get_name()]["bones"]] for c in poseables}
            rows.append([round(sim, 5), round(time.perf_counter() - t0, 4),
                         [xf_row(c.get_world_transform()) for c in statics], pose])
        except Exception as e:
            # PIE ended under us, or a component went away: stop cleanly
            rec["error"] = repr(e)
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._record_handle = None
            return
        if len(rows) >= MAX_SAMPLES:
            rec["truncated"] = True
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._record_handle = None

    handle.append(unreal.register_slate_post_tick_callback(sample))
    unreal._record_handle = handle[0]
    out({"recording": True, "actor": actor.get_actor_label(), "components": len(statics),
         "poseables": len(poseables), "scene": len(scene), "sim_clock": base is not None})


def status():
    rec = getattr(unreal, "_record", None)
    rows = rec["samples"] if rec else []
    out({"recording": getattr(unreal, "_record_handle", None) is not None, "samples": len(rows),
         "last_sim": rows[-1][0] if rows else None, "error": rec.get("error") if rec else None})


def end():
    unhook()
    rec = getattr(unreal, "_record", None)
    if rec is None:
        raise RuntimeError("nothing recorded")
    path = unreal._record_path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, separators=(",", ":"))
    rows = rec["samples"]
    out({"written": path, "samples": len(rows), "sim_span": [rows[0][0], rows[-1][0]] if rows else None,
         "error": rec.get("error"), "truncated": rec.get("truncated", False)})


args = take_op()
op = args[0]
if op == "begin":
    begin(args[1], args[2] if len(args) > 2 else None)
elif op == "status":
    status()
elif op == "end":
    end()
else:
    raise RuntimeError("unknown op %s" % op)
