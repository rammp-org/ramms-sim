"""Editor: a showcase level for the articulated SimReady assets: a furnished, roofless home open at the front like a
dollhouse (an L-shaped kitchen with an island and stools, a breakfast nook, dining and living room, laundry, bathroom,
bedroom and a porch) whose fridge, kitchen base and wall cabinets, range, microwave, pedal bin, washer, vanity, chest
of drawers and wheelie bin (18 in all) are URLab articulations that run on Chaos or MuJoCo. Dressed with static
SimReady, FreeFurniturePack and HousePropsFurniture props (rugs, art, curtains, books, tableware, toys). The level
references /Game/SimReady and Fab content, which is not committed, so neither is the level.

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "simready_showcase.py").read())

Then record it with simready_open.py (SO_STAGGER, SO_CAMPATH; see the README). Options (consumed): SC_MAP (default
/Game/Maps/SimReady/Map_SimReady_Showcase), SC_ENGINE ("Chaos", the default, "MuJoCo" or "Auto"). Missing props are
skipped and listed in Saved/ChaosArticulation/showcase.log; when the level cannot be opened or created it stops before
touching any level.

Layout (cm): the front (open side) faces -Y; the back wall is at y = 420, the side walls at x = -700 and 700.
"""
import os, unreal

_SC = {k: globals().pop(k) for k in list(globals()) if k.startswith("SC_")}

MJ = "/Game/SimReady/MuJoCo/"
SR = "/Game/SimReady/"
FF = "/Game/Fab/FreeFurniturePack/Meshes/"
HP = "/Game/HousePropsFurniture/Meshes/Meshes_props/"

# Yaw (degrees) that turns each asset's front to +X, as the worldgen palettes measure it (palettes.FACING_FIX,
# simready.FACING_FIX). The ForgeCAD SimReady packages face +Y as authored.
FRONT = {"sr_fc": -90.0, "SM_SR_FC_dining_chair": -90.0, "SM_SR_NV_table_bedside_b01": 90.0, "SM_Bathtub": -90.0,
         "SM_SR_NV_container_recycle_blue_wheeled_a01": -90.0}
FACE = {"E": 0.0, "N": 90.0, "W": 180.0, "S": -90.0}

WALL_H, WALL_T = 260.0, 12.0


def _front(path):
    name = path.rsplit("/", 1)[-1]
    return FRONT.get("sr_fc" if name.startswith("sr_fc_") else name, 0.0)


def _showcase(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    log = []
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    acs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    eal = unreal.EditorAssetLibrary
    level = opts.get("SC_MAP", "/Game/Maps/SimReady/Map_SimReady_Showcase")
    pal = unreal.load_asset("/RammsWorldGen/Palettes/PAL_Default")

    def mat(slot):
        return pal.material_path(slot) if pal else ""

    def tag(a, folder):
        a.set_folder_path("Showcase/" + folder)
        return a

    def piece(kind, loc, yaw, sx, sy, sz, material, folder, **kw):
        p = acs.spawn_actor_from_class(unreal.RammsProcPiece, unreal.Vector(*loc), unreal.Rotator(yaw=yaw))
        p.set_editor_property("kind", kind)
        p.set_editor_property("size_x", sx)
        p.set_editor_property("size_y", sy)
        p.set_editor_property("size_z", sz)
        p.set_editor_property("material_path", material)
        p.set_editor_property("uv_scale", kw.pop("uv", 200.0))
        for k, v in kw.items():
            p.set_editor_property(k, v)
        p.rebuild()
        return tag(p, folder)

    def floor(x0, x1, y0, y1, top, material, folder="Floors", uv=200.0):
        # a slab's origin is its +X start at mid-width, its top at the origin
        return piece(unreal.RammsProcPieceKind.SLAB, (x0, (y0 + y1) / 2.0, top), 0.0, x1 - x0, y1 - y0, 10.0, material, folder, uv=uv)

    def wall(x0, y0, x1, y1, folder="Walls", door=None, windows="", height=WALL_H):
        # axis-aligned; a wall runs along its +X from its start, centred on its thickness
        length = abs(x1 - x0) + abs(y1 - y0)
        yaw = 0.0 if y0 == y1 else 90.0
        kw = {"material_path2": mat("Mat.Trim.Interior"), "material_path3": mat("Mat.Glass"), "openings": windows}
        if door:
            kw.update(opening_width=door[1], opening_offset=door[0], opening_height=210.0)
        return piece(unreal.RammsProcPieceKind.WALL, (x0, y0, 0.0), yaw, length, WALL_T, height, mat("Mat.Wall.Interior"), folder, **kw)

    def light(x, y, z=232.0, candela=40.0, radius=520.0, folder="Lights"):
        # soft fill under the open roof: no shadows, so the rooms read evenly in the sun's shade
        l = acs.spawn_actor_from_class(unreal.PointLight, unreal.Vector(x, y, z))
        c = l.get_component_by_class(unreal.PointLightComponent)
        c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
        c.set_intensity(candela)
        c.set_attenuation_radius(radius)
        c.set_cast_shadows(False)
        c.set_light_color(unreal.LinearColor(1.0, 0.92, 0.82, 1.0))
        return tag(l, folder)

    def place(path, folder, face="S", x=None, y=None, z=0.0, back=None, yaw_extra=0.0, scale=1.0):
        """Spawn a Blueprint or a static mesh with its front toward `face`, its footprint centred on (x, y) and its
        bottom at z; `back` puts its back against that wall coordinate instead of centring on the facing axis."""
        if not eal.does_asset_exist(path):
            log.append("skip %s (not in this project)" % path)
            return None
        yaw = FACE[face] + _front(path) + yaw_extra
        asset = eal.load_asset(path)
        if isinstance(asset, unreal.StaticMesh):
            a = acs.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(yaw=yaw))
            a.static_mesh_component.set_static_mesh(asset)
        else:
            a = acs.spawn_actor_from_class(eal.load_blueprint_class(path), unreal.Vector(0, 0, 0), unreal.Rotator(yaw=yaw))
        if scale != 1.0:
            s = scale if isinstance(scale, tuple) else (scale, scale, scale)
            a.set_actor_scale3d(unreal.Vector(*s))
        o, e = a.get_actor_bounds(False, False)
        if back is not None:
            if face == "S":
                y = back - e.y
            elif face == "N":
                y = back + e.y
            elif face == "W":
                x = back - e.x
            else:
                x = back + e.x
        loc = a.get_actor_location()
        a.set_actor_location(unreal.Vector(loc.x + x - o.x, loc.y + y - o.y, loc.z + z - (o.z - e.z)), False, False)
        log.append("placed %s" % path)
        return tag(a, folder)

    def top(a, default=0.0):
        """The top of an actor placed with place() (default when it was skipped), to stand props on it."""
        if a is None:
            return default
        o, e = a.get_actor_bounds(False, False)
        return o.z + e.z

    def props(folder, z, items):
        """Small static props standing at height z: [(path, x, y[, face[, scale]]), ...]."""
        for it in items:
            place(it[0], folder, face=it[3] if len(it) > 3 else "S", x=it[1], y=it[2], z=z, scale=it[4] if len(it) > 4 else 1.0)

    try:
        if eal.does_asset_exist(level):
            ok = les.load_level(level)
        else:
            ok = les.new_level_from_template(level, "/Engine/Maps/Templates/Template_Default")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not ok or not world or world.get_outermost().get_name() != level:
            raise RuntimeError("could not open or create %s (a save prompt cancelled?); nothing changed" % level)
        world.get_world_settings().set_editor_property("default_game_mode", unreal.GameModeBase)
        for a in acs.get_all_level_actors():
            folder = str(a.get_folder_path())
            if folder.startswith("Showcase") or a.get_class().get_name() in ("StaticMeshActor",) and a.get_actor_label() == "Floor":
                acs.destroy_actor(a)
            elif isinstance(a, unreal.PlayerStart):
                # far behind every camera: GameModeBase's default pawn is a sphere
                a.set_actor_location(unreal.Vector(0.0, -4000.0, 100.0), False, False)
            elif isinstance(a, unreal.DirectionalLight):
                # high, from the open front and a little from the west, so the back wall's fronts are lit
                a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-50.0, yaw=96.0), False)
                a.get_component_by_class(unreal.DirectionalLightComponent).set_intensity(6.0)
            elif isinstance(a, unreal.SkyLight):
                a.get_component_by_class(unreal.SkyLightComponent).set_intensity(2.0)

        st = tag(acs.spawn_actor_from_class(unreal.RammsPhysicsSettings, unreal.Vector(0, 0, 0)), "Settings")
        st.set_editor_property("engine", {"chaos": unreal.RammsLevelPhysicsEngine.CHAOS, "mujoco": unreal.RammsLevelPhysicsEngine.MU_JO_CO}.get(str(opts.get("SC_ENGINE", "Chaos")).lower(), unreal.RammsLevelPhysicsEngine.AUTO))
        cl = unreal.Vector(0.0, -1500.0, 1000.0)
        sc = tag(acs.spawn_actor_from_class(unreal.SceneCapture2D, cl, unreal.MathLibrary.find_look_at_rotation(cl, unreal.Vector(0.0, 60.0, 40.0))), "Settings")
        sc.capture_component2d.set_editor_property("capture_every_frame", False)

        # --- shell: ground, porch, floors, walls -----------------------------------------------------------------
        floor(-2500.0, 2500.0, -2500.0, 2500.0, -6.0, mat("Mat.Lawn"), uv=400.0)
        floor(-760.0, 760.0, -600.0, -426.0, 0.0, mat("Mat.Concrete"))                       # porch
        floor(-706.0, 706.0, -426.0, 426.0, 0.0, mat("Mat.Floor.Wood"))
        floor(-694.0, -116.0, 40.0, 414.0, 0.4, mat("Mat.Floor.Tile"), uv=60.0)             # kitchen, island
        floor(-104.0, 119.0, 130.0, 414.0, 0.4, mat("Mat.Floor.Tile"), uv=60.0)             # laundry
        floor(131.0, 409.0, 136.0, 414.0, 0.4, mat("Mat.Floor.Tile"), uv=60.0)              # bathroom
        # back wall: kitchen, bathroom and bedroom windows
        wall(-706.0, 420.0, 706.0, 420.0, windows="329,200,135,222;986,70,165,222;1306,130,110,222")
        wall(-700.0, -426.0, -700.0, 426.0, windows="276,170,85,222")                         # west: dining window
        wall(700.0, -426.0, 700.0, 426.0, windows="576,120,90,222")                           # east: bedroom window
        wall(-110.0, 150.0, -110.0, 414.0)                                                    # kitchen | laundry
        wall(125.0, 130.0, 125.0, 414.0)                                                      # laundry | bathroom
        wall(125.0, 130.0, 415.0, 130.0, height=105.0)                                        # bathroom: a low front wall
        wall(415.0, -426.0, 415.0, 414.0, door=(466.0, 90.0))                                 # bedroom, door

        back = 414.0
        SM = HP + "Small_kitchen_props/"
        DP = HP + "Decorative_props/"
        FU = HP + "Furniture/"
        PA = HP + "Paintings/"
        BK = HP + "Books/"
        BA = HP + "Bathroom/"
        LA = HP + "Lamps/"
        KP = HP + "Kid_props/"
        CU = HP + "Curtains/"
        SRC = SR + "SM_SR_FC_kitchen_base_cabinet/SM_SR_FC_kitchen_base_cabinet"   # the base cabinet, static
        # --- kitchen: an L along the back and west walls, an island with stools, the sink under the window -----
        # Corner cabinets are static (their doors would hit the other leg); the fridge ends the west leg, 20 cm
        # from the next cabinet so its French doors can swing past 90 degrees. The island's articulated cabinets
        # face the back run across a 120 cm aisle, so facing doors that open together still clear each other.
        # (The wall cabinet's MJCF carries the patch of plaster it hangs on, floor to 250 cm, behind it.)
        place(SRC, "Kitchen", x=-664.0, back=back, z=0.4)
        corner = place(SRC, "Kitchen", x=-604.0, back=back, z=0.4)
        place(MJ + "sr_fc_range_oven", "Kitchen", x=-544.0, back=back, z=0.4)
        b1 = place(MJ + "sr_fc_kitchen_base_cabinet", "Kitchen", x=-484.0, back=back, z=0.4)
        b2 = place(MJ + "sr_fc_kitchen_base_cabinet", "Kitchen", x=-424.0, back=back, z=0.4)
        place(MJ + "sr_fc_kitchen_base_cabinet", "Kitchen", x=-364.0, back=back, z=0.4)
        sink = place(HP + "Cabinets_kitchen/SM_Kitchen_counter_sink", "Kitchen", x=-277.0, back=back, z=0.4, scale=(1.0, 1.0, 0.9))
        place(SR + "SM_SR_LG_dishwasher_ldfc2423v/SM_SR_LG_dishwasher_ldfc2423v", "Kitchen", x=-194.0, back=back, z=0.4)
        place(MJ + "sr_fc_pedal_trash_can", "Kitchen", x=-139.0, back=back, z=0.4)
        for wx in (-604.0, -484.0, -424.0):
            place(MJ + "sr_fc_kitchen_wall_cabinet", "Kitchen", x=wx, back=back, z=0.4)
        place(MJ + "sr_fc_microwave_oven", "Kitchen", x=-484.0, back=back - 4.0, z=top(b1, 91.2))
        leg = place(SRC, "Kitchen", face="E", back=-694.0, y=322.0, z=0.4)
        place(MJ + "sr_fc_kitchen_base_cabinet", "Kitchen", face="E", back=-694.0, y=261.0, z=0.4)
        place(MJ + "sr_fc_refrigerator", "Kitchen", face="E", back=-694.0, y=165.5, z=0.4)
        isl = None
        for ix in (-510.0, -450.0, -390.0):
            isl = place(MJ + "sr_fc_kitchen_base_cabinet", "Kitchen", face="N", x=ix, back=170.0, z=0.4)
            place(SRC, "Kitchen", face="S", x=ix, back=170.0, z=0.4)
            place(SR + "SM_SR_FC_gas_lift_bar_stool/SM_SR_FC_gas_lift_bar_stool", "Kitchen", face="N", x=ix, y=82.0, z=0.4)
        ct, it = top(corner, 91.2), top(isl, 91.2)
        props("Kitchen", ct, [(HP + "Electronics/SM_Coffeemaker_body", -592.0, 400.0), (SM + "SM_Coffee_mug", -625.0, 380.0)])
        props("Kitchen", top(leg, 91.2), [(SM + "SM_Kitchen_items_set_A", -680.0, 322.0, "E"), (SM + "SM_Teapot", -660.0, 262.0, "E")])
        props("Kitchen", ct + 1.3, [(SM + "SM_Cooking_pot", -556.0, 392.0), (SM + "SM_Frying_pan", -540.0, 370.0)])
        props("Kitchen", top(b2, 91.2), [(SM + "SM_Plate_pile", -430.0, 395.0), (SM + "SM_Jar_A", -403.0, 402.0), (SM + "SM_Jar_B", -388.0, 402.0)])
        props("Kitchen", ct, [(SM + "SM_Utensil_holder_full", -350.0, 400.0), (SM + "SM_Pepper_mill", -372.0, 404.0), (SM + "SM_Bottle_A", -380.0, 404.0)])
        props("Kitchen", ct, [(SM + "SM_Glass_drinking_pile", -217.0, 402.0), (SM + "SM_Macaroni_package", -330.0, 405.0)])
        props("Kitchen", it, [(DP + "SM_Decorative_bowl", -450.0, 170.0), (DP + "SM_Tulips_A", -515.0, 170.0), (SM + "SM_Bowl_cereal", -405.0, 130.0),
                              (SM + "SM_Coffee_mug", -380.0, 150.0), (SM + "SM_Coffee_mug", -470.0, 125.0), (BK + "SM_Book_single_A", -500.0, 125.0)])
        place(HP + "Electronics/SM_Clock_wall_analog", "Kitchen", back=back, x=-145.0, z=180.0)
        light(-420.0, 270.0)
        light(-450.0, 120.0, candela=20.0, radius=380.0)

        # --- breakfast nook by the west window, dining table, sideboard -----------------------------------------
        place(FF + "SM_Classic_Round_Table", "Dining", x=-575.0, y=-75.0)
        place(FU + "SM_Chair_dining", "Dining", face="N", x=-575.0, y=-162.0)
        place(FU + "SM_Chair_dining", "Dining", face="S", x=-575.0, y=12.0)
        place(FU + "SM_Chair_dining", "Dining", face="W", x=-488.0, y=-75.0)
        props("Dining", 76.5, [(SM + "SM_Coffee_mug", -560.0, -45.0), (SM + "SM_Bowl_cereal", -590.0, -100.0), (SM + "SM_Teapot", -600.0, -60.0),
                               (BK + "SM_Book_single_B", -540.0, -95.0)])
        place(CU + "SM_Curtain_A_rod_singlewindow", "Dining", face="E", back=-694.0, y=-65.0, z=230.0)
        place(CU + "SM_Curtain_A_L", "Dining", face="E", back=-694.0, y=-172.0, z=0.4)
        place(CU + "SM_Curtain_A_R", "Dining", face="E", back=-694.0, y=42.0, z=0.4)
        place(PA + "SM_Painting_small_A", "Dining", face="E", back=-694.0, y=78.0, z=135.0)
        light(-575.0, -75.0, candela=22.0, radius=380.0)

        place(DP + "SM_Carpet_C", "Dining", x=-330.0, y=-262.0, z=0.2)
        place(FF + "SM_Modern_Table", "Dining", x=-330.0, y=-262.0)
        for cx in (-380.0, -280.0):
            place(SR + "SM_SR_FC_dining_chair/SM_SR_FC_dining_chair", "Dining", face="S", x=cx, y=-187.0)
            place(SR + "SM_SR_FC_dining_chair/SM_SR_FC_dining_chair", "Dining", face="N", x=cx, y=-337.0)
            props("Dining", 78.0, [(SM + "SM_Plate_single", cx, -235.0), (SM + "SM_Plate_single", cx, -289.0),
                                   (SM + "SM_Glass_wine", cx + 22.0, -226.0), (SM + "SM_Glass_wine", cx - 22.0, -298.0)])
        props("Dining", 78.0, [(DP + "SM_Vase_A", -330.0, -262.0), (DP + "SM_Tulips_B", -330.0, -262.0), (DP + "SM_Candle_holder_A", -405.0, -262.0),
                               (DP + "SM_Candle_holder_B", -255.0, -262.0)])
        sb = place(FU + "SM_Sidetable_A", "Dining", face="E", back=-694.0, y=-300.0)
        props("Dining", top(sb, 83.6), [(DP + "SM_Vase_B_sticks", -680.0, -335.0, "E"), (DP + "SM_Decorative_plate", -688.0, -300.0, "E"),
                                        (DP + "SM_Candle_holder_A", -678.0, -265.0, "E")])
        place(PA + "SM_Painting_large_B", "Dining", face="E", back=-694.0, y=-300.0, z=140.0)
        place(DP + "SM_Plant_A", "Dining", x=-655.0, y=-395.0)
        light(-330.0, -262.0)

        # --- laundry --------------------------------------------------------------------------------------------
        place(MJ + "sr_fc_front_load_washer", "Laundry", x=-62.0, back=back, z=0.4)
        lg = place(SR + "SM_SR_LG_laundry_wm4000hwa/SM_SR_LG_laundry_wm4000hwa", "Laundry", x=28.0, back=back, z=0.4)
        place(HP + "Furniture/SM_Shelf", "Laundry", back=back, x=-17.0, z=150.0)
        props("Laundry", 165.4, [(SM + "SM_Bottle_A", -58.0, 402.0), (SM + "SM_Bottle_A", -48.0, 404.0), (BA + "SM_Bathroom_box_A", 0.0, 400.0),
                                 (BA + "SM_Shampoo_bottle_B", 22.0, 404.0)])
        props("Laundry", top(lg, 98.0), [(BA + "SM_Towel_pile", 28.0, 385.0)])
        place(BA + "SM_Laundrybasket", "Laundry", x=90.0, y=200.0, z=0.4)
        place(SR + "SM_SR_NV_bucket_mop_yellow_b01/SM_SR_NV_bucket_mop_yellow_b01", "Laundry", face="E", x=-75.0, y=200.0, z=0.4)
        place(SR + "SM_SR_NV_storage_basket_plastic_a01/SM_SR_NV_storage_basket_plastic_a01", "Laundry", x=30.0, y=190.0, z=0.4)
        place(KP + "SM_Poster_kid_B", "Laundry", face="W", back=119.0, y=300.0, z=130.0)
        light(5.0, 280.0, candela=30.0, radius=380.0)

        # --- bathroom -------------------------------------------------------------------------------------------
        van = place(MJ + "sr_fc_vanity_sink_faucet", "Bathroom", x=190.0, back=back, z=0.4)
        place(DP + "SM_Mirror_bathroom", "Bathroom", x=190.0, back=back, z=118.0, scale=0.55)
        props("Bathroom", 85.5, [(BA + "SM_Toothbrush_mug", 168.0, 402.0), (BA + "SM_Handsoap", 212.0, 404.0)])
        place(SR + "SM_SR_NV_toilet_a01/SM_SR_NV_toilet_a01", "Bathroom", x=270.0, back=back, z=0.4)
        place(BA + "SM_Toiletpaper_set", "Bathroom", x=236.0, y=398.0, z=0.4)
        place(FF + "SM_Bathtub", "Bathroom", face="W", back=409.0, y=322.0, z=0.4)
        place(BA + "SM_Towel_hanging_large", "Bathroom", face="E", back=131.0, y=300.0, z=120.0)
        bsh = place(BA + "SM_Bathroom_shelf_unit_A", "Bathroom", face="E", back=131.0, y=195.0, z=0.4)
        props("Bathroom", top(bsh, 110.0), [(BA + "SM_Towel_pile", 143.0, 195.0, "E", 0.55)])
        place(DP + "SM_Carpet_D", "Bathroom", x=225.0, y=262.0, z=0.6, scale=0.6)
        place(DP + "SM_Plant_B", "Bathroom", x=395.0, y=160.0, z=0.4)
        light(270.0, 280.0, candela=30.0, radius=380.0)
        tag(acs.spawn_actor_from_class(unreal.SphereReflectionCapture, unreal.Vector(250.0, 200.0, 150.0)), "Lights")  # the mirror

        # --- bedroom --------------------------------------------------------------------------------------------
        ch = place(MJ + "sr_fc_chest_of_drawers", "Bedroom", x=555.0, back=back)
        props("Bedroom", top(ch, 99.4), [(PA + "SM_Painting_table_A", 530.0, 402.0, "S"), (DP + "SM_Vase_A", 580.0, 400.0)])
        place(PA + "SM_Painting_medium_A", "Bedroom", face="S", back=back, x=548.0, z=140.0)
        place(HP + "Furniture/SM_Bed_king", "Bedroom", face="W", back=694.0, y=-170.0)
        for ny in (-322.0, -18.0):
            place(SR + "SM_SR_NV_table_bedside_b01/SM_SR_NV_table_bedside_b01", "Bedroom", face="W", back=694.0, y=ny)
            place(SR + "SM_SR_NV_lamp_table_bedside_a01/SM_SR_NV_lamp_table_bedside_a01", "Bedroom", x=670.0, y=ny, z=89.0)
        place(HP + "Electronics/SM_Clock_table_digital", "Bedroom", face="W", x=662.0, y=-346.0, z=89.0)
        place(PA + "SM_Painting_large_A", "Bedroom", face="W", back=694.0, y=-170.0, z=135.0)
        place(PA + "SM_Painting_large_C", "Bedroom", face="E", back=421.0, y=-200.0, z=135.0)
        place(DP + "SM_Carpet_D", "Bedroom", x=560.0, y=262.0, z=0.2)
        dk = place(FU + "SM_Workdesk", "Bedroom", face="E", back=421.0, y=250.0)
        place(FU + "SM_Chair_workdesk", "Bedroom", face="W", x=520.0, y=250.0)
        dz = top(dk, 72.5)
        place(SR + "SM_SR_LG_monitor_27gx790a/SM_SR_LG_monitor_27gx790a", "Bedroom", face="E", x=440.0, y=255.0, z=dz)
        place(SR + "SM_SR_FC_desk_lamp/SM_SR_FC_desk_lamp", "Bedroom", face="E", x=445.0, y=190.0, z=dz)
        props("Bedroom", dz, [(BK + "SM_Book_pile_A", 450.0, 312.0, "E"), (HP + "Office_props/SM_Pen_holder_with_pens", 445.0, 220.0, "E"),
                              (HP + "Office_props/SM_Papers_pile_A", 470.0, 290.0, "E"), (SM + "SM_Coffee_mug", 470.0, 205.0)])
        place(CU + "SM_Curtain_D_rod_singlewindow", "Bedroom", face="W", back=694.0, y=210.0, z=230.0)
        place(CU + "SM_Curtain_D_L", "Bedroom", face="W", back=694.0, y=128.0, z=56.0)
        place(CU + "SM_Curtain_D_R", "Bedroom", face="W", back=694.0, y=292.0, z=56.0)
        place(DP + "SM_Plant_B", "Bedroom", x=450.0, y=385.0)
        dr = place(FU + "SM_Dresser_B", "Bedroom", face="E", back=421.0, y=-5.0)
        drz = top(dr, 72.5)
        place(LA + "SM_Lamp_table_B", "Bedroom", x=442.0, y=-25.0, z=drz)
        place(LA + "SM_Lamp_table_B_shade", "Bedroom", x=442.0, y=-25.0, z=drz + 26.0)
        props("Bedroom", drz, [(BK + "SM_Book_pile_A", 445.0, 20.0, "E"), (DP + "SM_Candle_holder_B", 450.0, -2.0)])
        place(FU + "SM_Chair_arm", "Bedroom", face="W", x=625.0, y=70.0)
        place(FU + "SM_Pillow_B", "Bedroom", face="W", x=640.0, y=70.0, z=50.0)
        light(560.0, -120.0)
        light(560.0, 260.0, candela=25.0, radius=380.0)

        # --- living ---------------------------------------------------------------------------------------------
        place(DP + "SM_Carpet_A", "Living", x=250.0, y=-230.0, z=0.2)
        place(SR + "SM_SR_NV_sofa_soft_b02/SM_SR_NV_sofa_soft_b02", "Living", face="E", x=140.0, y=-230.0)
        cof = place(SR + "SM_SR_NV_furniture_table_coffee_low_a01/SM_SR_NV_furniture_table_coffee_low_a01", "Living", face="E", x=265.0, y=-230.0, z=0.4)
        props("Living", top(cof, 44.7), [(BK + "SM_Book_pile_A", 262.0, -190.0, "E"), (DP + "SM_Decorative_bowl", 268.0, -262.0),
                                         (HP + "Electronics/SM_TV_remote", 250.0, -228.0, "E"), (DP + "SM_Candle_holder_B", 280.0, -228.0)])
        place(SR + "SM_SR_LG_tv_oled77g6wua/SM_SR_LG_tv_oled77g6wua", "Living", face="W", back=409.0, y=-230.0, z=95.0)
        tvs = place(FU + "SM_Tv_stand", "Living", face="W", back=409.0, y=-230.0)
        props("Living", top(tvs, 50.9), [(PA + "SM_Painting_table_B", 392.0, -160.0, "W"), (DP + "SM_Vase_B_sticks", 390.0, -300.0, "W"),
                                         (BK + "SM_Books_C", 390.0, -275.0, "W")])
        place(FU + "SM_Bookshelf", "Living", face="W", back=409.0, y=-30.0)
        for bz in (45.0, 90.0, 135.0, 180.0):
            props("Living", bz, [(BK + "SM_Books_C", 388.0, -55.0, "W"), (BK + "SM_Books_D", 388.0, -5.0, "W")])
        place(PA + "SM_Painting_medium_C", "Living", face="W", back=409.0, y=-372.0, z=110.0)
        place(FF + "SM_Modern_Armchair", "Living", face="N", x=300.0, y=-380.0)
        place(HP + "Lamps/SM_Lamp_floor_A", "Living", x=60.0, y=-370.0)
        place(HP + "Lamps/SM_Lamp_floor_A_shade", "Living", x=60.0, y=-370.0, z=118.0)
        st_ = place(FU + "SM_Sidetable_C", "Living", x=140.0, y=-345.0)
        sz = top(st_, 53.7)
        place(LA + "SM_Lamp_table_A", "Living", x=140.0, y=-345.0, z=sz)
        place(LA + "SM_Lamp_table_A_shade", "Living", x=140.0, y=-345.0, z=sz + 27.0)
        con = place(FU + "SM_Sidetable_B", "Living", face="S", back=124.0, x=270.0)
        cz = top(con, 82.5)
        place(LA + "SM_Lamp_table_B", "Living", x=235.0, y=106.0, z=cz)
        place(LA + "SM_Lamp_table_B_shade", "Living", x=235.0, y=106.0, z=cz + 26.0)
        props("Living", cz, [(DP + "SM_Vase_A", 300.0, 106.0), (DP + "SM_Tulips_A", 300.0, 106.0), (PA + "SM_Painting_table_C", 270.0, 112.0, "S")])
        place(DP + "SM_Plant_A", "Living", x=-60.0, y=90.0)
        light(200.0, -200.0)
        # a play corner between the living and dining rooms
        place(KP + "SM_Toy_racetrack", "Living", x=-20.0, y=-330.0, z=0.2)
        place(KP + "SM_Toy_box_A", "Living", x=-75.0, y=-255.0)
        place(KP + "SM_Toy_block_set_A", "Living", x=10.0, y=-270.0)
        place(KP + "SM_Toy_teddy", "Living", face="S", x=55.0, y=-250.0)
        place(KP + "SM_Toy_truck", "Living", face="E", x=-40.0, y=-370.0)
        place(KP + "SM_Toy_car_A", "Living", face="E", x=20.0, y=-345.0)

        # --- porch ----------------------------------------------------------------------------------------------
        place(MJ + "sr_fc_wheelie_bin", "Porch", x=-590.0, y=-520.0)
        place(SR + "SM_SR_NV_container_recycle_blue_wheeled_a01/SM_SR_NV_container_recycle_blue_wheeled_a01", "Porch", x=-490.0, y=-520.0)
        place(SR + "SM_SR_FC_shipping_box/SM_SR_FC_shipping_box", "Porch", x=-370.0, y=-485.0, yaw_extra=8.0)
        bx = place(SR + "SM_SR_NV_box_cardboard_a01/SM_SR_NV_box_cardboard_a01", "Porch", x=-285.0, y=-495.0)
        place(SR + "SM_SR_FC_shipping_box/SM_SR_FC_shipping_box", "Porch", x=-290.0, y=-495.0, z=top(bx, 51.0), yaw_extra=-12.0)
        for px in (-160.0, 300.0, 700.0):
            place(DP + "SM_Plant_A", "Porch", x=px, y=-520.0)

        les.save_current_level()
        log.append("saved %s" % level)
    except Exception:
        import traceback
        log.append(traceback.format_exc())
    with open(os.path.join(out_dir, "showcase.log"), "w") as f:
        f.write("\n".join(log) + "\n")

_showcase(_SC)
del _showcase, _SC
