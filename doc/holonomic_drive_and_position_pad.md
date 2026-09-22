# Holonomic drive, and a positional pad for the 5-bar

Two pieces of work, scoped together because they share the control surface.

Status: **scoping**; nothing implemented yet.

## 1. Holonomic drive controller

### What the robot actually has

`BP_LiftDriveHolonomic_Ramms` carries 14 motors. What drives what today:

| motors | driven by |
| --- | --- |
| `left_center_wheel`, `right_center_wheel` | `DifferentialDrive` — the propulsion today |
| `left_hip_*`, `right_hip_*` | the two 5-bar linkage controllers |
| 4 x `*_omni_wheel` | **nothing** — motorised, exposed as raw axes |
| 4 x `*_crank` | nothing |

So the holonomic hardware is present and unused. **Decision: the new controller
drives the four corner omni wheels** and replaces `DifferentialDrive` on this
pawn.

### Geometry

From `lift_drive_holonomic_ue.xml`, the wheel spin axes:

| wheel | axis | roll direction |
| --- | --- | --- |
| front_left | `(-0.5, -0.8660254, 0)` | 150 deg |
| front_right | `(0.5, -0.8660254, 0)` | 210 deg |
| rear_left | `(0.5, -0.8660254, 0)` | 210 deg |
| rear_right | `(-0.5, -0.8660254, 0)` | 150 deg |

Opposite corners are parallel -- a Killough layout at +/-30 deg, not a mecanum
45. Two independent roll directions span the plane, so vx, vy and omega are all
reachable from four wheels with one redundancy.

**The body `pos` attributes are not usable as chassis offsets.** Each wheel body
nests inside a swing arm, so its `pos` is relative to that parent (0.08 m, not a
wheelbase). Wheel positions therefore have to come from an authored spec or be
derived at runtime from component transforms -- not read off the MJCF.

### Kinematics

For wheel *i* at chassis-relative position `(xi, yi)` with unit roll direction
`di = (cos θi, sin θi)`, the wheel's ground speed is

```
v_i = di . (v + ω × r_i)
    = dix*vx + diy*vy + ω*(xi*diy - yi*dix)
```

and the wheel is then commanded at `v_i / wheel_radius` **rad/s**, through
`URammsRobotBaseComponent::SetMotorVelocityCommand`. That last part matters: the
omni wheels are torque actuators, so writing the rate as a motor command applies
it as newton-metres. The base closes a velocity loop over `GetMotorVelocity` for
exactly this reason.

`wheel_radius` is the axle height above the ground, not a nominal wheel size.
Nothing can check it — a wrong value scales every rate and the loop tracks the
wrong target perfectly. The lift-drive ran at 7.5 cm against a real 10.7.

### Controls

```
drive.forward   Continuous, -1..1   paired with drive.strafe -> one joystick
drive.strafe    Continuous, -1..1
drive.turn      Continuous, -1..1
```

`drive.forward` and `drive.turn` are the ids the differential drive already
uses, so keyboard teleop and the access input drive this with no change. The
new `drive.strafe` is already in the shared vocabulary.

### Where it lives

RammsCore alongside the other controllers, and it moves with them in step 2 of
the extraction. Putting it in a not-yet-created `ramms-controllers` would block
it behind that work.

## 2. Friction

One default class covers every collision geom in the model:

```xml
<default class="collision">
  <geom friction="0.9 0.005 0.0001" ... />
</default>
```

So the corner omni wheels and the centre wheels have **identical** friction --
there is no differentiation to tune, which is the reported problem.

### Outcome: friction was not the blocker

Worth recording, because the evidence pointed the wrong way for a long time.
Three other faults were stopping the base, and each one looked like poor
traction: wheel rates written into torque actuators, the keyboard teleop
re-asserting zero on the drive axes every frame over the top of any other
command, and the wheel radius above. Every friction sweep run before those were
fixed measured noise, including two that came back cleanly non-monotonic.

Swept afterwards, omni slide friction of **0.1** was the best of
inherited / 0.4 / 0.1 / 0.02 and is what ships. Forward and yaw now drive the
base properly. Strafe remains weak at every value.

### What a single coefficient cannot do

`geom_friction` is 3 numbers (slide, spin, roll) and its slide term is
isotropic in the contact tangent plane, so it cannot say "grips along the roll
direction, slides across it" -- which is what an omni wheel does.

MuJoCo *can* express that: `pair_friction` is 5 numbers,
`tangent1, tangent2, spin, roll1, roll2`, and the two tangential coefficients
may differ. The catch is the contact frame. `mju_makeFrame` keeps a tangent the
collision routine supplied and otherwise falls back to a world axis, and
`mjc_PlaneCapsule` is the only routine that supplies one -- cylinder, box,
sphere, convex-mesh and GJK all zero it. **These wheels collide as cylinders**
(r = 0.10695), so a pair would give anisotropy along a world axis, fixed in the
world and wrong the moment the robot yaws. A capsule is not a substitute: its
hemispherical caps would make a 10.7 cm-radius, 4 cm-thick wheel a 25 cm-wide
blob at hub height.

So strafe needs the rollers represented, not a better number. Either as rigid
capsule proxies around the rim (tangential axes, one `<pair>` each, no new
DOFs) or as real free-spinning roller bodies, which makes ordinary isotropic
friction correct and removes the fake tuning entirely.

Friction is unset on the `MjGeom` components (URLab beta properties are
`TOptional` and start unset), so it is inherited from the class above. Overrides
belong on the geoms via a script, the way the linkage rows were added, so a
re-import does not silently revert them.

## 3. Positional pad for the 5-bar (mode 1)

The rate joystick (`jog_up` / `jog_forward`) already works and needs no UI work.
This is the other half: a pad showing **where the endpoint is** inside its
reachable region, with a reset.

The obstacle is that the reachable set is a curved region whose width varies
6x with height (4.5 cm near the top, 28 cm at z=0), so it cannot be described by
two ranges. A pad needs the region itself.

Options, in increasing cost:

1. **Sampled outline.** The contributor computes a polygon once and publishes it
   with the axis pair. The widget draws the polygon plus a live dot. No new
   control kind; the existing paired Position axes carry the values.
2. **A queryable region.** A new contributor method the widget calls to test
   points. More accurate, more chatter, needs a 2D query in the sink interface.
3. **A real 2D control kind.** `ERammsControlKind::Position2D` with vector
   values through the sink. The cleanest model, the largest change: every sink
   signature today is `(FName, float)`.

Option 1 is the recommendation: it reuses `PairedAxis`, needs no sink change,
and the polygon is cheap to compute from the scans the controller already does.

Also wanted: `linkage.<name>.reset` as an Action control, so the pad has its
reset-to-zero.
