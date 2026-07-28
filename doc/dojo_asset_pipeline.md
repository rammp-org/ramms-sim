# Dojo articulated-asset pipeline

Blender → Unreal (and MuJoCo / Newton / Isaac) pipeline for household
training assets with articulated parts: cabinets with drawers, fridges,
microwaves, stoves — anything with doors/drawers a robot should open.

```
dojo.blend (Blender 5.1)
   │  Scripts/dojo_articulated_export.py            one folder per asset:
   ▼                                                ├─ <asset>__root.fbx        static part + UCX boxes
UE_VAULT_EXPORT/dojo_parts/<asset>/ ────────────────├─ <asset>__door_1.fbx      (origin = hinge pivot)
   │                                                ├─ <asset>_<group>_*.png    baked BaseColor/ORM/Normal
   │  Scripts/ue_import_dojo_parts.py               ├─ <asset>.usda             UsdPhysics bodies + joints
   ▼                                                ├─ <asset>_mjcf.xml (+.obj) MuJoCo bodies + joints
/Game/DojoParts: BP_<asset> Blueprints              └─ rig_manifest.json        engine-neutral joint spec
```

The single source of truth for articulation is the **joint spec**: per mover
`{type: revolute|prismatic, axis, pivot, limits}`, stored both in
`rig_manifest.json` and as `dojo_*` custom properties on the part empties in
the .blend. UE Blueprints, USD, and MJCF are all generated from it, so all
engines agree on the physics.

## Requirements

- **Blender 5.1** (bundled `pxr` USD python is used for the `.usda` emitter).
- **UE 5.7** with Python enabled. To push scripts remotely, either UE Python
  Remote Execution (`Scripts/editor_remote_exec.py`, port 6776) or the
  Remote Control API (port 30010, needs *Enable Remote Python Execution* in
  Project Settings → Remote Control).

## Blender side: `Scripts/dojo_articulated_export.py`

Run inside Blender (Scripting tab) or headless:

```
blender --background dojo.blend --python Scripts/dojo_articulated_export.py
```

Everything is driven by the `CONFIG` dict at the top of the script:

| Key | Meaning |
| --- | --- |
| `export_mode` | `"static_parts"` (this pipeline) or `"skeletal"` (legacy bone-rigged FBX per asset) |
| `roots` | list of top-level scene objects to process, or `None` for all |
| `split` | how a root breaks into assets (`whole` / `("prefix", [...])` / `("children", None)`) |
| `output_dir` | export destination (one folder per asset) |
| `bake_resolution` / `_small` | atlas budget per asset (share-scaled per material group) |
| `ucx_max_boxes`, `ucx_dust_volume` | collision-box cap and junk-island floor per part |
| `emit_usd`, `emit_mjcf` | extra emitters (static_parts mode only) |

For a scripted run with different settings, import the module and override:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("dojo_export", "Scripts/dojo_articulated_export.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
mod.CONFIG.update(export_mode="static_parts", roots=["cabinets"], output_dir=r"D:\out")
report = mod.main()
```

### How parts and joints are found

1. **Name-driven**: an EMPTY whose name matches the door/drawer regexes
   (`door`, `drawer`, ...) becomes a mover; everything else is static and is
   welded to the asset root (or to a mover it is named after / overlaps).
2. **`dojo_*` custom properties** on the part empty override inference:
   `dojo_joint` (`revolute`/`prismatic`/`fixed`), `dojo_pivot`, `dojo_axis`,
   `dojo_limits`, plus fixers `dojo_close_angle`, `dojo_close_swing`,
   `dojo_bone_of`, `dojo_hinge`. Edit them in Object Properties → Custom
   Properties, re-export, done.
3. **`OVERRIDES`** dict in the script (same keys, by object name) beats both.

Run the **annotate pass** once per scene so the analyzer's inferences become
visible, editable properties (this is how you fix a wrong hinge or opening
direction without touching code):

```python
mod.main(annotate=True)   # writes dojo_* props onto the part empties; save the .blend
```

Doors posed open in the scene are auto-closed before export (bounds-trial +
sibling clustering); the recorded closing angle also determines the joint's
opening sign. Materials are baked per *material group* (normalized source
material name) into BaseColor/ORM/Normal PNG sets — each group stays its own
slot/material in every engine, so appearance variants are parameter swaps.

### Collision

Each rigid part's meshes are joined and every connected mesh island becomes
an axis-aligned `UCX_` box (deduped, dust-pruned, capped). Because this
furniture is panel-built, that yields near-perfect compound collision: a
drawer exports as bottom + four walls and can physically hold objects.

## Unreal side: `Scripts/ue_import_dojo_parts.py`

Edit `SOURCE_DIR` / `DEST_DIR` at the top, then run in-editor
(Tools → Execute Python Script) or push it:

```
python Scripts/editor_remote_exec.py --file Scripts/ue_import_dojo_parts.py
```

Per asset it imports the part FBXs as Static Meshes (UCX collision, real
scale), imports textures, creates `MI_<asset>_<group>` instances of
`M_Dojo_Master` / `M_Dojo_Master_Glass` (built on first run; expose `Tint`,
`RoughnessScale`, `MetallicScale`, glass `Opacity`), and assembles
`BP_<asset>`: one simulated `StaticMeshComponent` per part plus one
`PhysicsConstraintComponent` per joint —

- **revolute** → twist-limited constraint, frame X aligned to the hinge
  axis, `angular_rotation_offset` centering the `[lo, hi]` range;
- **prismatic** → linear-X-limited constraint, frame shifted half-range
  along the travel axis so motion runs `[closed, open]`.

### Importer gotchas (hard-won — do not "simplify" these away)

1. **UE 5.7 Interchange ignores `FbxImportUI` options and `UCX_` meshes.**
   The script sets `Interchange.FeatureFlags.Import.FBX 0` (session-scoped)
   to route through the legacy FBX importer.
2. **The legacy importer defaults `convert_scene_unit` off** and reads the
   meter-unit FBX as centimeters (everything 100× too small). The script
   sets it on.
3. **Reimporting over an existing asset reuses the settings stored on that
   asset** and silently ignores new task options. If import options change,
   delete `/Game/DojoParts/Meshes` (+ `Blueprints`) and import fresh.

Coordinate mapping used for manifest positions/axes:
`ue = (x, −y, z) × 100` (exporter writes meters, Z-up).

## Robotics engines

- **MuJoCo** (`RammsMujocoPhysics` / unreal-robotics-lab): load
  `<asset>_mjcf.xml` directly — bodies, `hinge`/`slide` joints with ranges
  (degrees/meters), native box collision geoms, and per-part OBJ visual
  geoms sit next to it.
- **Newton / Isaac / anything OpenUSD**: `<asset>.usda` carries
  `ArticulationRootAPI`, `RigidBodyAPI` bodies, box `CollisionAPI` prims,
  and `Revolute/PrismaticJoint`s with limits (joint axes snapped to the
  dominant world axis; a manifest note is added if a hinge was >5° off).

## Verifying / tuning

Drop a `BP_*` in a level and PIE: pull a drawer, swing a door. If something
opens the wrong way, flip that mover's `dojo_limits` sign in Blender (e.g.
`[0, 120]` → `[-120, 0]`) and re-export — or tweak the constraint in the BP
for a quick test. Constraint sign conventions have been reviewed but not
exhaustively simulation-tested across all 65 assets.

## Legacy skeletal mode

`export_mode="skeletal"` produces the original one-FBX-per-asset skeletal
meshes (bone per mover) that pair with `ue_import_dojo.py` and the
`UCabinetPhysicsTools` box physics-asset generator
(`Source/Ramms/Furniture/CabinetPhysicsTools.*`). Both modes share the
analyzer, baker, and manifest, and can coexist in separate output/content
folders.
