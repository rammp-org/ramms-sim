# Newton PIE test

`make_newton_map.py` authors `/Game/Maps/URL/Map_NewtonTest_URL` from scratch:
the smallest scene that exercises Newton behind URLab — a URLab manager, a
one-hinge pendulum built as a component tree, and the Newton solver component
that installs a custom step handler on the manager's physics engine.

No imported assets and nothing from `/RammsPrivateAssets/`, so it lives in the
public repo and compiles in well under a second. A pendulum is also what the
plugin's own parity harness uses, which keeps the two comparable.

```bash
python3 Scripts/editor_remote_exec.py --file Scripts/pie_tests/newton/make_newton_map.py
```

Then press Play, or request it from the MCP toolset's `begin_pie`, and watch
the solver with `newton_status` or in the log under `LogRammsNewton`.

## Two authoring rules this encodes

**The first body under the model root IS the world body.** URLab writes its
children straight onto the spec's existing worldbody rather than nesting a new
one (`MjSpecBuild.cpp`: "The root's body IS the world body"). So a link needs
*two* body levels. Hanging a joint one level up puts it in the world body and
MuJoCo rejects the model with `joint found in world body`.

**Element properties are `TOptional` and start unset.** A freshly added
`MjGeom` has no type and no size, and MuJoCo rejects it with `size 0 must be
positive in geom`. They do set from Python through `set_editor_property`, so
set them explicitly on every element you add.

![Gen3 arm commanded under Newton inside Unreal](../../../doc/images/newton_gen3_commanded.gif)

The arm above is being *commanded*: the end-effector controller traces a circle
while Newton integrates the dynamics. A passive-settling capture is in
`newton_gen3_unreal.gif` alongside it.

The Kinova Gen3 with its 2F-85 gripper, stepped by Newton through URLab's custom
step handler and rendered by Unreal. `run_newton_capture.py` swaps the pendulum
for `Content/Robots/URL/gen3_2f85_fixed` and starts play; the solver reports

    [NewtonSolver] Newton stepping active (mujoco_cpu, nq=15 nu=8)

## Known gaps

**The saved level does not round-trip.** Re-opening the map drops the outer
`World` body and reparents its child onto the spec, which puts the joint back
in the world body. Building the tree live and entering play without saving
works; the saved asset does not. Until that is understood, treat this script as
the source of truth and re-run it rather than relying on the `.umap`.

**URLab-side state resets do not reach the worker.** `reset_to_keyframe` writes
`qpos` into Unreal's `mjData`, and Newton overwrites it on the next step, so the
pose silently snaps back. No resync fires, because sim time keeps advancing
normally and the solver's external-change detector only looks at time. This is
the `set_state` wiring the plan tracks as the next Newton item; until it lands,
re-enter play rather than resetting to change the starting pose. Activation
*is* handled: the solver resets the sim when the worker finishes loading, so
Newton takes over from the model's initial state rather than from wherever
URLab had already stepped to —

    [NewtonSolver] Sim advanced to t=459.284s during worker load —
    resetting so Newton takes over from the initial state

**`SetActuatorControl` is silently ignored when a controller is bound.** This
looked like a Newton problem and is not one — it reproduces with Newton off,
stepping locally. `AMjArticulation::ApplyControls` hands `ctrl` to a bound,
enabled controller and *returns early*, so the value staged by
`SetActuatorControl` never reaches `d->ctrl`. The call still returns true.

The gen3 blueprint carries `RammsMjEndEffectorController`, enabled, so that
component owns `ctrl`. Command the arm through it instead:

```python
ee.resync_target_to_current_pose()
ee.move_target_by(unreal.Vector(0.0, 0.0, 0.03), unreal.Rotator(0, 0, 0), False)
```

Its inverse kinematics writes the actuator values, Newton integrates them, and
the joints track. `EControlSource` on the articulation (0 = external ZMQ,
1 = internal UI) only matters on the path *after* that early return, so
flipping it does not rescue `SetActuatorControl` while a controller is bound.

**Subobject handles go stale.** A handle from an earlier gather is invalid once
the next add reshapes the tree, and using one silently attaches to the root
instead — which is how an entire body level went missing here. `add_component`
re-resolves parents by object on every call for that reason.
