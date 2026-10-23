# Robot pawns

The robots RAMMS simulates in Chaos (`BP_Mebot_Ramms`, `BP_Mebot_Mujoco`) are pawns from
`Source/Ramms`, not from the UE vehicle template they started on. Driving, motors, cameras and input
all live in components (`RobotBase`, the drive controllers, `ControlSurface` / `ControlInput`,
`RobotCamera`, ...); the pawn classes only hold the robot's body together.

| Class | What it is |
|---|---|
| `ARammsRobotPawn` | Body-agnostic base. Creates no components. Gives a view of the robot as one physical thing across its parts: `GetBody()`, `GetSimulatedParts()`, `GetRobotActors()`, `GetRobotMass()`, `TeleportRobot()`, `ApplySelfCollisionChannel()`. |
| `ARammsSkeletalRobotPawn` | A robot whose body is one skeletal mesh simulating its physics asset: the root `VehicleMesh` plus a seat camera and a chase camera on booms. Parent of `BP_Mebot_Ramms` and `BP_Mebot_Mujoco`. |
| `ARammsPlayerController` | The controller of `BP_MebotGameMode` / `BP_MebotMujocoGameMode`. Adds optional project-wide input mapping contexts and nothing else: a robot's keys come from its `ControlInput`. |

`BP_MebotGameMode` is also the project's default game mode, so maps without an override
(`Map_BaseTest`, `Map_CurbTest`, `Map_StairTest`, `Map_DoorTest`) get the chair too.

## Names kept for the existing robots

`ARammsSkeletalRobotPawn` keeps the subobject and property names the robots had under the vehicle
template (`VehicleMesh` / `Mesh`, `Front Spring Arm` / `FrontSpringArm`, `Front Camera`,
`Back Spring Arm`, `Back Camera`) and the same component defaults, so the Blueprints' overrides and
socket attachments carried over when they were reparented. `RobotBase`'s
`ChaosSkeletalMeshComponentName` still points at `VehicleMesh`.

## Building a robot from parts (no skeletal mesh)

A base or seat built from Blueprint physics parts, possibly shared with the MuJoCo robots, derives from
`ARammsRobotPawn` directly:

1. Make the chassis a simulating primitive (static mesh, box, ...) and the **root**, so the actor
   follows it. If the root has to be something else, set `BodyComponentName` to the chassis.
2. Add the other parts as simulating components joined by `PhysicsConstraintComponent`s, or put them
   in child actors (`ChildActorComponent`; `bIncludeChildActorParts` counts them as the robot's).
   Components welded to a simulating parent are part of its body and are not separate parts.
3. Turn on `bApplySelfCollisionChannel`: every colliding part, child actors' included, goes on the
   `RobotSelf` object channel and ignores it, so the robot doesn't collide with itself while the
   world collides with all of it (a constraint only disables collision between the pair it joins).
4. Use `TeleportRobot()` to place or reset it: it moves every part, child actors' and skeletal bodies
   included, keeping their poses relative to the actor.

`Ramms.RobotPawn.Assembly` (Session Frontend > Automation) builds such a robot (static-mesh chassis,
a welded cover, a seat in a child actor) and checks parts, mass, teleport and self-collision.

Not there yet:
- `RobotBase`'s Chaos backend drives motors on a skeletal mesh's physics-asset constraints. Motors on
  `PhysicsConstraintComponent`s between parts need a constraint-component backend in ramms-core.
- RammsWorldGen holds and places players by their root body (and its skeletal bodies). Parts in child
  actors would need `TeleportRobot()` there.

## What changed from the vehicle template

The template pawn (`AWheeledVehiclePawn` → `ARammsPawn` → `ARammsSportsCar`) did a few things to the
chair's physics that nobody had set on purpose. They are gone; the robot now simulates exactly its
assets:

| | Before | Now |
|---|---|---|
| Root body mass (`mebot` plus the seat, rails, mounts and sensors welded to it) | forced to 50 kg by the vehicle movement's `Mass` | 61.7 kg: 21.9 kg `mebot` from its physics asset, 39.9 kg of welded parts from their meshes |
| Root angular damping | 3.0, always (the "in the air" damping, and with no wheels it never saw the ground) | the asset's, 0 |
| Flipped | teleported upright after 3–6 s on its side | stays where it fell |
| Vehicle sleep logic, drag, tick | `ChaosWheeledVehicleMovementComponent` with no wheels, ticking | none |
| Respawn when destroyed | a `BP_SportsCar_Pawn` at the first PlayerStart | none |
| Keys | `IMC_Vehicle_Default` added by the controller | the robot's `ControlInput` only |

### Arm and gripper masses

The Kinova arm (`gen3_6dof`, which despite the name is the 7-DOF Gen3: base + 7 links) and the gripper
(`kinova_gripper`, a Robotiq 2F-85) override every body's mass with the link masses of MuJoCo
Menagerie's `kinova_gen3/gen3.xml` and `robotiq_2f85/2f85.xml`, so the Chaos and MuJoCo robots agree:

| Arm bone | Gen3 link | kg | | Gripper bone (per side) | 2F-85 body | kg |
|---|---|---|---|---|---|---|
| `base_link` | base_link | 1.697 | | `base` | base | 0.777 |
| `link_0` | shoulder_link | 1.377 | | `link_0_*` | driver | 0.009 |
| `link_1` | half_arm_1_link | 1.164 | | `link_1_*` | coupler | 0.014 |
| `link_2` | half_arm_2_link | 1.164 | | `link_2_*` | spring_link | 0.022 |
| `link_3` | forearm_link | 0.930 | | `link_3_*` | follower | 0.013 |
| `link_4` | spherical_wrist_1_link | 0.678 | | `end_*` | pad | 0.0035 |
| `link_5` | spherical_wrist_2_link | 0.678 | | | | |
| `link_6` | bracelet_link (vision) | 0.500 | | | | |

That is 8.19 kg of arm and 0.90 kg of gripper (Kinova lists 8.2 kg for the 7-DOF arm, Robotiq 0.925 kg).
Centres of mass and inertia still come from the bodies' boxes. Before this the boxes gave 11.3 kg and
1.15 kg, and the 90 cm `ArmWorkspaceTrigger` sphere on `link_1` (query-and-probe, so welded in as
if it were solid) added 411 kg to that link. The trigger is now query-only, which keeps it out of the
body while it still overlaps `Interactable` objects.

If the chair needs mass or damping changed, set it on the physics asset (or a `BodyInstance` override
in the Blueprint) where it can be seen. `Scripts/pie_tests/base_component/run_chaos.sh` (drive, turn,
constraint motors, control surface, arm, Enhanced Input, HUD, RammsAccess, MebotController) passes on
the new pawn.

Removed with it: `/Game/VehicleTemplate` (and its `VehicleBasic` map), `/Game/Vehicles/SportsCar`,
`/Game/Vehicles/OffroadCar`, `/Game/Vehicles/PhysicsMaterials`, the sports-car / off-road / time-trial
C++ (`ARammsPawn`, `ARammsSportsCar`, `ARammsOffroadCar`, the wheels, `ARammsGameMode`, `URammsUI`,
`Variant_*`), the `ChaosVehicles` module dependency and the `ChaosVehiclesPlugin` entry. Class
redirects map `RammsPawn` / `RammsSportsCar` to `RammsSkeletalRobotPawn` for assets saved elsewhere.
