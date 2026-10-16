# RammsWorldGen toolset: world generation and randomization for AI assistants.
#
# Same conventions as the RAMMS toolset: every tool returns a JSON string,
# `generator` is a partial actor name ("" = the only one), read-only tools
# work before play. Generation is asynchronous: generate/randomize return at
# once and the caller polls worldgen_status until `generating` is false.

import unreal

import toolset_registry

from . import _helpers as H
from . import presets as PR


def _status(gen):
    m = H.manifest_to_dict(gen)
    feats = m.get("features", [])
    issues = {}
    for f in feats:
        if not f.get("bCompliant", True):
            issues[f.get("issue", "?")] = issues.get(f.get("issue", "?"), 0) + 1
    preset = gen.get_editor_property("preset")
    return {
        "generator": gen.get_actor_label(),
        "preset": preset.get_name() if preset else None,
        "scene_kind": str(preset.get_editor_property("scene_kind")) if preset else None,
        "seed": gen.get_editor_property("seed"),
        "generating": gen.is_generating(),
        "features": len(feats),
        "routes": len(m.get("routes", [])),
        "non_compliant": sum(issues.values()),
        "issues": issues,
        "suggested_start": m.get("suggestedStart"),
    }


@unreal.uclass()
class RammsWorldGenToolset(unreal.ToolsetDefinition):
    """Generate and randomize pedestrian / wheelchair environments (streets,
    sidewalks, buildings, parks, indoor layouts) and read their ground-truth
    manifests."""

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_status(generator: str = "") -> str:
        """Summarize the world generators in the current level.

        Args:
            generator: Partial actor name; empty reports every generator.

        Returns:
            JSON list with preset, seed, whether generation is running, and manifest counts.
        """
        gens = H.find_generators()
        if generator:
            gens = [g for g in gens if generator.lower() in g.get_actor_label().lower()]
        return H.dumps([_status(g) for g in gens])

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_list_presets() -> str:
        """List the world presets and what each produces.

        Returns:
            JSON list of {name, scene_kind, description, exists}.
        """
        out = []
        for name, (kind, graph, desc, params) in PR.PRESETS.items():
            out.append({"name": name, "scene_kind": str(kind), "description": desc, "exists": H.EAL.does_asset_exist(H.PRESETS + "/" + name), "params": params})
        return H.dumps(out)

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_generate(generator: str = "", preset: str = "", seed: int = -1) -> str:
        """(Re)generate a world, optionally switching preset and seed.

        Args:
            generator: Partial actor name; empty means the only generator.
            preset: Preset name (PRE_Downtown, PRE_Suburban, PRE_Park, PRE_Indoor_Home, PRE_Indoor_Office) or asset path; empty keeps the current one.
            seed: Seed to use; -1 keeps the current seed. Same preset + seed = same world.

        Returns:
            JSON with the request; poll worldgen_status until generating is false.
        """
        gen = H.find_generator(generator)
        if preset:
            gen.set_editor_property("preset", PR.load_preset(preset))
        if seed >= 0:
            gen.set_editor_property("seed", int(seed))
        gen.regenerate()
        return H.dumps({"requested": True, "generator": gen.get_actor_label(), "seed": gen.get_editor_property("seed"), "note": "poll worldgen_status until generating is false"})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_randomize(generator: str = "") -> str:
        """Pick a new random seed and regenerate.

        Args:
            generator: Partial actor name; empty means the only generator.

        Returns:
            JSON with the new seed.
        """
        gen = H.find_generator(generator)
        gen.randomize()
        return H.dumps({"requested": True, "seed": gen.get_editor_property("seed")})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_cleanup(generator: str = "") -> str:
        """Remove everything a generator spawned.

        Args:
            generator: Partial actor name; empty means the only generator.

        Returns:
            JSON confirming the request.
        """
        H.find_generator(generator).cleanup()
        return H.dumps({"requested": True})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_manifest(generator: str = "", kind: str = "", only_non_compliant: bool = False) -> str:
        """The ground-truth manifest of a generated world: routes with clear widths, and every
        hazard, ramp, door, entrance and crossing with its compliance verdict.

        Args:
            generator: Partial actor name; empty means the only generator.
            kind: Optional feature kind filter, e.g. Hazard, CurbRamp, Door, Entrance, Room, Crossing.
            only_non_compliant: When true, list only features that break the accessibility profile.

        Returns:
            JSON manifest (seed, preset, routes, features, suggestedStart).
        """
        gen = H.find_generator(generator)
        m = H.manifest_to_dict(gen)
        feats = m.get("features", [])
        if kind:
            feats = [f for f in feats if str(f.get("kind", "")).lower() == kind.lower()]
        if only_non_compliant:
            feats = [f for f in feats if not f.get("bCompliant", True)]
        m["features"] = feats
        return H.dumps(m)

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_get_params(generator: str = "") -> str:
        """Every generation parameter and its resolved value (preset + overrides).

        Args:
            generator: Partial actor name; empty means the only generator.

        Returns:
            JSON {name: value}.
        """
        gen = H.find_generator(generator)
        out = {}
        for n in gen.get_param_names():
            v = gen.get_param(n)   # bool return + out param -> Optional[float]
            if v is not None:
                out[str(n)] = v
        return H.dumps(out)

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_set_param(generator: str, name: str, value: float) -> str:
        """Override one parameter on a generator (kept across preset updates) and regenerate.

        Args:
            generator: Partial actor name; empty means the only generator.
            name: Parameter name from worldgen_get_params, e.g. NonCompliance, SidewalkWidth, HazardDensity.
            value: New value (bools as 0/1, ints rounded).

        Returns:
            JSON with the accepted value, or an error for unknown names.
        """
        gen = H.find_generator(generator)
        if not gen.set_param(name, float(value)):
            raise RuntimeError("unknown parameter '%s'; see worldgen_get_params" % name)
        gen.regenerate()
        return H.dumps({"name": name, "value": value, "requested": True})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_export_manifest(generator: str = "", path: str = "") -> str:
        """Write the manifest JSON to disk.

        Args:
            generator: Partial actor name; empty means the only generator.
            path: Absolute file path; empty writes under Saved/WorldGen/.

        Returns:
            JSON with the path written.
        """
        gen = H.find_generator(generator)
        return H.dumps({"path": gen.export_manifest(path)})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_place_player_start(generator: str = "") -> str:
        """Move (or create) the level's PlayerStart to the manifest's suggested start pose.

        Args:
            generator: Partial actor name; empty means the only generator.

        Returns:
            JSON with the suggested start.
        """
        gen = H.find_generator(generator)
        gen.place_player_start()
        return H.dumps({"suggested_start": H.manifest_to_dict(gen).get("suggestedStart")})

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_build_assets(what: str = "all") -> str:
        """Create or refresh the generated-content assets from code: the default palette (from the
        Fab packs), the accessibility profile, the presets, and the PCG graphs.

        Args:
            what: all, palette, presets, graphs.

        Returns:
            JSON report (palette slots filled / missing, assets written).
        """
        from . import build_all
        return H.dumps(build_all.build(what))

    @toolset_registry.tool_call
    @staticmethod
    def worldgen_build_level(kind: str, seed: int = -1) -> str:
        """Create an example level with lights, ground, a generator and a PlayerStart, and generate it.

        Args:
            kind: downtown, suburban, park, indoor, office.
            seed: Seed; -1 uses the example's default.

        Returns:
            JSON with the map path; generation finishes asynchronously and the map is saved then.
        """
        from . import levels
        return H.dumps({"map": levels.build_level(kind, None if seed < 0 else seed)})
