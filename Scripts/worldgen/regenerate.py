"""Regenerate the generator in the open level with a new seed (default: random).

    python Scripts/editor_remote_exec.py --file Scripts/worldgen/regenerate.py
"""
import random

import unreal

import ramms_worldgen._helpers as H

gen = H.find_generator()
gen.set_editor_property("seed", random.randrange(1, 1 << 30))
gen.regenerate()
unreal.log("[worldgen] regenerating %s with seed %d" % (gen.get_actor_label(), gen.get_editor_property("seed")))
