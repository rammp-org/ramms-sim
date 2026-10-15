"""Build the default palette from the Fab packs the project already has.

Slots are looked up by asset *name* through the asset registry, so a pack can
be moved under /Game/Fab without touching this file; a missing asset just
leaves its slot empty and is reported. Footprints and heights are read from
the mesh bounds so placement can keep clearances without loading meshes at
generation time.
"""

import unreal

from . import _helpers as H

DEFAULT_PALETTE = H.PALETTES + "/PAL_Default"
ENGINE_MAT = "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"

# slot -> list of static mesh asset names (any that exist are used, weight 1). Names come from the
# packs the project carries (MoStreetProps, Megascans, FreeFurniturePack, RestaurantScene,
# AmericanCityPacks, TownShops, CityBeachStrip, SuburbNeighborhoodHousePack); a missing pack just
# leaves fewer variants in a slot.
MESH_SLOTS = {
    # Curb: left empty on purpose - the Megascans curb pieces vary in length and leave gaps; the procedural
    # curb (continuous, world-aligned concrete) reads better. Add meshes here to switch back.
    "Curb": [],
    "SidewalkCorner": ["uiksdjydw_tier_2"],
    "Bench": ["SM_Bench01", "SM_Bench02", "SM_Bench03", "SM_bench_outdoor_01_rm"],
    "Bollard": ["SM_Bollard01B", "SM_Bollard01P", "SM_electric_bollard_metal"],
    "BusStop": ["SM_BusStop01", "SM_BusStop02", "SM_BusStation"],
    "StreetLight": ["SM_LampPost", "SM_Lamp_Street_High", "SM_StreetLight01", "SM_StreetLight02", "SM_light_pole_baytrail_01"],
    "Railing": ["SM_StreetRailing01", "SM_StreetRailing02"],
    "TrashBin": ["SM_streetBin", "SM_TrashCanClosed", "SM_Bin_01", "SM_Trashbin02", "SM_Trashbin01B", "SM_Trash_Container", "SM_garbage_bin_concrete_RM_01"],
    "InfoBoard": ["SM_InfoTable01", "SM_InfoTable02", "SM_InfoTable03"],
    "Hydrant": ["SM_hydrant", "SM_Fire_Hydrant"],
    "ParkingMeter": ["SM_ParkingMeter"],
    "NewspaperBox": ["SM_NewspaperBox"],
    "Mailbox": ["SM_Mailbox", "SM_Mailbox_01"],
    "StreetSign": ["SM_Sign_StopSign", "SM_Sign_NoParking01", "SM_Sign_SpeedLimit25", "SM_Sign_OneWay01", "SM_Sign_Residential", "SM_Stop_Sign", "SM_Street_Sign"],
    "UtilityPole": ["SM_PowerPole_Solo", "SM_UtilityPole"],
    "Car": ["SM_Car", "SM_veh07_car_sedan_parked", "SM_veh_03_car_parked", "SM_veh_05_car_suv_parked", "SM_veh_04_truck_parked"],
    "Flowerbed": ["SM_Flowerbed_Round", "SM_WoodPlanter01", "SM_WoodPlanter03", "SM_Pot04", "SM_Pot05"],
    "Fence": ["SM_Fence_Frontyard_Tile_Left_2x", "SM_Fence_Frontyard_Tile_Right_2x"],
    "Stairs": ["stairs_street"],
    "RoofUnit": ["SM_AC_Box", "SM_AC_Exaust", "SM_ac_01", "SM_ac_02"],
    # foliage
    # leafy trees only (the AmericanCityPacks SM_Tree1-3 are bare winter trees)
    "Tree": ["SM_BeechTree02", "SM_BeechTree03", "SM_MapleTree_Pivot", "SM_TreeLarge_Static", "SM_Alder_Desktop_Forest_modded_01_rep",
             "SM_Sycamore_American_Sapling_SF_rep", "SM_SF_Broadleaf_Desktop_Field_rep"],
    # big old street trees for canopy streets (the 300k-triangle oaks only when they are Nanite meshes)
    "TreeLarge": ["SM_SF_Broadleaf_Desktop_Field_rep", "SM_JacarandaTree", "SM_TreeLarge_Static", "SM_BeechTree03", "SM_MapleTree_Pivot",
                  "SM_Tree_Q_Rubra_Adult_vertcol_02", "SM_tree_Rubra_old_tall_01"],
    # lawn cover: low clumps (spawned at 60-130% scale), a few weeds
    "GrassClump": ["SM_Grass_Clump_01_1m", "SM_GrassClump02", "SM_grass_bermuda_01_main", "SM_grass_bermuda_02_main", "SM_Plant_Grass_Small",
                   "SM_grass_bermuda_01_weeds"],
    "Flowers": ["SM_Flowers01", "SM_Flowers02", "SM_Flowers03", "SM_Flower_Red_01", "SM_Flower_Red_02", "SM_Flower_Yellow_01", "SM_grass_bermuda_03_flower",
                "SM_Plant_FlowersRedBush"],
    "FoundationShrub": ["SM_shrub_03_a", "SM_shrub_03_b", "SM_shrub_03_c", "SM_shrub_03_d", "SM_Plant_Bush_A", "SM_Plant_Bush_B", "SM_Shrub01",
                        "SM_Hedge_Sphere", "SM_Plant_FlowersWhiteBush"],
    # door leaves with their handles; scaled to the opening
    "Door.Interior": ["SM_Door_interior", "SM_WoodenDoor1", "SM_OfficeDoor_01a", "SM_DoorSingleLeft_1", "SM_toiletwooddoor", "SM_Door_exterior_white",
                      "SM_Door_exterior_paneled"],
    "Door.Exterior": ["SM_Door_exterior_windowed", "SM_Door_exterior_windowed_brown", "SM_ExteriorDoor_01a", "SM_DoorMain"],
    "TreeSmall": ["SM_MyrtleTree01", "SM_MyrtleTree02", "SM_PrivetTree01", "SM_TreeSmall_Static"],
    "TreePit": ["SM_tree_grate_01", "SM_Tree_Grate"],
    "Shrub": ["SM_Shrub01", "SM_Shrub01_b", "SM_Plant_Bush_A", "SM_Plant_Bush_B", "SM_Plant_Treebush", "SM_Hedge_Sphere", "SM_Plant_FlowersRedBush", "SM_Plant_FlowersWhiteBush"],
    "Hedge": ["SM_Hedge_4m_Half", "SM_Hedge02_4m_Half", "SM_Hedge_4m"],
    # buildings
    "House": ["SM_Background_House_A", "SM_Background_House_B"],
    # hazards: things that end up in the access route
    "Hazard.Upheaval": ["adoquines_levantados_alcorque"],
    "Hazard.BinOut": ["SM_TrashCan_WithTrash_01", "SM_TrashCan_WithTrash_02", "SM_BinOpenedWithTrash", "SM_Trashbag", "SM_Trashbin01"],
    "Hazard.Barrier": ["SM_metallicBarrier", "SM_Roadblock_Wood_Roadblock_Woo", "SM_Roadblock_Concrete", "SM_StreetRailing01", "SM_barricade_metal_rm_01", "SM_construction_fence_orange_rm_01"],
    "Hazard.Cone": ["SM_RoadConstruction_cone_01", "SM_RoadConstruction_cone_02", "SM_RoadConstruction_cone_03"],
    "Hazard.AFrame": ["SM_InfoTable01", "SM_InfoTable02"],
    "Hazard.Cafe": ["SM_RestaurantTable", "SM_OutsideTable", "SM_GardenTable", "viejdi1_tier_2", "SM_Table"],
    "Hazard.CafeChair": ["SM_OutsideChair", "SM_GardenChair", "SM_PlasticChair", "SM_Chair"],
    "Hazard.Scooter": ["SM_Scooter"],
    "Hazard.Bike": ["SM_Bike"],
    "Hazard.Dumpster": ["SM_Dumpster", "SM_dumpster"],
    "Hazard.Box": ["SM_Cardboard_Closed_2", "SM_Cardboard_Closed_3", "SM_CardboardBox_01", "SM_CardboardBoxOpened_02"],
    # indoor
    "Furniture.Table": ["SM_Kitchen_table_large", "SM_Kitchen_table_rectangle", "SM_Kitchen_table_small", "SM_Table_dining", "SM_KitchenTable_01a", "SM_Table", "SM_Classic_Round_Table", "SM_Modern_Table"],
    "Furniture.Chair": ["SM_Kitchen_chair_fabric", "SM_Kitchen_chair_wooden", "SM_Chair_dining", "SM_KitchenChair_01a", "SM_Chair", "SM_Classic_chair", "SM_Modern_Chair_1", "SM_Old_Chair"],
    "Furniture.Sofa": ["SM_Couch_3seat", "SM_Couch_2seat", "SM_Couch", "SM_Sofa_01a", "SM_Sofa_02a", "SM_Classic_Leather_Sofa", "SM_Classic_Leather_sofa_2", "SM_Modern_Sofa_2"],
    "Furniture.Armchair": ["SM_Couch_1seat", "SM_Chair_arm", "SM_LoungeChair_01a", "SM_Chair_leather", "SM_Classic_Leather_Armchair", "SM_Modern_Armchair"],
    "Furniture.CoffeeTable": ["SM_Coffee_Table", "SM_Sidetable_small", "SM_Sidetable_C", "SM_CoffeeTable_01a"],
    "Furniture.Bed": ["SM_Bed_queen", "SM_Bed_small", "SM_Bed_king", "SM_Bed_single_person", "SM_Modern_Bed_1", "SM_Modern_Bed_2"],
    "Furniture.BedTable": ["SM_Sidetable_small", "SM_Nightstand_A", "SM_Nightstand_B", "SM_Bed_Table"],
    "Furniture.Cupboard": ["SM_Classic_Cupboard", "SM_Modern_Cupboard", "SM_Dresser_C", "SM_Dresser_large_A", "SM_Shelf_standing_A", "SM_Commode", "SM_Classic_Commode", "SM_Garage_shelf"],
    "Furniture.Bookshelf": ["SM_Book_set_bookshelf_A", "SM_Book_set_bookshelf_B", "SM_Bookshelf", "SM_BookShelf_01a"],
    "Furniture.Fireplace": ["SM_Fireplace_Single"],
    "Furniture.TVStand": ["SM_Sidetable_dark_large", "SM_Tv_stand", "SM_Commode", "SM_Classic_Commode_2"],
    "Furniture.TV": ["SM_TV_standing", "SM_TV", "SM_TVFlat_01a"],
    "Furniture.Desk": ["SM_Desk_office", "SM_Workdesk", "SM_Old_Table", "SM_Classic_table", "SM_Modern_Table"],
    "Furniture.OfficeChair": ["SM_Modern_Office_chair", "SM_Chair_office", "SM_OfficeChair_01a", "SM_OfficeChair02a"],
    "Furniture.Booth": ["SM_Booth"],
    "Furniture.Plant": ["SM_Plant_interior_yucca", "SM_Plant_interior_aglaonema", "SM_Plant_A", "SM_Plant_01a", "SM_PlantPot"],
    "Furniture.Lamp": ["SM_Lamp_table_A", "SM_Lamp_table_B", "SM_TableLamp_01a", "SM_Table_Lamp", "SM_Bed_lamp_3"],
    "Furniture.FloorLamp": ["SM_Lamp_standing"],
    "Furniture.Toilet": ["SM_Toilet"],
    "Furniture.Bathtub": ["SM_To_bathtub", "SM_Bathtub"],
    "Furniture.Appliance": ["SM_Washingmachine", "SM_Refrigerator_04a", "SM_Fridge_01a"],
    "Furniture.KitchenLow": ["SM_Kitcabinet_low_1x_A", "SM_Kitcabinet_low_1x_B", "SM_Kitcabinet_low_1halfx_A"],
    "Furniture.KitchenSink": ["SM_Kitcabinet_low_1halfx_sink"],
    "Furniture.KitchenStove": ["SM_Kitcabinet_low_1x_stove"],
    "Furniture.KitchenDishwasher": ["SM_Kitcabinet_low_1x_dishwasher", "SM_Dishwasher_01a"],
    "Furniture.KitchenUpper": ["SM_Kitcabinet_upper_1x_A", "SM_Kitcabinet_upper_1x_B"],
    "Furniture.KitchenTall": ["SM_Kitcabinet_full_fridge", "SM_Kitcabinet_full_cabinet", "SM_Fridge_01a", "SM_Refrigerator_04a", "SM_Refridgerator_05a"],
    "Furniture.OfficeStorage": ["SM_FilingCabinet01a", "SM_FilingCabinet01b", "SM_FilingCabinet01e", "SM_MetalShelf_100a", "SM_Shelf_standing_A", "SM_BookShelf_01a"],
    "Furniture.OfficeProp": ["SM_Printer_02a", "SM_WaterCooler_01b", "SM_VendingMachine_01a", "SM_StepLadder_01a", "SM_PaperBoxes_01a"],
    "Furniture.Whiteboard": ["SM_WhiteBoard_01a", "SM_NoticeBoard_01a", "SM_NoticeBoard_01e"],
    # retail (StorePropsCollection, GroceryProps)
    "Store.Shelf": ["SM_Shelving4", "SM_Shelving5", "SM_Shelving6", "SM_WoodenShelvings2"],
    "Store.Fridge": ["SM_Freezer3", "SM_Freezer4", "SM_Refrigerator1"],
    "Store.ChestFreezer": ["SM_StoreFreezer1", "SM_StoreFreezer2", "SM_CounterFreezer"],
    "Store.Counter": ["SM_Counter_3", "SM_Counter_4"],
    "Store.Register": ["SM_CashRegister"],
    "Store.Cart": ["SM_Cart1", "SM_Cart2", "SM_Cart3"],
    "Store.Display": ["SM_CardboardDisplay", "SM_NewsRack", "SM_Shelving7"],
    "Store.Product": ["SM_BoxedProduct00", "SM_BoxedProduct01", "SM_BoxedProduct03", "SM_BoxedProduct04", "SM_BoxedProduct05",
                      "SM_Can01Pack", "SM_Can02Pack", "SM_Can03Pack", "SM_Can04Pack", "SM_Jug1", "SM_Jug2", "SM_Jar01", "SM_Jar03",
                      "SM_PastaPack", "SM_RicePack", "SM_FlourPack", "SM_Snack_MorningCrunch", "SM_Snack_RunnersBacon",
                      "SM_Carton1", "SM_Carton2", "SM_DrinkCanBig_1", "SM_DrinkCanBig_3"],
    "Store.ProduceTable": ["SM_MetalTable"],
    "Store.Crate": ["SM_PlasticCrate"],
    "Store.Produce": ["SM_Apple1", "SM_Apple2", "SM_Apple3", "SM_Avocado", "SM_Banana1", "SM_Banana2", "SM_Carrot1", "SM_Carrot2", "SM_Corn1",
                      "SM_Cucumber1", "SM_Cucumber2", "SM_Garlic", "SM_Lemon", "SM_Lime", "SM_Onion", "SM_Orange", "SM_Pear", "SM_Pepper1", "SM_Pepper2",
                      "SM_Tomato1", "SM_Tomato2", "SM_Pumkin1"],
    "Store.DeliCase": ["SM_CounterFreezer", "SM_Icecreamfridge"],
    "Store.DeliItem": ["SM_odenmachine", "SM_sausagemachine_01", "SM_Cheese1", "SM_Bread1", "SM_Meat1"],
    "Store.Sign": ["SM_storebillboard"],
    "Store.ExitSign": ["SM_ExitSign1", "SM_ExitSign2"],
    "Store.Basket": ["SM_ShoppingBasket"],
    "Store.Clutter": ["SM_WoodenPallet", "SM_plasticcrate", "SM_WetFloorSign", "SM_CardboardBox_A", "SM_CardboardBox_B", "SM_Cardboard1", "SM_Box1",
                      "SM_box_01", "SM_cardbox", "SM_Bucket"],
    "Furniture.Picture": ["SM_Painting_A", "SM_Painting_B", "SM_Painting_C", "SM_Painting_E", "SM_Painting_F", "SM_Painting_large_A", "SM_Painting_wide_A", "SM_Mirror", "SM_Picture", "SM_Classic_Picture"],
    "Furniture.Clutter": ["SM_UtilityCart", "SM_Garage_plastic_box", "SM_Cardboard_Closed_3", "SM_To_laundrybasket", "SM_Old_Chair", "SM_WaterCooler_01b", "SM_Printer_02a", "SM_ShippingBoxes_01b", "SM_FilingCabinet01a", "SM_Laundrybasket"],
}

# Real-world heights (cm) a slot's meshes are normalised to when a pack models them at another
# scale (the FreeFurniturePack seating is ~15% large; a couple of chairs are armchair-sized).
# A mesh within 12% of the expected height is left alone; otherwise it is scaled uniformly.
SLOT_HEIGHTS = {
    "Furniture.Sofa": 86, "Furniture.Armchair": 90, "Furniture.Chair": 92, "Furniture.OfficeChair": 100,
    "Furniture.Table": 75, "Furniture.Desk": 75, "Furniture.CoffeeTable": 45, "Furniture.BedTable": 55,
    "Furniture.Bed": 95, "Furniture.Cupboard": 190, "Furniture.Bookshelf": 190, "Furniture.TVStand": 60,
    "Furniture.TV": 70, "Furniture.Toilet": 76, "Furniture.Bathtub": 60, "Furniture.Plant": 120,
    "Furniture.Lamp": 50, "Furniture.FloorLamp": 150, "Furniture.Booth": 110, "Furniture.Fireplace": 240,
    "Furniture.Appliance": 88, "Furniture.KitchenLow": 92, "Furniture.KitchenSink": 92, "Furniture.KitchenStove": 92,
    "Furniture.KitchenDishwasher": 92, "Furniture.KitchenUpper": 95, "Furniture.KitchenTall": 200,
    "Bench": 85, "TrashBin": 100, "Hydrant": 80, "ParkingMeter": 140, "NewspaperBox": 120, "Mailbox": 120,
    "Hazard.BinOut": 100, "Hazard.Cafe": 75, "Hazard.CafeChair": 90, "Hazard.Scooter": 115, "Hazard.Bike": 105,
    "Hazard.Cone": 75, "Hazard.Dumpster": 150, "Car": 150,
}
# Slots whose meshes keep their native size whatever the height (poles, trees, buildings, hedges).
NO_NORMALISE = {"TreeLarge", "GrassClump", "Flowers", "FoundationShrub", "Door.Interior", "Door.Exterior", "Store.ProduceTable", "Store.Crate",
                "Store.Produce", "Store.DeliCase", "Store.DeliItem", "Store.Sign", "Store.ExitSign", "Store.Basket", "Store.Clutter",
                "Tree", "TreeSmall", "Shrub", "Hedge", "House", "Car", "Store.Shelf", "Store.Fridge", "Store.ChestFreezer",
                "Store.Counter", "Store.Register", "Store.Cart", "Store.Display", "Store.Product", "StreetLight", "UtilityPole", "StreetSign", "BusStop",
                "Stairs", "Curb", "SidewalkCorner", "Railing", "Hazard.Upheaval", "Hazard.Barrier", "RoofUnit",
                "Flowerbed", "Fence", "TreePit", "Furniture.Picture", "Furniture.Clutter", "Furniture.OfficeProp", "Furniture.Whiteboard", "Furniture.OfficeStorage", "Hazard.Box", "Hazard.AFrame", "InfoBoard", "Bollard"}

# Meshes whose "front" the facing heuristic cannot tell (symmetric tops): yaw that turns the front to +X.
MESH_FACING = {
    "SM_TV": 0.0,
}

# Solid materials built from code when no pack provides them (name -> (rgb, roughness, metallic)).
SOLID_MATERIALS = {
    "M_RammsFoliage": ((0.07, 0.24, 0.05), 0.85, 0.0),
    "M_RammsTrunk": ((0.20, 0.13, 0.08), 0.9, 0.0),
    "M_RammsWarning": ((0.95, 0.70, 0.05), 0.75, 0.0),
    "M_RammsMarkingWhite": ((0.85, 0.85, 0.82), 0.6, 0.0),
    "M_RammsMarkingYellow": ((0.90, 0.72, 0.08), 0.6, 0.0),
    "M_RammsRoof": ((0.22, 0.22, 0.24), 0.95, 0.0),
    "M_RammsStorefront": ((0.10, 0.10, 0.12), 0.45, 0.6),
    "M_RammsTrim": ((0.62, 0.60, 0.56), 0.8, 0.0),
    "M_RammsTrimWhite": ((0.82, 0.81, 0.78), 0.45, 0.0),
}
MATERIALS_DIR = "/Game/WorldGen/Materials"

# slot -> list of material (instance) asset names, first that exists wins
MATERIAL_SLOTS = {
    "Mat.Asphalt": ["M_RammsAsphalt", "MI_rh0ribp0", "MI_sjfnbeaa", "MI_vizhdcz"],
    "Mat.Sidewalk": ["M_RammsSidewalk", "MI_ugxjcdpn", "MI_vmcxajwfw"],
    "Mat.Concrete": ["M_RammsConcrete", "MI_ugkjbgplw", "MI_vmcxajwfw"],
    "Mat.Cobble": ["MI_CobbleStone", "MI_tbjjai0s"],
    "Mat.Facade": ["M_RammsBrick", "MI_vizcegj"],
    "Mat.FacadeAlt": ["M_RammsSiding", "MI_ugtkdffg", "MI_vi4idbm"],
    "Mat.Curb": ["M_RammsCurb", "M_RammsConcrete"],
    "Mat.Trim.Interior": ["M_RammsTrimWhite"],
    "Mat.Glass": ["MI_Glass", "M_Glass", "MI_AdvancedGlass", "M_AdvancedGlass"],
    "Mat.Paint": ["M_RammsMarkingWhite"],
    "Mat.Marking": ["M_RammsMarkingWhite"],
    "Mat.MarkingYellow": ["M_RammsMarkingYellow"],
    "Mat.Warning": ["M_RammsWarning"],
    "Mat.Grass": ["M_RammsGrass", "MI_SFPark_grass_01_RM", "MI_pjwey0"],
    "Mat.Lawn": ["M_RammsLawn", "M_RammsGrass", "MI_SFPark_grass_01_RM", "MI_tkynejer"],
    "Mat.Path": ["M_RammsPath", "MI_vmcxajwfw", "MI_ugkjbgplw"],
    "Mat.Foliage": ["M_RammsFoliage"],
    "Mat.Trunk": ["M_RammsTrunk"],
    "Mat.Metal": ["MI_teeaccoc"],
    "Mat.Trim": ["M_RammsTrim"],
    "Mat.Roof": ["M_RammsRoof"],
    "Mat.Storefront": ["M_RammsStorefront"],
    "Mat.Floor.Wood": ["MI_ucklejqdy", "MI_ufeleiln", "MI_ugcwcevaw"],
    "Mat.Floor.Tile": ["MI_wfribhq", "MI_uenobapfw"],
    "Mat.Floor.Carpet": ["MI_umonbbqdy"],
    "Mat.Wall.Interior": ["MI_qj2luvs0", "MI_umridamn"],
    "Mat.Ceiling": ["MI_ufgnagwew", "MI_ugtmehro"],
    "Mat.Door": ["MI_vlznbajfw", "MI_ugcwcevaw"],
}

# slot -> material set (FRammsPaletteSlot::Materials): a node picks one per room / per decal. Names are
# looked up like MATERIAL_SLOTS; "MI_RammsPaint_*" expands to every paint instance surfaces.py made.
MATERIAL_SETS = {
    "Mat.Wall.Paint": ["MI_RammsPaint_*"],
    "Mat.Wall.Paper": ["M_RammsWallpaper", "M_RammsWallpaperDiamond", "M_RammsWallpaperFlowers", "M_RammsWallpaperRed"],
    "Mat.Wall.Tile": ["M_RammsWallTile", "M_RammsWallTile2"],
    "Mat.Floor.Wood": ["M_RammsFloorWood1", "M_RammsFloorWood2", "M_RammsFloorParquet", "M_RammsFloorHardwood"],
    "Mat.Floor.Carpet": ["M_RammsFloorCarpet1", "M_RammsFloorCarpet2", "M_RammsFloorCarpetOffice", "M_RammsFloorCarpetTiles"],
    "Mat.Floor.Tile": ["M_RammsFloorBath", "M_RammsFloorCeramic", "M_RammsFloorTiles", "M_RammsFloorMarble"],
    "Mat.Floor.Vinyl": ["M_RammsFloorPVC", "M_RammsFloorPVC2", "M_RammsFloorShop", "M_RammsFloorConcrete"],
    # projected decals (deferred-decal materials only; anything else is skipped)
    "Decal.Road.Crack": ["MI_AsphaltCrack", "MI_Crack01", "MI_Crack02", "MI_08_Asphalt_Crack_rmopsgp2_4K_RM", "MI_09_Asphalt_Crack_rmopfdp2_4K_RM"],
    "Decal.Road.Pothole": ["MI_Pothole01", "MI_Pothole02", "MI_Pothole03"],
    "Decal.Road.Patch": ["MI_ManholePatch", "MI_manhole_patch_dec_01_RM", "MI_manhole_patch_dec_03_RM", "MI_manhole_patch_tint_dec_02_RM",
                         "MI_16_Round_Manhole_Cover_scolskp_4K_RM", "MI_17_Round_Manhole_Cover_scomxop_4K_RM"],
    "Decal.Sidewalk.Crack": ["MI_Cracks_01", "MI_Cracks_02", "MI_Cracks_03", "MI_Cracks_04", "MI_Crack01", "MI_Crack02"],
    "Decal.Stain": ["MI_decal_overlay_grime_01_RM", "Mi_Stain_01a", "MI_Stains"],
    "Decal.Puddle": ["MI_AsphaltPuddle01", "MI_AsphaltPuddle02", "MI_Puddle01", "MI_RoadPuddle01", "MI_RoadPuddle02"],
}

ACTOR_SLOTS = {
    "DoorActor": "/Game/ada_door/BP_Moving_Door.BP_Moving_Door_C",
}

# slot -> blueprint classes whose child-actor static meshes are captured as one composite entry
# (Residential Houses - Modular Pack assembles each house from ~300 child actors; spawned as ISM
# instances they cost nothing). The front is taken from the porch / front door parts.
COMPOSITE_SLOTS = {
    "House": ["/Game/ResidentialHouses/Blueprints/Houses/NoInteriors/House%02d.House%02d_C" % (n, n) for n in range(1, 13)],
}
COMPOSITE_FRONT_HINTS = ("Porch", "FrontDoor", "Front_Door", "SM_Door", "Steps")


def _pick_front(named, cx, cy, ex, ey):
    """Yaw that turns a composite house's front door to +X.

    These houses have a front and a back entrance, each with a porch, so averaging porch parts lands near
    the middle. Score every entrance door instead: the wide front door (Outside_Door_2_4m, FrontDoor...)
    counts for it, a *_Back frame against it, nearby porch parts and a garage door on the same side add a
    little. named: [(mesh name, x, y, zmin)] relative to the capture origin.
    Returns (yaw, (door x, y, zmin) or None)."""
    def near(x, y, keys, r):
        return sum(1 for n, px, py, _z in named if any(k in n for k in keys) and abs(px - x) < r and abs(py - y) < r)

    def side(x, y):
        fx, fy = x - cx, y - cy
        if abs(fx) / max(ex, 1.0) >= abs(fy) / max(ey, 1.0):
            return 0.0 if fx > 0 else 180.0
        return -90.0 if fy > 0 else 90.0

    doors = [(px, py, pz) for n, px, py, pz in named if "EntranceDoor" in n]
    if not doors:
        doors = [(px, py, pz) for n, px, py, pz in named if any(h.lower() in n.lower() for h in COMPOSITE_FRONT_HINTS)]
    if not doors:
        return 0.0, None
    garages = [side(px, py) for n, px, py, _z in named if "GarageDoor" in n]
    best, best_score, best_door = None, -1e9, None
    for x, y, z in doors:
        sc = 5.0 * near(x, y, ("Door_2_4m", "FrontDoor", "Front_Door"), 200.0)
        sc -= 10.0 * near(x, y, ("_Back",), 150.0)
        sc += 0.3 * near(x, y, ("Porch",), 700.0)
        sd = side(x, y)
        # The porch stairs stand in front of the door: their direction from it is the front, which is
        # more reliable than which bounds side the door is nearest (doors sit near corners).
        st = [(px, py) for n, px, py, _z in named if "Stairs" in n and abs(px - x) < 600.0 and abs(py - y) < 600.0]
        if st:
            sx, sy = min(st, key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
            if abs(sx - x) >= abs(sy - y):
                sd = 0.0 if sx > x else 180.0
            else:
                sd = -90.0 if sy > y else 90.0
        sc += 2.0 * garages.count(sd)
        if sc > best_score:
            best, best_score, best_door = sd, sc, (x, y, z)
    return best, best_door

# --- facade module kits (AmericanCityPacks) ------------------------------------------------
# Module meshes are found by name pattern: SM_<style>_GroundFloor_L<n>T<t>[_door|_noDoor]_piece,
# SM_<style>_windows[Top]_L<n>T<t>_piece, SM_<style>_corner_L1T<t>_piece, SM_01_top_L<n> ... Each
# becomes an entry of "Facade.<style>.<Part>" with its material slot categories recorded, so the
# massing node can tile a facade and override every slot from one set of picks per building.
import re as _re

FACADE_PATTERNS = [
    # (part, regex with a 'style' group; corners are only the L1 pieces)
    ("GFDoor", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_[Gg]roundFloor_L\d+T\d+_door_piece$")),
    ("GF", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_[Gg]roundFloor_L\d+T\d+(_noDoor)?_piece$")),
    ("GFCorner", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_GroundFloorCorner_L1T\d+_piece$")),
    ("WinTop", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_windowsTop_L\d+T\d+_piece$")),
    ("Win", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_windows_L\d+T\d+_piece$")),
    ("WinCorner", _re.compile(r"^SM_(?P<style>[a-z]+\d+)_corner_L1T\d+_piece$")),
]
FACADE_GENERIC = {
    "Facade.WinCorner": _re.compile(r"^SM_01_corner_L1T\d+_piece$"),
    "Facade.Top": _re.compile(r"^SM_01_top_L\d$"),
    "Facade.TopCorner": _re.compile(r"^SM_01_top_corner_L1$"),
    "Facade.TallTop": _re.compile(r"^SM_01_TallTop_L\d$"),
    "Facade.TallTopCorner": _re.compile(r"^SM_01_TallTop_Corner_L1$"),
}
# mesh material slot name (lower-cased) -> category; a slot not listed falls back to the bricks.
FACADE_SLOT_CATEGORIES = {
    "facade": "Bricks", "facade2": "Bricks", "facade3": "Bricks2",
    "glass": "Windows", "glassnocurtains": "WindowsNoCurtain",
    "shopglass": "Shop", "glassfake": "Shop",
    "window": "Frame", "windows": "Frame", "black": "Frame", "framewindow": "Frame",
    "concrete": "Concrete", "ornaments": "Ornament", "border": "Border",
    "metal": "Metal", "metallic": "Metal", "metallic2": "Metal", "roof": "Roof", "door": "Door",
}
# category -> (asset folder, name filter) for the material sets
FACADE_MATERIAL_SETS = {
    "Bricks": ("/Game/AmericanCityPacks/Materials/Bricks", _re.compile(r"^MI_(bricks_|BrownBricks)")),
    # ground-floor panels (slot facade3): the regular bricks read at the right size; the pack's own
    # "F" bricks come out as 4x-size blocks on these UVs
    "Bricks2": ("/Game/AmericanCityPacks/Materials/Bricks", _re.compile(r"^MI_(bricks_|BrownBricks)")),
    # mostly bare glass; the curtained variants light up white in full sun
    "Windows": ("/Game/AmericanCityPacks/Materials/Windows", _re.compile(r"^MI_(3?windows_\d+|3?windows_NoCurtain_\d+|SbWindows_NoCurtain_\d+)$")),
    "WindowsNoCurtain": ("/Game/AmericanCityPacks/Materials/Windows/NoCurtains", _re.compile(r"^MI_(3?windows|SbWindows)_NoCurtain_\d+$")),
    # the pack's fake-interior shop glass renders as an opaque brick box here (no reflection capture, no VT):
    # plain glass over the dark shell reads as a shop front instead
    "Shop": ("/Game/AmericanCityPacks/Materials", _re.compile(r"^MI_Glass_0\d$")),
    "Frame": ("/Game/AmericanCityPacks/Materials/Simple", _re.compile(r"^MI_simple_")),
    "Concrete": ("/Game/AmericanCityPacks/Materials/Concrete", _re.compile(r"^MI_concrete_")),
    "Ornament": ("/Game/AmericanCityPacks/Materials/Ornaments", _re.compile(r"^MI_ornament_")),
    "Border": ("/Game/AmericanCityPacks/Materials/Ornaments", _re.compile(r"^MI_Ornaments_border_")),
    "Metal": ("/Game/AmericanCityPacks/Materials/Metal", _re.compile(r"^MI_metal_")),
    "Roof": ("/Game/AmericanCityPacks/Materials/Roof", _re.compile(r"^MI_RoofPlaster_")),
    "Door": ("/Game/AmericanCityPacks/Materials/Props", _re.compile(r"^MI_Door")),
}


def _module_entry(mesh):
    """Palette entry for a facade module: native pivot (start of run, base on the ground), no facing fix."""
    bounds = mesh.get_bounds()
    ext = bounds.box_extent
    e = unreal.RammsPaletteMesh()
    e.set_editor_property("mesh", mesh)
    e.set_editor_property("weight", 1.0)
    e.set_editor_property("scale", 1.0)
    e.set_editor_property("footprint", unreal.Vector2D(max(ext.x * 2.0, 1.0), max(ext.y * 2.0, 1.0)))
    e.set_editor_property("height", max(ext.z * 2.0, 1.0))
    e.set_editor_property("rotation_offset", unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
    e.set_editor_property("location_offset", unreal.Vector(0.0, 0.0, 0.0))
    cats = []
    for sm in mesh.get_editor_property("static_materials"):
        cats.append(FACADE_SLOT_CATEGORIES.get(str(sm.material_slot_name).lower(), "Default"))
    e.set_editor_property("material_slots", cats)
    return e


def build_facade_slots(pal, report):
    """Fill Facade.* slots from whatever facade kits the registry holds."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    counts = {}
    for ad in reg.get_assets_by_path("/Game/AmericanCityPacks/Geometry", recursive=True):
        if str(ad.asset_class_path.asset_name) != "StaticMesh":
            continue
        name = str(ad.asset_name)
        if name.endswith("_INT"):
            continue
        slot = None
        for part, rx in FACADE_PATTERNS:
            m = rx.match(name)
            if m:
                slot = "Facade.%s.%s" % (m.group("style"), part)
                break
        if slot is None:
            for generic, rx in FACADE_GENERIC.items():
                if rx.match(name):
                    slot = generic
                    break
        if slot is None:
            continue
        mesh = ad.get_asset()
        if mesh is None:
            continue
        pal.add_mesh(slot, _module_entry(mesh))
        counts[slot] = counts.get(slot, 0) + 1
    for cat, (folder, rx) in FACADE_MATERIAL_SETS.items():
        n = 0
        for ad in reg.get_assets_by_path(folder, recursive=True):
            if str(ad.asset_class_path.asset_name) not in ("MaterialInstanceConstant", "Material"):
                continue
            if not rx.match(str(ad.asset_name)):
                continue
            mat = ad.get_asset()
            if mat is None:
                continue
            pal.add_material("Facade.Mat." + cat, mat)
            n += 1
        counts["Facade.Mat." + cat] = n
    report["facade"] = counts
    return counts


def _registry_index():
    """name -> asset data for every StaticMesh and MaterialInterface under /Game."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    index = {}
    for ad in reg.get_assets_by_path("/Game", recursive=True):
        cls = str(ad.asset_class_path.asset_name)
        if cls in ("StaticMesh", "MaterialInstanceConstant", "Material"):
            index.setdefault(str(ad.asset_name), []).append(ad)
    return index


def _vertex_positions(mesh):
    """Vertex positions of LOD0 in mesh space via GeometryScript, or None when that is unavailable."""
    try:
        dm = unreal.DynamicMesh()
        opts = unreal.GeometryScriptCopyMeshFromAssetOptions()
        lod = unreal.GeometryScriptMeshReadLOD()
        res = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(mesh, dm, opts, lod)
        dm = res[0] if isinstance(res, tuple) else res
        res = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
        # Python returns the out-params: (target_mesh, position_list, has_gaps) or (position_list, has_gaps).
        vlist = next(v for v in (res if isinstance(res, tuple) else (res,)) if isinstance(v, unreal.GeometryScriptVectorList))
        arr = unreal.GeometryScript_List.convert_vector_list_to_array(vlist)
        return [(v.x, v.y, v.z) for v in arr]
    except Exception as exc:  # noqa: BLE001 - any failure just means "no facing info"
        H.warn("facing: no vertices for %s (%s)" % (mesh.get_name(), exc))
        return None


# slot -> which local axis the mesh's long side should end up on: "x" = along the facing direction
# (vehicles), "y" = across it (shelving, counters, freezers: their front is a long face).
LONG_AXIS_SLOTS = {"Car": "x", "Hedge": "y", "Fence": "y", "Store.Shelf": "y", "Store.Fridge": "y", "Store.ChestFreezer": "y", "Store.Counter": "y",
                   "Door.Interior": "y", "Door.Exterior": "y", "Store.DeliCase": "y", "Store.ProduceTable": "y", "Store.Sign": "y", "Store.ExitSign": "y"}


def _facing_yaw(mesh, bounds, slot=""):
    """
    Yaw (degrees) that turns the mesh's front to +X. Seating, beds and toilets carry their mass high
    at the back (backrest, headboard, cistern), so the front is opposite the side where the upper
    vertices gather; symmetric pieces (tables, cupboards) get 0. Explicit MESH_FACING entries win.
    """
    name = mesh.get_name()
    if name in MESH_FACING:
        return MESH_FACING[name]
    if slot in LONG_AXIS_SLOTS:
        # Only the axis matters here (which end is the nose / the front face is not decidable from bounds).
        ex, ey = bounds.box_extent.x, bounds.box_extent.y
        if slot == "Store.Shelf":
            # Shelving has a full-height back panel at one end of its short axis: more vertices sit in a thin
            # band there than at the open front (board lips, feet). The front is the other end.
            verts = _vertex_positions(mesh)
            if verts:
                k = 0 if ex <= ey else 1
                cs = [v[k] for v in verts]
                lo, hi = min(cs), max(cs)
                n_lo = sum(1 for c in cs if c - lo < 3.0)
                n_hi = sum(1 for c in cs if hi - c < 3.0)
                if n_lo != n_hi:
                    back_hi = n_hi > n_lo
                    if k == 0:
                        return 180.0 if back_hi else 0.0
                    return 90.0 if back_hi else -90.0
        if LONG_AXIS_SLOTS[slot] == "x":
            return 90.0 if ey > ex else 0.0
        return 90.0 if ex > ey else 0.0
    verts = _vertex_positions(mesh)
    if not verts or len(verts) < 12:
        return 0.0
    ext = bounds.box_extent
    org = bounds.origin
    zlo = org.z - ext.z
    top = [v for v in verts if v[2] > zlo + ext.z * 2.0 * 0.5]
    if len(verts) - len(top) < 4 or len(top) < 4:
        return 0.0
    mx = sum(v[0] for v in top) / len(top) - org.x
    my = sum(v[1] for v in top) / len(top) - org.y
    nx = mx / max(ext.x, 1.0)
    ny = my / max(ext.y, 1.0)
    if max(abs(nx), abs(ny)) < 0.12:
        return 0.0
    # Back is where the high vertices are; front is the opposite axis direction.
    if abs(nx) >= abs(ny):
        front = (-1.0, 0.0) if nx > 0 else (1.0, 0.0)
    else:
        front = (0.0, -1.0) if ny > 0 else (0.0, 1.0)
    import math
    return -math.degrees(math.atan2(front[1], front[0]))


def _shelf_heights(mesh, scale):
    """Heights of horizontal boards in a shelving mesh: z levels where many vertices cluster.

    Vertices are binned at 1.5 cm, bins closer than 4.5 cm are merged into one cluster (a board's top,
    bottom and lip), and a cluster that holds at least 4% of all vertices is a board. The plinth and the
    top cap (within 10 cm of either end) are not shelves. Low-poly store meshes have few bins, so the
    threshold is relative to the vertex count, not to the average bin."""
    verts = _vertex_positions(mesh)
    if not verts:
        return []
    zmin = min(v[2] for v in verts)
    zmax = max(v[2] for v in verts)
    bins = {}
    for v in verts:
        b = int(round((v[2] - zmin) / 1.5))
        bins[b] = bins.get(b, 0) + 1
    clusters = []  # [z_lo, z_hi, count]
    for b in sorted(bins):
        z = b * 1.5
        if clusters and z - clusters[-1][1] <= 4.5:
            clusters[-1][1] = z
            clusters[-1][2] += bins[b]
        else:
            clusters.append([z, z, bins[b]])
    need = max(3, 0.04 * len(verts))
    levels = [c[1] for c in clusters if c[2] >= need and c[0] > 10.0 and c[1] < (zmax - zmin) - 10.0]
    return [round(z * scale, 1) for z in levels]


HEAVY_OK_IF_NANITE = {"TreeLarge"}
TREE_SLOTS = {"Tree", "TreeSmall", "TreeLarge"}
DOOR_SLOTS = {"Door.Interior", "Door.Exterior"}


def _nanite(mesh):
    try:
        return bool(mesh.get_editor_property("nanite_settings").get_editor_property("enabled"))
    except Exception:  # noqa: BLE001
        return False


def _is_decal(mat):
    try:
        base = mat.get_base_material()
        return base.get_editor_property("material_domain") == unreal.MaterialDomain.MD_DEFERRED_DECAL
    except Exception:  # noqa: BLE001
        return False


def _trunk_xy(mesh):
    """Mesh-space XY of a tree's trunk: the centroid of the vertices in the lowest 60 cm (the canopy's
    bounds centre is often a metre or more off the trunk)."""
    verts = _vertex_positions(mesh)
    if not verts:
        return None
    zmin = min(v[2] for v in verts)
    low = [v for v in verts if v[2] < zmin + 60.0]
    if len(low) < 3:
        return None
    return (sum(v[0] for v in low) / len(low), sum(v[1] for v in low) / len(low))


def _handle_side(mesh, yaw):
    """+1 / -1: which end of the facing-frame Y axis of a door leaf carries the handle (vertex-dense hardware
    at 85-120 cm near one edge); 0 when it cannot tell."""
    import math
    verts = _vertex_positions(mesh)
    if not verts:
        return 0.0
    zmin = min(v[2] for v in verts)
    r = math.radians(yaw)
    ys = [v[0] * math.sin(r) + v[1] * math.cos(r) for v in verts]
    ylo, yhi = min(ys), max(ys)
    w = max(yhi - ylo, 1.0)
    pos = neg = 0
    for v, y in zip(verts, ys):
        if 85.0 <= v[2] - zmin <= 120.0:
            if y > yhi - 0.25 * w:
                pos += 1
            elif y < ylo + 0.25 * w:
                neg += 1
    if pos == neg:
        return 0.0
    return 1.0 if pos > neg else -1.0


def _mesh_entry(mesh, slot=""):
    import math
    bounds = mesh.get_bounds()
    ext = bounds.box_extent
    origin = bounds.origin
    yaw = _facing_yaw(mesh, bounds, slot)
    e = unreal.RammsPaletteMesh()
    e.set_editor_property("mesh", mesh)
    e.set_editor_property("weight", 1.0)
    scale = 1.0
    expected = SLOT_HEIGHTS.get(slot)
    if expected and slot not in NO_NORMALISE and ext.z > 1.0:
        ratio = expected / (ext.z * 2.0)
        if abs(ratio - 1.0) > 0.12:
            scale = max(0.5, min(1.6, ratio))
    e.set_editor_property("scale", scale)
    ext = unreal.Vector(ext.x * scale, ext.y * scale, ext.z * scale)
    origin = unreal.Vector(origin.x * scale, origin.y * scale, origin.z * scale)
    # Footprint and pivot offset are stored in the facing frame (front = +X), so a node can treat every
    # mesh as "depth fx along its front, width fy across" and set the yaw it wants.
    swap = abs(abs(yaw) % 180.0 - 90.0) < 1.0
    fx, fy = (ext.y, ext.x) if swap else (ext.x, ext.y)
    e.set_editor_property("footprint", unreal.Vector2D(max(fx * 2.0, 1.0), max(fy * 2.0, 1.0)))
    e.set_editor_property("height", max(ext.z * 2.0, 1.0))
    e.set_editor_property("rotation_offset", unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
    # Put the mesh's bounds centre on the requested point and its lowest point on the ground.
    r = math.radians(yaw)
    ox = origin.x * math.cos(r) - origin.y * math.sin(r)
    oy = origin.x * math.sin(r) + origin.y * math.cos(r)
    base_z = origin.z - ext.z
    if slot in TREE_SLOTS:
        # Put the trunk, not the canopy's centre, on the requested point (tree pits, planting strips).
        t = _trunk_xy(mesh)
        if t is not None:
            tx, ty = t[0] * scale, t[1] * scale
            ox = tx * math.cos(r) - ty * math.sin(r)
            oy = tx * math.sin(r) + ty * math.cos(r)
    e.set_editor_property("location_offset", unreal.Vector(-ox, -oy, -base_z))
    if slot in DOOR_SLOTS:
        try:
            e.set_editor_property("handle_side", _handle_side(mesh, yaw))
        except Exception as exc:  # noqa: BLE001
            H.warn("handle side for %s: %s" % (mesh.get_name(), exc))
    if slot == "Store.Shelf":
        try:
            e.set_editor_property("shelf_heights", _shelf_heights(mesh, scale))
        except Exception as exc:  # noqa: BLE001
            H.warn("shelf heights for %s: %s" % (mesh.get_name(), exc))
    return e


def _composite_entry(cls_path, slot=""):
    """Spawn the blueprint once, capture every child static mesh as a part, measure and face it."""
    import math
    cls = unreal.load_class(None, cls_path)
    if cls is None:
        return None
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    base = unreal.Vector(0.0, 0.0, 50000.0)
    actor = eas.spawn_actor_from_class(cls, base)
    if actor is None:
        return None
    parts = []
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    named = []
    garage_doors = []
    try:
        owners = []
        for c in actor.get_components_by_class(unreal.ChildActorComponent):
            child = c.get_editor_property("child_actor")
            if child is not None:
                owners.append(child)
        owners.append(actor)
        # Stray parts far from the house (a road piece, a backdrop) would inflate the footprint: keep
        # the cluster around the median part position.
        measured = []
        for owner in owners:
            smcs = [c for c in owner.get_components_by_class(unreal.StaticMeshComponent) if c.get_editor_property("static_mesh") is not None]
            if not smcs:
                continue
            bo, be = owner.get_actor_bounds(False, False)
            if be.x < 1.0 and be.y < 1.0:
                continue
            measured.append((owner, smcs, bo, be))
        xs = sorted(m[2].x for m in measured); ys = sorted(m[2].y for m in measured)
        mx, my = (xs[len(xs) // 2], ys[len(ys) // 2]) if xs else (base.x, base.y)
        for owner, smcs, bo, be in measured:
            if abs(bo.x - mx) > 2500.0 or abs(bo.y - my) > 2500.0:
                continue
            lo = [min(lo[0], bo.x - be.x - base.x), min(lo[1], bo.y - be.y - base.y), min(lo[2], bo.z - be.z - base.z)]
            hi = [max(hi[0], bo.x + be.x - base.x), max(hi[1], bo.y + be.y - base.y), max(hi[2], bo.z + be.z - base.z)]
            for smc in smcs:
                mesh = smc.get_editor_property("static_mesh")
                loc = smc.get_world_location()
                rel = unreal.Transform(unreal.Vector(loc.x - base.x, loc.y - base.y, loc.z - base.z), smc.get_world_rotation(), smc.get_world_scale())
                part = unreal.RammsPalettePart()
                part.set_editor_property("mesh", mesh)
                part.set_editor_property("relative_transform", rel)
                mats = [smc.get_material(i) for i in range(smc.get_num_materials())]
                part.set_editor_property("materials", mats if mats and all(m is not None for m in mats) else [])
                parts.append(part)
                co, _ce, _r = unreal.SystemLibrary.get_component_bounds(smc)
                named.append((mesh.get_name(), co.x - base.x, co.y - base.y, co.z - _ce.z - base.z))
                if "GarageDoor_Closed" in mesh.get_name():
                    garage_doors.append((co.x - base.x, co.y - base.y, _ce.x, _ce.y))
    finally:
        eas.destroy_actor(actor)
    if not parts or lo[0] > hi[0]:
        H.warn("composite %s: no parts" % cls_path)
        return None
    cx, cy = (lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5
    ex, ey, ez = (hi[0] - lo[0]) * 0.5, (hi[1] - lo[1]) * 0.5, (hi[2] - lo[2]) * 0.5
    yaw, door = _pick_front(named, cx, cy, ex, ey)
    e = unreal.RammsPaletteMesh()
    e.set_editor_property("weight", 1.0)
    e.set_editor_property("scale", 1.0)
    e.set_editor_property("parts", parts)
    swap = abs(abs(yaw) % 180.0 - 90.0) < 1.0
    fx_, fy_ = (ey, ex) if swap else (ex, ey)
    e.set_editor_property("footprint", unreal.Vector2D(max(fx_ * 2.0, 1.0), max(fy_ * 2.0, 1.0)))
    e.set_editor_property("height", max(ez * 2.0, 1.0))
    e.set_editor_property("rotation_offset", unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
    r = math.radians(yaw)
    ox = cx * math.cos(r) - cy * math.sin(r)
    oy = cx * math.sin(r) + cy * math.cos(r)
    e.set_editor_property("location_offset", unreal.Vector(-ox, -oy, -lo[2]))
    if door is not None:
        dx, dy = door[0] - cx, door[1] - cy
        e.set_editor_property("entrance_offset_y", dx * math.sin(r) + dy * math.cos(r))
        e.set_editor_property("entrance_rise", max(0.0, door[2] - lo[2]))
    for gx, gy, gex, gey in garage_doors:
        dx, dy = gx - cx, gy - cy
        lx = dx * math.cos(r) - dy * math.sin(r)
        ly = dx * math.sin(r) + dy * math.cos(r)
        if lx > fx_ * 0.25:  # on the front half: the garage opens toward the street
            wide = max(gex, gey)  # the door is thin: its long extent is its width
            e.set_editor_property("garage_door", unreal.Vector2D(lx, ly))
            e.set_editor_property("garage_width", wide * 2.0)
            break
    H.log("composite %s: %d parts, footprint %.0fx%.0f h %.0f yaw %.0f" % (cls_path.rsplit("/", 1)[-1], len(parts), fx_ * 2, fy_ * 2, ez * 2, yaw))
    return e


def _ensure_solid_material(name, rgb, roughness, metallic):
    """A one-colour material asset under /Game/WorldGen/Materials, created once."""
    path = MATERIALS_DIR + "/" + name
    if H.EAL.does_asset_exist(path):
        return H.EAL.load_asset(path)
    H.ensure_dir(MATERIALS_DIR)
    mat = H.asset_tools().create_asset(name, MATERIALS_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        return None
    mel = unreal.MaterialEditingLibrary
    colour = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -350, 0)
    colour.set_editor_property("constant", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
    mel.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -350, 200)
    rough.set_editor_property("r", roughness)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    metal = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -350, 300)
    metal.set_editor_property("r", metallic)
    mel.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)
    mel.recompile_material(mat)
    H.save(mat)
    return mat


def build_default_palette(path=DEFAULT_PALETTE):
    """Create or refresh the default palette. Returns (palette, report dict)."""
    for name, (rgb, rough, metal) in SOLID_MATERIALS.items():
        _ensure_solid_material(name, rgb, rough, metal)
    from . import surfaces
    surfaces.build_surfaces()
    index = _registry_index()
    pal, _ = H.get_or_create(path, unreal.RammsWorldPalette)
    pal.set_editor_property("slots", {})
    pal.set_editor_property("default_material", unreal.load_asset(ENGINE_MAT))
    report = {"meshes": {}, "materials": {}, "missing": []}

    for slot, names in MESH_SLOTS.items():
        found = []
        for n in names:
            for ad in index.get(n, []):
                if str(ad.asset_class_path.asset_name) != "StaticMesh":
                    continue
                mesh = ad.get_asset()
                if mesh is None:
                    continue
                if slot in HEAVY_OK_IF_NANITE and not _nanite(mesh):
                    try:
                        if mesh.get_num_triangles(0) > 100000:
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                pal.add_mesh(slot, _mesh_entry(mesh, slot))
                found.append(mesh.get_path_name())
                break
        report["meshes"][slot] = found
        if not found:
            report["missing"].append(slot)

    for slot, names in MATERIAL_SLOTS.items():
        chosen = None
        for n in names:
            if n.startswith("M_Ramms") and H.EAL.does_asset_exist(MATERIALS_DIR + "/" + n):
                chosen = H.EAL.load_asset(MATERIALS_DIR + "/" + n)
                break
            for ad in index.get(n, []):
                if str(ad.asset_class_path.asset_name) in ("MaterialInstanceConstant", "Material"):
                    chosen = ad.get_asset()
                    break
            if chosen:
                break
        if chosen is None:
            chosen = unreal.load_asset(ENGINE_MAT)
            report["missing"].append(slot)
        pal.set_material(slot, chosen)
        report["materials"][slot] = chosen.get_path_name()

    report["material_sets"] = {}
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    for slot, names in MATERIAL_SETS.items():
        mats = []
        for n in names:
            if n.endswith("*"):
                for ad in reg.get_assets_by_path(MATERIALS_DIR, False):
                    if str(ad.asset_name).startswith(n[:-1]):
                        mats.append(ad.get_asset())
                continue
            if n.startswith("M_Ramms"):
                if H.EAL.does_asset_exist(MATERIALS_DIR + "/" + n):
                    mats.append(H.EAL.load_asset(MATERIALS_DIR + "/" + n))
                continue
            for ad in index.get(n, []):
                if str(ad.asset_class_path.asset_name) in ("MaterialInstanceConstant", "Material"):
                    mats.append(ad.get_asset())
                    break
        mats = [m for m in mats if m is not None]
        if slot.startswith("Decal."):
            mats = [m for m in mats if _is_decal(m)]
        for m in mats:
            pal.add_material(slot, m)
        report["material_sets"][slot] = [m.get_name() for m in mats]
        if not mats:
            report["missing"].append(slot)

    build_facade_slots(pal, report)

    report["composites"] = {}
    for slot, cls_paths in COMPOSITE_SLOTS.items():
        for cls_path in cls_paths:
            try:
                e = _composite_entry(cls_path, slot)
            except Exception as exc:  # noqa: BLE001
                H.warn("composite %s failed: %s" % (cls_path, exc))
                e = None
            if e is not None:
                pal.add_mesh(slot, e)
                report["composites"].setdefault(slot, []).append(cls_path)

    for slot, cls_path in ACTOR_SLOTS.items():
        cls = unreal.load_class(None, cls_path)
        if cls:
            pal.set_actor_class(slot, cls)
        else:
            report["missing"].append(slot)

    H.save(pal)
    missing = [str(n) for n in pal.missing_well_known_slots()]
    report["still_empty"] = missing
    H.log("palette %s: %d mesh slots, %d material slots; empty: %s" % (path, len(report["meshes"]), len(report["materials"]), missing))
    return pal, report
