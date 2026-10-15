"""World-aligned, anti-tiling ground materials built from pack textures.

Generated roads, sidewalks and lawns are boxes and slabs of arbitrary size, so a
material that relies on mesh UVs either stretches (scaled cubes) or repeats in
an obvious grid. These materials take their UVs from the world XY position
instead, at a real-world tile size, and break the repetition up:

* the texture set is sampled twice, at the tile size and at a rotated-ish 0.537x
  scale with an offset, and blended by a low-frequency mask,
* a second, much larger mask modulates brightness (macro variation),
* an optional second texture set (e.g. a damaged / patchy variant) is blended in
  by the same mask instead of the second sample of the first set.

Built once per surface by `build_surfaces()`; the palette builder points the
Mat.* slots at them. Missing textures just skip that surface.
"""

import unreal

from . import _helpers as H

DIR = "/Game/WorldGen/Materials"
MEL = unreal.MaterialEditingLibrary

# name -> spec. bc/n/rma: texture paths; layout: how the packed texture holds roughness / AO -
# "rma" (R rough, B ao), "mrao" (G rough, B ao), "orm" (R ao, G rough), "mask" (HDRP mask map: G ao,
# A smoothness); bc2/n2/rma2: optional variant set; tile: tile size in cm; second: blend a second,
# rescaled sample (off for regular patterns: tiles, planks, bricks, wallpaper); mask: low-frequency mask
# texture; macro: brightness range of the large-scale variation; tint: base colour multiplier; tint2: a
# second tint the macro mask blends toward (colour patches on lawns); tint_param: expose the tint as a
# "Tint" vector parameter so material instances can recolour it (paints).
_MASK = "/Game/CityBeachStrip/Textures/Masks/T_Dirt_Mask"
_SNH = "/Game/SuburbNeighborhoodHousePack/Textures/"
_CBS = "/Game/CityBeachStrip/Textures/"
_RSF = "/Game/RealCitySF/Textures/Remastered/Bldg_GP_Textures/"
SURFACES = {
    "M_RammsAsphalt": dict(
        bc="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt01_BC", n="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt01_N",
        rma="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt01_RMA",
        bc2="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt02_BC", n2="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt02_N",
        rma2="/Game/StripMall/Textures/Tileable/Roads/T_RoadAsphalt02_RMA", tile=450.0, mask=_MASK, tint=(0.95, 0.95, 0.97)),
    "M_RammsSidewalk": dict(
        bc="/Game/StripMall/Textures/Tileable/Sidewalk/T_Sidewalk01_BC", n="/Game/StripMall/Textures/Tileable/Sidewalk/T_Sidewalk01_N",
        rma="/Game/StripMall/Textures/Tileable/Sidewalk/T_Sidewalk01_RMA", tile=300.0, mask=_MASK, second=False),
    "M_RammsConcrete": dict(
        bc="/Game/TownShops/Textures/Tileable/Concrete/T_ConcreteBase_BC", n="/Game/TownShops/Textures/Tileable/Concrete/T_ConcreteBase_N",
        rma="/Game/TownShops/Textures/Tileable/Concrete/T_ConcreteBase_RMA", tile=400.0, mask=_MASK),
    "M_RammsGrass": dict(
        bc="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_BC", n="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_N",
        rma="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_RMA",
        bc2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_BC", n2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_N",
        rma2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_RMA", tile=380.0, mask=_MASK, macro=(0.78, 1.12), tint=(0.62, 0.80, 0.42), tint2=(0.78, 0.80, 0.46)),
    "M_RammsLawn": dict(
        bc="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_BC", n="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_N",
        rma="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_RMA",
        bc2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_BC", n2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_N",
        rma2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_RMA", tile=320.0, mask=_MASK, macro=(0.82, 1.1), tint=(0.55, 0.80, 0.38), tint2=(0.74, 0.78, 0.44)),
    "M_RammsPath": dict(
        bc="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_BC", n="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_N",
        rma="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_RMA", tile=220.0, mask=_MASK, second=False),
    "M_RammsDirt": dict(
        bc="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_BC", n="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_N",
        rma="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_RMA", tile=300.0, mask=_MASK),
    # curbs: a finer concrete so the 15 cm face reads as cast concrete, slightly darker than the walk
    "M_RammsCurb": dict(
        bc="/Game/RealCitySF/Textures/Remastered/T_Sidewalk_conc_tan_tile_01_BaseColor", n="/Game/RealCitySF/Textures/Remastered/T_Sidewalk_conc_tan_tile_01_Normal",
        rma="/Game/RealCitySF/Textures/Remastered/T_Sidewalk_conc_tan_tile_01_MRAO", layout="mrao", tile=140.0, mask=_MASK, second=False, tint=(0.82, 0.82, 0.82)),
    # stand-in building shells (when no house / facade kit fits): world-aligned so nothing stretches
    "M_RammsBrick": dict(
        bc="/Game/StripMall/Textures/Tileable/Brick/T_BrickWall03_BC", n="/Game/StripMall/Textures/Tileable/Brick/T_BrickWall03_N",
        rma="/Game/StripMall/Textures/Tileable/Brick/T_BrickWall03_RMA", tile=220.0, mask=_MASK, second=False, macro=(0.9, 1.05)),
    "M_RammsSiding": dict(
        bc=_SNH + "T_Wall_HouseWoodPlank_White_BaseColor", n=_SNH + "T_Wall_HouseWoodPlank_Normal",
        rma=_SNH + "T_Wall_HouseWoodPlank_White_MaskMap", layout="mask", tile=200.0, mask=_MASK, second=False, macro=(0.92, 1.03)),
    # interior walls
    "M_RammsPaint": dict(
        bc=_RSF + "T_int_wall_drywall_tile_01_BaseColor", n=_RSF + "T_int_wall_drywall_tile_01_Normal",
        rma=_RSF + "T_int_wall_drywall_tile_01_MRAO", layout="mrao", tile=200.0, second=False, tint=(0.92, 0.91, 0.88), tint_param=True),
    "M_RammsWallpaper": dict(
        bc="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallPaper_BC", n="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallPaper_N",
        rma="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallPaper_RMA", tile=90.0, second=False),
    "M_RammsWallpaperDiamond": dict(
        bc=_SNH + "T_In_WallPaper_Diamond_BaseColor", n=_SNH + "T_In_WallPaper_Diamond_Normal",
        rma=_SNH + "T_In_WallPaper_Diamond_MaskMap", layout="mask", tile=100.0, second=False),
    "M_RammsWallpaperFlowers": dict(
        bc=_SNH + "T_In_WallPaper_Flowers_BaseColor", n=_SNH + "T_In_WallPaper_Normal",
        rma=_SNH + "T_In_WallPaper_MaskMap", layout="mask", tile=100.0, second=False),
    "M_RammsWallpaperRed": dict(
        bc=_SNH + "T_In_WallPaper_Red_BaseColor", n=_SNH + "T_In_WallPaper_Normal",
        rma=_SNH + "T_In_WallPaper_Red_MaskMap", layout="mask", tile=100.0, second=False),
    "M_RammsWallTile": dict(
        bc="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallTile_BC", n="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallTile_N",
        rma="/Game/ResidentialHouses/Textures/Walls/Inside/T_WallTile_RMA", tile=120.0, second=False),
    "M_RammsWallTile2": dict(
        bc=_CBS + "Tileable/Tiles/T_CeramicTiles_01_BC", n=_CBS + "Tileable/Tiles/T_CeramicTiles_01_N",
        rma=_CBS + "Tileable/Tiles/T_CeramicTiles_01_RMA", tile=120.0, second=False),
    # floors
    "M_RammsFloorWood1": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_WoodFloor01_BC", n=_CBS + "Architecture/Interiors/Floor/T_WoodFloor01_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_WoodFloor01_RMA", tile=250.0, second=False, macro=(0.92, 1.05), mask=_MASK),
    "M_RammsFloorWood2": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_WoodFloor02_BC", n=_CBS + "Architecture/Interiors/Floor/T_WoodFloor02_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_WoodFloor02_RMA", tile=250.0, second=False, macro=(0.92, 1.05), mask=_MASK),
    "M_RammsFloorParquet": dict(
        bc="/Game/ResidentialHouses/Textures/Tileable/Wood/T_ParquetFloor_BC", n="/Game/ResidentialHouses/Textures/Tileable/Wood/T_ParquetFloor_N",
        rma="/Game/ResidentialHouses/Textures/Tileable/Wood/T_ParquetFloor_RMA", tile=200.0, second=False),
    "M_RammsFloorHardwood": dict(
        bc="/Game/HousePropsFurniture/Textures/Textures_building/T_Floor_hardwood_BaseColor", n="/Game/HousePropsFurniture/Textures/Textures_building/T_Floor_hardwood_Normal",
        rma="/Game/HousePropsFurniture/Textures/Textures_building/T_Floor_hardwood_MaskMap", layout="mask", tile=250.0, second=False),
    "M_RammsFloorCarpet1": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_Carpet01_BC", n=_CBS + "Architecture/Interiors/Floor/T_Carpet01_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_Carpet01_RMA", tile=200.0, mask=_MASK, macro=(0.9, 1.05)),
    "M_RammsFloorCarpet2": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_Carpet02_BC", n=_CBS + "Architecture/Interiors/Floor/T_Carpet02_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_Carpet02_RMA", tile=200.0, mask=_MASK, macro=(0.9, 1.05)),
    "M_RammsFloorCarpetOffice": dict(
        bc="/Game/Office/Textures/TX_Carpet_BaseColor", n="/Game/Office/Textures/TX_Carpet_Normal",
        rma="/Game/Office/Textures/TX_Carpet_OcclusionRoughnessMetallic", layout="orm", tile=200.0, mask=_MASK, macro=(0.9, 1.05)),
    "M_RammsFloorCarpetTiles": dict(
        bc=_RSF + "T_int_floor_carpet_tiles_01_BaseColor", n=_RSF + "T_int_floor_carpet_tiles_01_Normal",
        rma=_RSF + "T_int_floor_carpet_tiles_01_MRAO", layout="mrao", tile=200.0, second=False),
    "M_RammsFloorBath": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_BathroomFloor01_BC", n=_CBS + "Architecture/Interiors/Floor/T_BathroomFloor01_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_BathroomFloor01_RMA", tile=150.0, second=False),
    "M_RammsFloorCeramic": dict(
        bc=_CBS + "Tileable/Tiles/T_CeramicTiles_02_BC", n=_CBS + "Tileable/Tiles/T_CeramicTiles_02_N",
        rma=_CBS + "Tileable/Tiles/T_CeramicTiles_02_RMA", tile=150.0, second=False),
    "M_RammsFloorTiles": dict(
        bc=_RSF + "T_int_floor_tiles_01_BaseColor", n=_RSF + "T_int_floor_tiles_01_Normal",
        rma=_RSF + "T_int_floor_tiles_01_MRAO", layout="mrao", tile=200.0, second=False),
    "M_RammsFloorMarble": dict(
        bc=_CBS + "Tileable/Marble/T_MarbleTiles_BC", n=_CBS + "Tileable/Marble/T_MarbleTiles_N",
        rma=_CBS + "Tileable/Marble/T_MarbleTiles_RMA", tile=200.0, second=False),
    "M_RammsFloorPVC": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_PVC_Floor01_BC", n=_CBS + "Architecture/Interiors/Floor/T_PVC_Floor01_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_PVC_Floor01_RMA", tile=250.0, second=False),
    "M_RammsFloorPVC2": dict(
        bc="/Game/TownShops/Textures/Tileable/Flooring/T_PVC_Flooring_01_BC", n="/Game/TownShops/Textures/Tileable/Flooring/T_PVC_Flooring_01_N",
        rma="/Game/TownShops/Textures/Tileable/Flooring/T_PVC_Flooring_01_RMA", tile=250.0, second=False),
    "M_RammsFloorShop": dict(
        bc=_CBS + "Architecture/Interiors/Floor/T_Floor01_BC", n=_CBS + "Architecture/Interiors/Floor/T_Floor01_N",
        rma=_CBS + "Architecture/Interiors/Floor/T_Floor01_RMA", tile=250.0, second=False),
    "M_RammsFloorConcrete": dict(
        bc=_RSF + "T_int_floor_concrete_glossy_tiled_01_BaseColor", n=_RSF + "T_int_floor_concrete_glossy_tiled_01_Normal",
        rma=_RSF + "T_int_floor_concrete_glossy_tiled_01_MRAO", layout="mrao", tile=300.0, mask=_MASK),
}

# Paint colours: material instances of M_RammsPaint with the Tint parameter set.
PAINTS = {
    "Cream": (0.93, 0.85, 0.68), "Sage": (0.56, 0.68, 0.50), "SkyBlue": (0.52, 0.68, 0.84), "Grey": (0.62, 0.64, 0.66),
    "Beige": (0.84, 0.72, 0.56), "Terracotta": (0.78, 0.47, 0.34), "Mint": (0.60, 0.82, 0.70), "Lavender": (0.70, 0.64, 0.82),
    "Butter": (0.95, 0.84, 0.50), "Slate": (0.40, 0.48, 0.56), "Blush": (0.90, 0.68, 0.66), "White": (0.92, 0.91, 0.88),
    "Olive": (0.62, 0.62, 0.42), "Teal": (0.36, 0.60, 0.62),
}


def _load(path):
    if not path:
        return None
    return H.EAL.load_asset(path) if H.EAL.does_asset_exist(path) else None


def _sampler_type(tex):
    cs = tex.get_editor_property("compression_settings")
    srgb = tex.get_editor_property("srgb")
    TC, ST = unreal.TextureCompressionSettings, unreal.MaterialSamplerType
    if cs == TC.TC_NORMALMAP:
        return ST.SAMPLERTYPE_NORMAL
    if cs == TC.TC_GRAYSCALE:
        return ST.SAMPLERTYPE_GRAYSCALE if srgb else ST.SAMPLERTYPE_LINEAR_GRAYSCALE
    if cs == TC.TC_ALPHA:
        return ST.SAMPLERTYPE_ALPHA
    if cs == TC.TC_MASKS:
        return ST.SAMPLERTYPE_MASKS
    if not srgb:
        return ST.SAMPLERTYPE_LINEAR_COLOR
    return ST.SAMPLERTYPE_COLOR


class _G:
    """Tiny graph helper: places nodes in columns and connects by name."""

    def __init__(self, mat):
        self.m = mat
        self.y = 0

    def node(self, cls, x, **props):
        e = MEL.create_material_expression(self.m, cls, x, self.y)
        self.y += 140
        for k, v in props.items():
            e.set_editor_property(k, v)
        return e

    def tex(self, x, tex, uv):
        e = self.node(unreal.MaterialExpressionTextureSample, x, texture=tex, sampler_type=_sampler_type(tex))
        MEL.connect_material_expressions(uv, "", e, "UVs")
        return e

    def lerp(self, x, a, a_out, b, b_out, alpha, alpha_out="R"):
        e = self.node(unreal.MaterialExpressionLinearInterpolate, x)
        MEL.connect_material_expressions(a, a_out, e, "A")
        MEL.connect_material_expressions(b, b_out, e, "B")
        MEL.connect_material_expressions(alpha, alpha_out, e, "Alpha")
        return e


def _world_uv(g):
    """World-space UVs by the dominant normal axis: XY on floors and tops, YZ / XZ on walls and curb faces
    (V = -Z so textures stay upright). Selection is a hard switch built from lerps so no If node is needed."""
    wp = g.node(unreal.MaterialExpressionWorldPosition, -2600)
    nrm = g.node(unreal.MaterialExpressionVertexNormalWS, -2600)
    an = g.node(unreal.MaterialExpressionAbs, -2450)
    MEL.connect_material_expressions(nrm, "", an, "")
    def mask(src, r, gg, b):
        e = g.node(unreal.MaterialExpressionComponentMask, -2300, r=r, g=gg, b=b, a=False)
        MEL.connect_material_expressions(src, "", e, "")
        return e
    nx, ny, nz = mask(an, True, False, False), mask(an, False, True, False), mask(an, False, False, True)
    wx, wy, wz = mask(wp, True, False, False), mask(wp, False, True, False), mask(wp, False, False, True)
    xy = mask(wp, True, True, False)
    negz = g.node(unreal.MaterialExpressionMultiply, -2150, const_b=-1.0)
    MEL.connect_material_expressions(wz, "", negz, "A")
    def append(a_, b_):
        e = g.node(unreal.MaterialExpressionAppendVector, -2000)
        MEL.connect_material_expressions(a_, "", e, "A")
        MEL.connect_material_expressions(b_, "", e, "B")
        return e
    xz, yz = append(wx, negz), append(wy, negz)
    def step(a_, b_=None, const=None):
        sub = g.node(unreal.MaterialExpressionSubtract, -2000, **({"const_b": const} if const is not None else {}))
        MEL.connect_material_expressions(a_, "", sub, "A")
        if b_ is not None:
            MEL.connect_material_expressions(b_, "", sub, "B")
        mul = g.node(unreal.MaterialExpressionMultiply, -1900, const_b=1000.0)
        MEL.connect_material_expressions(sub, "", mul, "A")
        sat = g.node(unreal.MaterialExpressionSaturate, -1800)
        MEL.connect_material_expressions(mul, "", sat, "")
        return sat
    side = g.lerp(-1700, xz, "", yz, "", step(nx, ny), "")
    return g.lerp(-1650, side, "", xy, "", step(nz, const=0.5), "")


# packed texture layouts: (roughness channel, ao channel, roughness is smoothness)
_LAYOUTS = {"rma": ("R", "B", False), "mrao": ("G", "B", False), "orm": ("G", "R", False), "mask": ("A", "G", True)}


def _build(name, spec):
    bc, n, rma, mask = _load(spec["bc"]), _load(spec.get("n")), _load(spec.get("rma")), _load(spec.get("mask"))
    if bc is None:
        H.warn("surface %s: base colour %s missing" % (name, spec["bc"]))
        return None
    bc2, n2, rma2 = _load(spec.get("bc2")), _load(spec.get("n2")), _load(spec.get("rma2"))
    second = spec.get("second", True) or bc2 is not None
    path = DIR + "/" + name
    H.ensure_dir(DIR)
    if H.EAL.does_asset_exist(path):
        mat = H.EAL.load_asset(path)
        MEL.delete_all_material_expressions(mat)
    else:
        mat = H.asset_tools().create_asset(name, DIR, unreal.Material, unreal.MaterialFactoryNew())
    g = _G(mat)
    tile = float(spec.get("tile", 300.0))

    xy = _world_uv(g)
    uv1 = g.node(unreal.MaterialExpressionDivide, -1300, const_b=tile)
    MEL.connect_material_expressions(xy, "", uv1, "A")
    uvs = g.node(unreal.MaterialExpressionMultiply, -1150, const_b=0.537)
    MEL.connect_material_expressions(uv1, "", uvs, "A")
    uv2 = g.node(unreal.MaterialExpressionAdd, -1000, const_b=0.371)
    MEL.connect_material_expressions(uvs, "", uv2, "A")
    blend = None
    macro = None
    if mask is not None:
        uvm = g.node(unreal.MaterialExpressionDivide, -1300, const_b=tile * 7.3)
        MEL.connect_material_expressions(xy, "", uvm, "A")
        blend = g.tex(-1000, mask, uvm)
        uvM = g.node(unreal.MaterialExpressionDivide, -1300, const_b=tile * 29.0)
        MEL.connect_material_expressions(xy, "", uvM, "A")
        macro = g.tex(-1000, mask, uvM)

    def pair(t1, t2, out_all):
        a = g.tex(-700, t1, uv1)
        if blend is None or not second:
            return a, out_all
        b = g.tex(-700, t2 or t1, uv2)
        return g.lerp(-450, a, out_all, b, out_all, blend), ""

    col, col_out = pair(bc, bc2, "RGB")
    if macro is not None:
        lo, hi = spec.get("macro", (0.85, 1.1))
        bright = g.node(unreal.MaterialExpressionLinearInterpolate, -450, const_a=lo, const_b=hi)
        MEL.connect_material_expressions(macro, "R", bright, "Alpha")
        mul = g.node(unreal.MaterialExpressionMultiply, -250)
        MEL.connect_material_expressions(col, col_out, mul, "A")
        MEL.connect_material_expressions(bright, "", mul, "B")
        col, col_out = mul, ""
    tint = spec.get("tint")
    if tint:
        if spec.get("tint_param"):
            tn = g.node(unreal.MaterialExpressionVectorParameter, -250, parameter_name="Tint", default_value=unreal.LinearColor(tint[0], tint[1], tint[2], 1.0))
            tn_out = "RGB"
        else:
            tn = g.node(unreal.MaterialExpressionConstant3Vector, -250, constant=unreal.LinearColor(tint[0], tint[1], tint[2], 1.0))
            tn_out = ""
        t2 = spec.get("tint2")
        if t2 and macro is not None:
            # Colour patches: the large-scale mask drifts the tint toward a second hue (dry / lush grass).
            tn2 = g.node(unreal.MaterialExpressionConstant3Vector, -250, constant=unreal.LinearColor(t2[0], t2[1], t2[2], 1.0))
            sharp = g.node(unreal.MaterialExpressionPower, -350, const_exponent=2.0)
            MEL.connect_material_expressions(macro, "G", sharp, "Base")
            tn = g.lerp(-200, tn, tn_out, tn2, "", sharp, "")
            tn_out = ""
        mul = g.node(unreal.MaterialExpressionMultiply, -100)
        MEL.connect_material_expressions(col, col_out, mul, "A")
        MEL.connect_material_expressions(tn, tn_out, mul, "B")
        col, col_out = mul, ""
    MEL.connect_material_property(col, col_out, unreal.MaterialProperty.MP_BASE_COLOR)
    if n is not None:
        nn, nn_out = pair(n, n2 if bc2 is not None else None, "RGB")
        MEL.connect_material_property(nn, nn_out, unreal.MaterialProperty.MP_NORMAL)
    if rma is not None:
        rc, ac, smooth = _LAYOUTS.get(spec.get("layout", "rma"), _LAYOUTS["rma"])
        rr, rr_out = pair(rma, rma2 if bc2 is not None else None, "RGBA" if smooth else "RGB")
        rough = g.node(unreal.MaterialExpressionComponentMask, -100, r=rc == "R", g=rc == "G", b=rc == "B", a=rc == "A")
        MEL.connect_material_expressions(rr, rr_out, rough, "")
        if smooth:
            inv = g.node(unreal.MaterialExpressionOneMinus, -50)
            MEL.connect_material_expressions(rough, "", inv, "")
            rough = inv
        MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
        ao = g.node(unreal.MaterialExpressionComponentMask, -100, r=ac == "R", g=ac == "G", b=ac == "B", a=False)
        MEL.connect_material_expressions(rr, rr_out, ao, "")
        MEL.connect_material_property(ao, "", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    else:
        r = g.node(unreal.MaterialExpressionConstant, -100, r=0.85)
        MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.layout_material_expressions(mat)
    MEL.recompile_material(mat)
    H.save(mat)
    return mat


def build_paints():
    """Material instances of M_RammsPaint, one per PAINTS colour. Returns their paths."""
    parent_path = DIR + "/M_RammsPaint"
    if not H.EAL.does_asset_exist(parent_path):
        return []
    parent = H.EAL.load_asset(parent_path)
    out = []
    for cname, rgb in PAINTS.items():
        name = "MI_RammsPaint_" + cname
        path = DIR + "/" + name
        if H.EAL.does_asset_exist(path):
            mi = H.EAL.load_asset(path)
        else:
            mi = H.asset_tools().create_asset(name, DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        if mi is None:
            continue
        MEL.set_material_instance_parent(mi, parent)
        MEL.set_material_instance_vector_parameter_value(mi, "Tint", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
        H.save(mi)
        out.append(mi.get_path_name())
    return out


def build_surfaces():
    """Create or refresh every surface material and the paint instances. Returns {name: path or None}."""
    out = {}
    for name, spec in SURFACES.items():
        try:
            m = _build(name, spec)
        except Exception as exc:  # noqa: BLE001
            H.warn("surface %s failed: %s" % (name, exc))
            m = None
        out[name] = m.get_path_name() if m else None
    try:
        out["paints"] = build_paints()
    except Exception as exc:  # noqa: BLE001
        H.warn("paints failed: %s" % exc)
    H.log("surfaces: %s" % out)
    return out
