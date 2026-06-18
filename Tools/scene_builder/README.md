# scene_builder

One command builds a **grasp-ready store scene** around the Kinova arm, driving the editor
over **Remote Control**. Run it from a terminal (not the editor Output Log).

`build_supermarket.py --build` does everything end-to-end:
**clean → floor/walls → shelves → solidify the shelf collision → fill with grabbable items**
(simulate + collide + high friction + CCD). Result: the arm can't pass through the shelf and
every item can be picked up.

## Setup (once)

1. **Content packs** — the shelf + item meshes come from `OfficeMedley`, `ConvenienceStore`,
   and `BookStackBPV2`. These are **not in the repo** (gitignored). Download them from the team
   Drive and drop them under `Content/`:
   <https://drive.google.com/drive/folders/12DBohSoSZKU44ZqyUiUoR2qEu451hmYN?usp=drive_link>
2. **Dependency** — the one Python dep:
   ```bash
   pip install -r requirements.txt        # = pip install git+https://github.com/rammp-org/ramms-tools.git
   ```
3. **Editor** — open a map with the Kinova arm (a `KinovaGen3` actor) in it. The Remote Control
   web server auto-starts; the project also ships `Config/DefaultRemoteControl.ini` (enables
   remote-Python) so the shelf-solidify step can run.

## Build (one command)

One stocked shelf in front of the arm, everything grabbable:
```bash
python build_supermarket.py --build --front-shelves 1 --aisles 0 --grasp-only
```
A full store:
```bash
python build_supermarket.py --build --seed 0
```
Then **save + Play** (or add `--save` to have the script save the level for you).

| flag | default | meaning |
|------|---------|---------|
| `--build` | — | run the whole pipeline |
| `--grasp-only` | off | stock only graspable items |
| `--save` | off | save the level to disk after building |
| `--seed` | 0 | re-roll the product layout |
| `--front-shelves` | 5 | shelves in the front display row |
| `--gondola-shelves` | 6 | shelves per gondola row |
| `--aisles` | 2 | backdrop gondola aisles |
| `--front-gap` | 38 | cm from the arm to the front shelf |
| `--host` / `--port` | 127.0.0.1 / 30010 | target editor instance |

## Files

| File | Role |
|------|------|
| `build_supermarket.py` | the builder (clean → floor/walls → shelves → solidify → grabbable fill) |
| `catalog_items.py` | one-time pass that measures items → `item_catalog.json` |
| `item_catalog.json` | measured catalog the builder reads (committed; rebuild only if items change) |
| `requirements.txt` | the one dependency: `ramms-tools` |

## Recalibration (only if the shelf sits at a different height)

The builder uses tuned board heights (`BOARD_TOPS`). To recalibrate:
```bash
python build_supermarket.py --skeleton      # room + shelves + probe ladder
# press PLAY ~3s so the probes settle, then:
python build_supermarket.py --read-boards    # prints the true board heights -> paste into BOARD_TOPS
python build_supermarket.py --fill all --seed 0
```
Rebuild the item catalog only if the item assets change: `python catalog_items.py`.
