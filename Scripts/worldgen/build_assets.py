"""Build the world-generation assets from code inside a running editor.

    python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_assets.py

Creates/refreshes /RammsWorldGen/Palettes/PAL_Default (from the Fab packs),
/RammsWorldGen/Profiles/PROF_ADA, the presets, and the PCG graphs. Safe to
re-run: everything is rebuilt in place. Requires the RammsWorldGen C++ module
to be compiled and the editor to have loaded it.
"""
import importlib

import unreal

import ramms_worldgen.build_all as b

for m in ("ramms_worldgen._helpers", "ramms_worldgen._graph", "ramms_worldgen.palettes", "ramms_worldgen.presets", "ramms_worldgen.graphs", "ramms_worldgen.build_all"):
    importlib.reload(importlib.import_module(m))
import ramms_worldgen.build_all as b  # noqa: E402  (reloaded)

report = b.build("all")
unreal.log("[worldgen] " + b.H.dumps(report))
