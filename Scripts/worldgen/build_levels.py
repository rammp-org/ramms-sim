"""Build the example levels (Map_Gen_Downtown / Suburban / Park / Indoor / Office).

    python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_levels.py

Each level is created, generated, and saved once its generation finishes; the
editor keeps running between them, so watch the Output Log for
"[RammsWorldGen] level ... generated". Run build_assets.py first.
"""
import importlib

import ramms_worldgen.levels as levels

importlib.reload(levels)
levels.build_all_levels()
