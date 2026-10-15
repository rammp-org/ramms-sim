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

# name -> spec. bc/n/rma: texture paths (rma channels: roughness, ao); bc2/n2/rma2: optional variant set;
# tile: tile size in cm; mask: low-frequency mask texture; tint: base colour multiplier; rough: roughness bias.
_MASK = "/Game/CityBeachStrip/Textures/Masks/T_Dirt_Mask"
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
        rma2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_RMA", tile=380.0, mask=_MASK, macro=(0.78, 1.12), tint=(0.62, 0.80, 0.42)),
    "M_RammsLawn": dict(
        bc="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_BC", n="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_N",
        rma="/Game/ResidentialHouses/Textures/Foliage/Grass/T_GrassGround_RMA",
        bc2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_BC", n2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_N",
        rma2="/Game/CityBeachStrip/Textures/Landscape/T_GrassGround_02_RMA", tile=320.0, mask=_MASK, macro=(0.82, 1.1), tint=(0.58, 0.82, 0.40)),
    "M_RammsPath": dict(
        bc="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_BC", n="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_N",
        rma="/Game/ResidentialHouses/Textures/Tileable/Paths/T_Path_Concrete_RMA", tile=220.0, mask=_MASK, second=False),
    "M_RammsDirt": dict(
        bc="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_BC", n="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_N",
        rma="/Game/TownShops/Textures/Tileable/Dirt/T_Dirt_RMA", tile=300.0, mask=_MASK),
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

    wp = g.node(unreal.MaterialExpressionWorldPosition, -1600)
    xy = g.node(unreal.MaterialExpressionComponentMask, -1450, r=True, g=True, b=False, a=False)
    MEL.connect_material_expressions(wp, "", xy, "")
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
        tn = g.node(unreal.MaterialExpressionConstant3Vector, -250, constant=unreal.LinearColor(tint[0], tint[1], tint[2], 1.0))
        mul = g.node(unreal.MaterialExpressionMultiply, -100)
        MEL.connect_material_expressions(col, col_out, mul, "A")
        MEL.connect_material_expressions(tn, "", mul, "B")
        col, col_out = mul, ""
    MEL.connect_material_property(col, col_out, unreal.MaterialProperty.MP_BASE_COLOR)
    if n is not None:
        nn, nn_out = pair(n, n2 if bc2 is not None else None, "RGB")
        MEL.connect_material_property(nn, nn_out, unreal.MaterialProperty.MP_NORMAL)
    if rma is not None:
        rr, rr_out = pair(rma, rma2 if bc2 is not None else None, "RGB")
        rough = g.node(unreal.MaterialExpressionComponentMask, -100, r=True, g=False, b=False, a=False)
        MEL.connect_material_expressions(rr, rr_out, rough, "")
        MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
        ao = g.node(unreal.MaterialExpressionComponentMask, -100, r=False, g=False, b=True, a=False)
        MEL.connect_material_expressions(rr, rr_out, ao, "")
        MEL.connect_material_property(ao, "", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    else:
        r = g.node(unreal.MaterialExpressionConstant, -100, r=0.85)
        MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.layout_material_expressions(mat)
    MEL.recompile_material(mat)
    H.save(mat)
    return mat


def build_surfaces():
    """Create or refresh every surface material. Returns {name: path or None}."""
    out = {}
    for name, spec in SURFACES.items():
        try:
            m = _build(name, spec)
        except Exception as exc:  # noqa: BLE001
            H.warn("surface %s failed: %s" % (name, exc))
            m = None
        out[name] = m.get_path_name() if m else None
    H.log("surfaces: %s" % out)
    return out
