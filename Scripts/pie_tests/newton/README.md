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

## Known gaps

**The saved level does not round-trip.** Re-opening the map drops the outer
`World` body and reparents its child onto the spec, which puts the joint back
in the world body. Building the tree live and entering play without saving
works; the saved asset does not. Until that is understood, treat this script as
the source of truth and re-run it rather than relying on the `.umap`.

**Subobject handles go stale.** A handle from an earlier gather is invalid once
the next add reshapes the tree, and using one silently attaches to the root
instead — which is how an entire body level went missing here. `add_component`
re-resolves parents by object on every call for that reason.
