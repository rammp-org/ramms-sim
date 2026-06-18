"""
Supermarket scene builder — drives the Unreal EDITOR world over Remote Control
(port-parameterized, so the same connection model scales to N headless instances).

Phase A (this file, `skeleton`):
  - strip the level down to essentials (kill landscape / playground cones / car /
    tunnel / brush / leftover probes+groc actors); keep arm, Target, camera rig,
    lights/sky.
  - lay a solid floor at the arm's ground height (Z~8).
  - place a full-aisle layout of OfficeMedley SM_Box_Shelf_005 shelves
    (front row opens toward the arm = grasp row; back row opens back = backdrop)
    resting on the floor.
  - back + side walls so nothing falls into the void.
  - drop a vertical PROBE LADDER into the grasp shelf; on one Play they settle on
    the real boards so we can read true board heights (board collision is private
    over RC, so we measure with physics).

Run (editor open, RC up):
  python build_supermarket.py --skeleton
Then press Play ~3s in the editor and run:
  python build_supermarket.py --read-boards     # reads settled probe Z (PIE world)

NOTHING is saved to disk here (reversible). Save happens only once the layout is
approved.
"""
from __future__ import annotations
import argparse, sys, os, json, random
from ramms_tools.unreal_remote import UnrealRemote, UnrealRemoteError

EAS = "/Script/UnrealEd.Default__EditorActorSubsystem"
CUBE = "/Engine/BasicShapes/Cube.Cube"
SHELF = "/Game/OfficeMedley/Meshes/Basic_Components/SM_Box_Shelf_005.SM_Box_Shelf_005"

# High-friction material so the gripper holds products.
PAD_MAT = "/RammsAssets/PhysicsMaterials/PhysMat_Gripper_FingerPad"

# Editor Python scripting library (CDO) — lets us run a one-off editor-Python command over RC.
PYLIB = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"
# Package path (no object suffix) of the shelf mesh, for EditorAssetLibrary.load_asset.
SHELF_PKG = "/Game/OfficeMedley/Meshes/Basic_Components/SM_Box_Shelf_005"

# shelf local size (measured): 50.8 x 102.1 x 208.9 cm, pivot at bottom-centre.
SHELF_HX, SHELF_HY, SHELF_TOP = 25.4, 51.0, 208.9

FLOOR_TOP_Z = 8.0          # arm base / current ground height
FRONT_GAP = 38.0           # grasp-shelf front face this far in front of arm base

# --- big room (cm, relative to the arm which sits at the near edge) ---
ROOM_BEHIND = 800.0        # open space + back wall behind the arm (camera sits here)
ROOM_FRONT = 3400.0        # store depth in front of the arm
ROOM_HALF_W = 1600.0       # half width (each side in Y)
WALL_H = 3.4               # wall height scale (~340 cm)

# --- front display row (the grasp wall the arm faces) ---
FRONT_N = 5
FRONT_PITCH_Y = 104.0      # 102-wide shelves ~touching = a continuous section

# --- backdrop aisles (gondolas: two rows back-to-back), receding into +X ---
GONDOLA_OFFS = [1200.0, 2350.0]   # gondola centre X, relative to arm base X
GONDOLA_N = 6              # shelves along Y per row
GONDOLA_PITCH_Y = 150.0

# --- shelf boards (world Z of top surfaces), measured from the probe ladder ---
BOARD_TOPS = [26.1, 57.8, 89.5, 121.3, 153.0, 184.7]
GRASP_BOARD = 57.8        # reach sweet-spot; graspable items go here
BOTTOM4 = BOARD_TOPS[:4]  # "fill the bottom 4 levels"
CATALOG = os.path.join(os.path.dirname(__file__), "item_catalog.json")


def vec(x, y, z): return {"X": float(x), "Y": float(y), "Z": float(z)}
def rot(p, yaw, r): return {"Pitch": float(p), "Yaw": float(yaw), "Roll": float(r)}


class Builder:
    def __init__(self, host, port):
        self.ue = UnrealRemote(host=host, http_port=port, timeout=30)
        if not self.ue.ping():
            sys.exit(f"RC unreachable at {host}:{port} (run WebControl.StartServer)")
        self.eas = self.ue.actor(EAS)
        self.grasp_only = False   # if True, shelves use ONLY graspable items (no big clutter)

    # ---- discovery helpers ------------------------------------------------
    def all_paths(self):
        r = self.ue.bridge.call("GetAllActorPaths")
        return r.get("ReturnValue", []) if isinstance(r, dict) else (r or [])

    def label(self, path):
        try: return self.ue.actor(path).call("GetActorLabel")
        except UnrealRemoteError: return ""

    def mesh_name(self, path):
        for c in self.ue.find_components(path, "StaticMesh"):
            try:
                v = self.ue.actor(c["path"]).get_property("StaticMesh")
                if isinstance(v, str) and v:
                    return v.split(".")[-1].rstrip("'")
            except UnrealRemoteError:
                pass
        return ""

    def arm_loc(self):
        h = self.ue.find_actors_by_component("KinovaGen3")
        if not h:
            sys.exit("arm (KinovaGen3) not found")
        a = self.ue.actor(h[0]["actor_path"])
        v = a.call("K2_GetActorLocation")
        return v.get("X", 0), v.get("Y", 0), v.get("Z", 0)

    def destroy(self, path):
        try:
            return bool(self.eas.call("DestroyActor", ActorToDestroy=path))
        except UnrealRemoteError as e:
            print("   destroy fail", str(e)[:80]); return False

    def spawn(self, asset, location, rotation, label):
        r = self.eas.call("SpawnActorFromObject", ObjectToUse=asset,
                          Location=location, Rotation=rotation)
        path = r if isinstance(r, str) else (r.get("ReturnValue") if isinstance(r, dict) else None)
        if not path:
            print("   SPAWN FAILED for", label); return None
        try: self.ue.actor(path).call("SetActorLabel", NewActorLabel=label, bMarkDirty=True)
        except UnrealRemoteError: pass
        return path

    def smc(self, actor_path):
        c = self.ue.find_components(actor_path, "StaticMesh")
        return self.ue.actor(c[0]["path"]) if c else None

    def set_scale(self, path, sx, sy, sz):
        try: self.ue.actor(path).call("SetActorScale3D", NewScale3D=vec(sx, sy, sz))
        except UnrealRemoteError as e: print("   scale fail", str(e)[:80])

    # ---- phase A: clean + skeleton ---------------------------------------
    def clean(self):
        print("=== CLEAN ===")
        JUNK_PATH = ("Landscape", "BP_IDBuzz", "Brush_", "RuntimeVirtualTexture")
        JUNK_MESH = ("SM_Cone", "SM_Tunnel")
        # case-insensitive prefixes: catches MKT_*, Mkt* (old build_market), Groc*, etc.
        JUNK_LABEL = ("groc", "mkt", "spawn_test")
        killed = 0
        for p in self.all_paths():
            short = p.split(".")[-1]
            why = None
            if any(k in p for k in JUNK_PATH):
                why = "path"
            elif "StaticMeshActor" in p:
                lbl = self.label(p)
                if any(lbl.lower().startswith(j) for j in JUNK_LABEL):
                    why = f"label:{lbl}"
                else:
                    mn = self.mesh_name(p)
                    if mn in JUNK_MESH:
                        why = f"mesh:{mn}"
            if why and self.destroy(p):
                killed += 1
                print(f"  - killed {short[:40]} ({why})")
        print(f"  removed {killed} junk actors")

    def floor_and_walls(self, ax, ay):
        print("=== FLOOR + WALLS (big room) ===")
        back_x, far_x = ax - ROOM_BEHIND, ax + ROOM_FRONT
        lo_y, hi_y = ay - ROOM_HALF_W, ay + ROOM_HALF_W
        cx = (back_x + far_x) / 2
        sx, sy = (far_x - back_x) / 100.0, (hi_y - lo_y) / 100.0
        # solid floor slab, top at FLOOR_TOP_Z
        self._slab(cx, ay, FLOOR_TOP_Z, sx, sy, 0.4, "MKT_Floor", top_anchor=True)
        # perimeter walls
        self._wall(back_x, ay, 0.15, sy, WALL_H, "MKT_Wall_Back")
        self._wall(far_x, ay, 0.15, sy, WALL_H, "MKT_Wall_Front")
        self._wall(cx, lo_y, sx, 0.15, WALL_H, "MKT_Wall_L")
        self._wall(cx, hi_y, sx, 0.15, WALL_H, "MKT_Wall_R")
        print(f"  floor {sx*100:.0f}x{sy*100:.0f}cm; room X[{back_x:.0f}..{far_x:.0f}] Y[{lo_y:.0f}..{hi_y:.0f}]")

    def _slab(self, cx, cy, z, sx, sy, sz, label, on_floor=True, top_anchor=False):
        # cube is 100cm; half-thickness = 50*sz. anchor so TOP sits at z (top_anchor)
        center_z = z - 50 * sz if top_anchor else z + 50 * sz
        p = self.spawn(CUBE, vec(cx, cy, center_z), rot(0, 0, 0), label)
        if p: self.set_scale(p, sx, sy, sz)
        return p

    def _wall(self, cx, cy, sx, sy, sz, label):
        # wall bottom on floor (z=FLOOR_TOP_Z), centre raised by half-height
        center_z = FLOOR_TOP_Z + 50 * sz
        p = self.spawn(CUBE, vec(cx, cy, center_z), rot(0, 0, 0), label)
        if p: self.set_scale(p, sx, sy, sz)
        return p

    def shelves(self, ax, ay):
        print("=== SHELVES ===")
        n = 0
        # front display row (grasp wall) — opens -X toward the arm
        fys = [ay + (i - (FRONT_N - 1) / 2.0) * FRONT_PITCH_Y for i in range(FRONT_N)]
        front_cx = ax + FRONT_GAP + SHELF_HX
        gidx = FRONT_N // 2
        for i, y in enumerate(fys):
            tag = "GRASP" if i == gidx else "F"
            self.spawn(SHELF, vec(front_cx, y, FLOOR_TOP_Z), rot(0, 0, 0), f"MKT_Shelf_{tag}{i}")
            n += 1
        # backdrop gondola aisles (two rows back-to-back), spread into +X
        for gi, offs in enumerate(GONDOLA_OFFS):
            gx = ax + offs
            gys = [ay + (i - (GONDOLA_N - 1) / 2.0) * GONDOLA_PITCH_Y for i in range(GONDOLA_N)]
            for i, y in enumerate(gys):
                self.spawn(SHELF, vec(gx - SHELF_HX - 0.5, y, FLOOR_TOP_Z), rot(0, 0, 0), f"MKT_Shelf_G{gi}a{i}")
                self.spawn(SHELF, vec(gx + SHELF_HX + 0.5, y, FLOOR_TOP_Z), rot(0, 180, 0), f"MKT_Shelf_G{gi}b{i}")
                n += 2
        print(f"  placed {n} shelves; grasp shelf = front-centre at X={front_cx:.0f} Y={fys[gidx]:.0f}")
        return front_cx, fys[gidx]

    def solidify_shelf(self):
        """Make the shelf MESH solid so the arm/items can't pass through it: switch
        SM_Box_Shelf_005 collision to complex-as-simple (boards/frame block as drawn) and
        SAVE the mesh asset. Global + permanent + idempotent — baked in here so this one
        script does everything. Runs as editor Python over RC (reliable; no fragile RC
        property paths)."""
        print("=== SOLIDIFY SHELF MESH (complex-as-simple, global) ===")
        py = (
            "import unreal; "
            f"m=unreal.EditorAssetLibrary.load_asset('{SHELF_PKG}'); "
            "bs=m.get_editor_property('body_setup'); "
            "bs.set_editor_property('collision_trace_flag', unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE); "
            "unreal.EditorAssetLibrary.save_loaded_asset(m); "
            "unreal.log('[solidify] SM_Box_Shelf_005 -> complex-as-simple saved')"
        )
        try:
            r = self.ue.actor(PYLIB).call("ExecutePythonCommand", PythonCommand=py)
            print(f"   shelf mesh solidified (ExecutePythonCommand -> {r})")
        except UnrealRemoteError as e:
            print("   solidify FAILED:", str(e)[:140])

    def save_level(self):
        """Save the current level to disk (over RC). Optional. Reuses the existing finger-pad
        material (no transient assets are created), so this doesn't trip the level-save error."""
        print("=== SAVE LEVEL ===")
        py = ("import unreal; "
              "ok=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level(); "
              "unreal.log('[save] save_current_level -> %s' % ok)")
        try:
            r = self.ue.actor(PYLIB).call("ExecutePythonCommand", PythonCommand=py)
            print(f"   save executed (-> {r}); see Output Log '[save]' line for the result")
        except UnrealRemoteError as e:
            print("   save FAILED:", str(e)[:140])

    def probe_ladder(self, grasp_cx, grasp_y):
        print("=== PROBE LADDER (read board heights on Play) ===")
        front_face_x = grasp_cx - SHELF_HX
        n = 11
        for k in range(n):
            z = 18.0 + k * 18.0                       # 18..198cm
            ylane = grasp_y - 40 + k * (80.0 / (n - 1))
            p = self.spawn(CUBE, vec(front_face_x + 6, ylane, z), rot(0, 0, 0), f"MKT_Probe_{k:02d}")
            if not p: continue
            self.set_scale(p, 0.05, 0.05, 0.05)        # 5cm cube
            smc = self.smc(p)
            if smc:
                try:
                    smc.call("SetMobility", NewMobility="EComponentMobility::Movable")
                except UnrealRemoteError:
                    try: smc.set_property("Mobility", "EComponentMobility::Movable")
                    except UnrealRemoteError: pass
                try: smc.call("SetSimulatePhysics", bSimulate=True)
                except UnrealRemoteError as e: print("   physics fail", str(e)[:70])
        print(f"  dropped {n} probes at X={front_face_x+6:.0f} (front of grasp shelf)")

    # ---- phase B: planogram item fill ------------------------------------
    def load_catalog(self):
        items = json.load(open(CATALOG))
        self.grasp_pool = [i for i in items if i["graspable"]]
        # shelf-displayable = fits the ~32cm board gap AND the shelf width, and isn't
        # a ball / oversized prop ("overfill"). This drops basketballs, tall bottles,
        # and big boxes that clip the board above.
        BOARD_GAP = 30.0
        def ok(i):
            return (i["sz"] <= BOARD_GAP and max(i["sx"], i["sy"]) <= 26.0
                    and not i["big"] and "ball" not in i["name"].lower())
        self.shelf_pool = [i for i in items if ok(i)]
        self.grasp_pool = [i for i in self.grasp_pool if ok(i)]
        if self.grasp_only:
            self.shelf_pool = list(self.grasp_pool)   # every shelf item is graspable
        print(f"  catalog: {len(self.shelf_pool)} shelf-displayable "
              f"({len(self.grasp_pool)} graspable); dropped {len(items)-len(self.shelf_pool)} oversized"
              f"{' [grasp-only]' if self.grasp_only else ''}")

    def _purge(self, *prefixes):
        killed = 0
        for p in self.all_paths():
            l = self.label(p)
            if any(l.startswith(pre) for pre in prefixes) and self.destroy(p):
                killed += 1
        return killed

    def place_item(self, it, tx, ty, board_top, yaw, physics, label):
        loc = vec(tx - it["off_x"], ty - it["off_y"], board_top - it["min_z"] + 0.2)
        p = self.spawn(it["path"], loc, rot(0, yaw, 0), label)
        if p and physics:
            smc = self.smc(p)
            if smc:
                try: smc.call("SetMobility", NewMobility="EComponentMobility::Movable")
                except UnrealRemoteError: pass
                # grasp-ready: block + query/physics, high friction, CCD (no tunneling)
                try: smc.call("SetCollisionProfileName", InCollisionProfileName="PhysicsActor")
                except UnrealRemoteError: pass
                try: smc.call("SetPhysMaterialOverride", NewPhysMaterial=PAD_MAT)
                except UnrealRemoteError: pass
                try: smc.call("SetAllUseCCD", InUseCCD=True)
                except UnrealRemoteError: pass
                try: smc.call("SetSimulatePhysics", bSimulate=True)
                except UnrealRemoteError: pass
        return p

    def fill_board(self, cx, cy, os_sign, board_top, rnd, counter, grasp=False, depth_cap=3):
        """os_sign: -1 shelf opens -X, +1 opens +X. Lay a front-facing planogram;
        each product facing is repeated `depth` rows back-to-front (packed shelf)."""
        front_face_x = cx + os_sign * SHELF_HX
        din = -os_sign                        # inward direction
        inset = 3.5
        usable_y = 2 * (SHELF_HY - 3.0)        # ~96 cm along Y
        usable_d = 2 * SHELF_HX - 7.0          # ~44 cm inward depth
        ymax = cy + usable_y / 2
        y = cy - usable_y / 2
        placed = 0
        if grasp:
            # graspable singles, wide spacing so the gripper fits, physics ON
            n = 7
            for k in range(n):
                it = rnd.choice(self.grasp_pool)
                ty = (cy - usable_y / 2) + (k + 0.5) * (usable_y / n)
                tx = front_face_x + din * (inset + it["sx"] / 2 + 2)
                self.place_item(it, tx, ty, board_top, rnd.uniform(-3, 3), True,
                                f"MKT_Grasp_{counter[0]:04d}"); counter[0] += 1; placed += 1
            return placed
        # planogram: blocks of like products across Y, each facing packed `depth` deep
        chosen = rnd.sample(self.shelf_pool, min(len(self.shelf_pool), 8))
        pi = 0
        while y < ymax - 4:
            it = chosen[pi % len(chosen)]; pi += 1
            ypitch = it["sy"] + 0.8
            ndepth = min(depth_cap, max(1, int(usable_d / (it["sx"] + 0.8))))
            for _ in range(rnd.randint(2, 4)):          # facings of this product
                if y > ymax - it["sy"] / 2: break
                ty = y + it["sy"] / 2
                for d in range(ndepth):                  # depth rows of the same product
                    tx = front_face_x + din * (inset + d * (it["sx"] + 0.8) + it["sx"] / 2)
                    self.place_item(it, tx, ty, board_top, rnd.uniform(-2, 2), True,
                                    f"MKT_Item_{counter[0]:04d}"); counter[0] += 1; placed += 1
                y += ypitch
            y += 1.5
        return placed

    def fill_front(self, ax, ay, seed=0):
        print("=== FILL FRONT DISPLAY (planogram) ===")
        self.load_catalog()
        self._purge("MKT_Item_", "MKT_Grasp_", "MKT_Probe_")
        front_cx = ax + FRONT_GAP + SHELF_HX
        fys = [ay + (i - (FRONT_N - 1) / 2.0) * FRONT_PITCH_Y for i in range(FRONT_N)]
        gidx = FRONT_N // 2
        counter = [0]
        for i, y in enumerate(fys):
            rnd = random.Random(seed * 100 + i)
            for bt in BOARD_TOPS:                 # fill EVERY board level of the shelf
                is_grasp = (i == gidx) and abs(bt - GRASP_BOARD) < 1.0
                self.fill_board(front_cx, y, -1, bt, rnd, counter, grasp=is_grasp)
        print(f"  placed {counter[0]} items on the front display "
              f"(grasp items physics-ON on shelf {gidx} board Z{GRASP_BOARD:.0f})")

    def fill_gondolas(self, ax, ay, seed=0):
        print("=== FILL GONDOLA AISLES (backdrop clutter) ===")
        self.load_catalog()
        counter = [10000]
        boards = [57.8, 89.5, 121.3]
        for gi, offs in enumerate(GONDOLA_OFFS):
            gx = ax + offs
            gys = [ay + (i - (GONDOLA_N - 1) / 2.0) * GONDOLA_PITCH_Y for i in range(GONDOLA_N)]
            for i, y in enumerate(gys):
                rnd = random.Random(seed * 1000 + gi * 50 + i)
                for bt in boards:
                    self.fill_board(gx - SHELF_HX - 0.5, y, -1, bt, rnd, counter)  # rowA opens -X
                    self.fill_board(gx + SHELF_HX + 0.5, y, +1, bt, rnd, counter)  # rowB opens +X
        print(f"  placed {counter[0]-10000} backdrop items across the gondolas")

    def read_boards(self):
        print("=== READ SETTLED PROBE HEIGHTS (do this WHILE playing) ===")
        zs = []
        # scan all actors, keep the ones labelled MKT_Probe_*
        for p in self.all_paths():
            lbl = self.label(p)
            if lbl.startswith("MKT_Probe_"):
                v = self.ue.actor(p).call("K2_GetActorLocation")
                zs.append(round(v.get("Z", 0), 1))
        if not zs:
            print("  no probes found — are you in PIE? (press Play first)"); return
        zs.sort()
        # cluster settled Z into boards (gap > 6cm = new board)
        boards, cur = [], [zs[0]]
        for z in zs[1:]:
            if z - cur[-1] > 6: boards.append(cur); cur = [z]
            else: cur.append(z)
        boards.append(cur)
        levels = [round(sum(c) / len(c), 1) for c in boards]
        print(f"  raw settled Z: {zs}")
        print(f"  >>> BOARD HEIGHTS (world Z, top surfaces): {levels}")


def _apply_layout(front_shelves, gondola_shelves, aisles, front_gap):
    """Push caller params into the module layout constants (the Builder methods read these)."""
    global FRONT_N, GONDOLA_N, FRONT_GAP, GONDOLA_OFFS
    FRONT_N = front_shelves
    GONDOLA_N = gondola_shelves
    FRONT_GAP = front_gap
    GONDOLA_OFFS = [1200.0 + i * 1150.0 for i in range(aisles)]


def build(host="127.0.0.1", port=30010, seed=0,
          front_shelves=FRONT_N, gondola_shelves=GONDOLA_N,
          aisles=len(GONDOLA_OFFS), front_gap=FRONT_GAP, grasp_only=False, save=False):
    """One-shot, fully self-contained build (the --build flag). Does EVERYTHING needed for a
    grasp-ready scene so this single script is all anyone needs to run:
      clean -> floor/walls -> shelves -> SOLIDIFY shelf mesh (can't pass through) ->
      planogram fill with every product made grabbable (simulate + collide + friction + CCD).
    grasp_only=True stocks shelves with ONLY graspable items. save=True also saves the level.
    (Skips the probe ladder; uses the calibrated BOARD_TOPS.)

    Example:
        from build_supermarket import build
        build(seed=3, front_shelves=1, aisles=0, grasp_only=True, save=True)
    """
    _apply_layout(front_shelves, gondola_shelves, aisles, front_gap)
    b = Builder(host, port)
    b.grasp_only = grasp_only
    ax, ay, az = b.arm_loc()
    print(f"arm at ({ax:.0f},{ay:.0f},{az:.0f}); building store (seed {seed})")
    b.clean()
    b.floor_and_walls(ax, ay)
    b.shelves(ax, ay)
    b.solidify_shelf()                       # shelf mesh -> solid (boards/frame block)
    b.fill_front(ax, ay, seed)
    b.fill_gondolas(ax, ay, seed)
    if save:
        b.save_level()
    print(f"\nDONE one-shot build{' + SAVED' if save else ' (not saved)'}. Press Play to check items rest.")
    return b


def main():
    ap = argparse.ArgumentParser(description="Build a supermarket scene in the UE editor over Remote Control.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=30010, help="editor Remote Control port")
    # what to do
    ap.add_argument("--build", action="store_true",
                    help="one-shot: clean + floor + shelves + full planogram fill (no probes)")
    ap.add_argument("--skeleton", action="store_true", help="clean + floor + shelves + probe ladder")
    ap.add_argument("--read-boards", action="store_true", help="read settled probe Z (run while in PIE)")
    ap.add_argument("--fill", choices=["front", "gondolas", "all"], help="planogram item fill only")
    # layout knobs (default to the tuned values)
    ap.add_argument("--seed", type=int, default=0, help="re-roll the product layout")
    ap.add_argument("--front-shelves", type=int, default=FRONT_N, help="shelves in the front display row")
    ap.add_argument("--gondola-shelves", type=int, default=GONDOLA_N, help="shelves per gondola row")
    ap.add_argument("--aisles", type=int, default=len(GONDOLA_OFFS), help="backdrop gondola aisles")
    ap.add_argument("--front-gap", type=float, default=FRONT_GAP, help="cm from the arm to the front shelf")
    ap.add_argument("--grasp-only", action="store_true", help="stock shelves with ONLY graspable items")
    ap.add_argument("--save", action="store_true", help="also save the level to disk after building")
    args = ap.parse_args()

    _apply_layout(args.front_shelves, args.gondola_shelves, args.aisles, args.front_gap)

    if args.build:
        build(args.host, args.port, args.seed, args.front_shelves,
              args.gondola_shelves, args.aisles, args.front_gap, args.grasp_only, args.save)
        return

    b = Builder(args.host, args.port)
    b.grasp_only = args.grasp_only
    if args.read_boards:
        b.read_boards(); return
    if args.fill:
        ax, ay, _ = b.arm_loc()
        if args.fill in ("front", "all"):
            b.fill_front(ax, ay, args.seed)
        if args.fill in ("gondolas", "all"):
            b.fill_gondolas(ax, ay, args.seed)
        print("\nDONE (not saved). Press Play to check items rest.")
        return
    if args.skeleton:
        ax, ay, az = b.arm_loc()
        print(f"arm at ({ax:.0f},{ay:.0f},{az:.0f}), facing +X; floor top Z={FLOOR_TOP_Z}")
        b.clean()
        b.floor_and_walls(ax, ay)
        gx, gy = b.shelves(ax, ay)
        b.probe_ladder(gx, gy)
        print("\nDONE (not saved). Press PLAY ~3s, then run: python build_supermarket.py --read-boards")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
