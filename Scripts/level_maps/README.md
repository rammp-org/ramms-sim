# Level-assist course maps

The ground the level assist is tested on: `/Game/Maps/Level/Map_Level_<id>_URL`, one map per course. The maps are generated and never edited by hand. They name no robot: each starts whichever robot is chosen (`ramms.Robot`).

- `level_terrain.py` defines every course's ground as planes and the slabs that build them. It has no `unreal` import, so the map builder, the course runner and its measures all read the same ground.
- `make_level_maps.py` builds the maps inside the editor, each from an empty level, and checks each one before it is kept.

```
python -I Scripts/level_maps/level_terrain.py                 # every course, its seams and its flush check
python -I Scripts/level_maps/tests/test_level_terrain.py      # the terrain's maths (no editor)
python -I Scripts/editor_remote_exec.py --file Scripts/level_maps/make_level_maps.py   # build them all, in a running editor
```

To build only some, set `RAMMS_LEVEL_MAPS=FLAT,RAMP5` in the editor's environment, or `unreal._ramms_level_maps = "FLAT,RAMP5"` in a running editor before the build.

## The courses

A course is a lane along +X, 3 m wide unless said, starting at x = 0 with its centreline on y = 0. Every course begins and ends on its own flat run-in and run-out slab. A plane's `grade` rises along +X (the pitch of a robot heading +X, nose up positive). Its `cross` rises toward +Y (its roll, positive with the right side up: the sign of `level.pref.roll`).

| id | ground |
|---|---|
| `FLAT` | 12 m of flat ground: the control |
| `RAMP5`, `RAMP8`, `RAMP12` | a ramp up, a landing, a ramp down: 1:12 (4.76°), 8° and 12° |
| `CROSS2`, `CROSS6` | a 6 m wide lane falling 1.15° and 6° to one side; the robot starts on it |
| `BREAK6` | flat, 6° up, 6° down, flat: a sag, a crest, a sag |
| `STEEPEN` | a grade breaking to a steeper one: 3°, then 6°, a landing, 6° down, then 3° |
| `WARP` | the cross fall changes sign along the path: flat, 6° one way, 6° the other, flat |
| `CROWN` | two planes falling 2.3° either side of a ridge along the lane (starts: straddling it, on one side, crossing it at 20°) |
| `FOLD` | a 6° plane entered and left across fold lines 30° off square |
| `COMBO` | a 5° grade carrying 3° of cross fall, a twist to 2° of the opposite cross fall on the same grade, then a skewed crest onto the flat |
| `PARK` | two pads to stand on: a 6° grade and a 6° cross fall |
| `TRANSITIONS` | one run through them all: flat, grade up, flat, cross fall left, cross fall right, grade down with cross fall, flat |

Every plane gives at least 4 s at 0.6 m/s with every wheel on it (a test holds this for a 60 cm wheelbase).

## Seams without steps

Two planes can only meet where they are equal, so a course's seams follow from its planes:

- **A fold**: the grade changes. The planes meet along a line through the joint's point on the centreline. The line is square to the path when only the grade changes. It is skewed when the cross fall changes with it, and the wheels then cross it one at a time.
- **A twist**: only the cross fall changes. The two planes then meet along the centreline alone, so no line across the path joins them. Two wedge planes round the joint's point join them instead: the left one climbs, the right one falls, and the centreline keeps its height. A wheel pair is twisted against the other while it passes.

What a trace or a wheel meets is the highest slab top over a point:

- Across a valley the ground is the higher of two planes, so the two slabs overlap.
- Across a crest it is the lower, so each slab ends exactly on the fold line. A slab's two edges across its own `along` direction are exact, so a slab that ends on a crest is laid out along that fold's normal.
- A twist is one crest line through the joint with two planes on each side.

`Layout.flush()` checks every course: what the slabs build equals the planes meant everywhere on the lane, no seam has a step, and no slab's body comes up through a neighbour. The map builder runs it before it spawns anything. It then traces the built level from above on a grid and on both sides of every seam: the surface must be the terrain's within 0.2 cm, and no seam may step more than the planes do. The saved map must reference nothing of the optional private plugin.

## For a scorer

- `layout(id).surface_z(x, y)`: the surface as built.
- `layout(id).ground_attitude(points, yaw)`: the pitch and roll of the ground under a robot whose standing wheels are over `points`, at its heading.
- `layout(id).start(name, direction)`: a start's pose and path.
- `layout(id).profile(start, footprint)`: the ground along a path as a robot's wheels meet it. It gives the segments (every wheel on one plane) and the transitions between them, each from the first wheel reaching the seam to the last leaving it.
