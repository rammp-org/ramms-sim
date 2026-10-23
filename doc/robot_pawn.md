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
| Root body (`mebot`) mass | forced to 50 kg by the vehicle movement's `Mass` | the physics asset's, 61.7 kg |
| Root angular damping | 3.0, always (the "in the air" damping, and with no wheels it never saw the ground) | the asset's, 0 |
| Flipped | teleported upright after 3–6 s on its side | stays where it fell |
| Vehicle sleep logic, drag, tick | `ChaosWheeledVehicleMovementComponent` with no wheels, ticking | none |
| Respawn when destroyed | a `BP_SportsCar_Pawn` at the first PlayerStart | none |
| Keys | `IMC_Vehicle_Default` added by the controller | the robot's `ControlInput` only |

If the chair needs mass or damping changed, set it on the physics asset (or a `BodyInstance` override
in the Blueprint) where it can be seen. `Scripts/pie_tests/base_component/run_chaos.sh` (drive, turn,
constraint motors, control surface, arm, Enhanced Input, HUD, RammsAccess, MebotController) passes on
the new pawn.

Removed with it: `/Game/VehicleTemplate` (and its `VehicleBasic` map), `/Game/Vehicles/SportsCar`,
`/Game/Vehicles/OffroadCar`, `/Game/Vehicles/PhysicsMaterials`, the sports-car / off-road / time-trial
C++ (`ARammsPawn`, `ARammsSportsCar`, `ARammsOffroadCar`, the wheels, `ARammsGameMode`, `URammsUI`,
`Variant_*`), the `ChaosVehicles` module dependency and the `ChaosVehiclesPlugin` entry. Class
redirects map `RammsPawn` / `RammsSportsCar` to `RammsSkeletalRobotPawn` for assets saved elsewhere.
