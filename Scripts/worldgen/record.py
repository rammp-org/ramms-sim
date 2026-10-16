"""Record short clips of a generated level with its crowd walking (Simulate in the editor).

    REC_MAP = "/Game/Maps/Gen/Map_Gen_Office"
    REC_SHOTS = [("office_corridor", (x, y, z), (pitch, yaw), (x2, y2, z2), (pitch2, yaw2), seconds), ...]
    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/record.py").read())

Each shot dollies the editor camera from the first pose to the second over `seconds` of video while
capturing frames (HighResShot, 1280x720) into Saved/WorldGen/video/<shot>/f_####.png. A screenshot takes
a few hundred ms, so the simulation runs in slow motion (global time dilation REC_SLOMO, default 0.25) and
times.txt records the game time of each frame: assemble with ffmpeg at frames / game seconds.
"""
import os
import time
import unreal


def _start_record(map_path, shots, warmup, slomo, fps):
    root = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "WorldGen", "video").replace("\\", "/")
    s = {"phase": "load", "until": 0.0, "i": 0, "f": 0, "t0": 0.0, "h": None, "times": [], "g0": 0.0}
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

    def lerp(a, b, t):
        return [a[k] + (b[k] - a[k]) * t for k in range(len(a))]

    def cam(shot, t):
        _n, p0, r0, p1, r1, _d = shot
        p = lerp(p0, p1, t)
        r = lerp(r0, r1, t)
        ues.set_level_viewport_camera_info(unreal.Vector(*p), unreal.Rotator(roll=0.0, pitch=r[0], yaw=r[1]))

    def tick(dt):
        now = time.time()
        if now < s["until"]:
            return
        try:
            if s["phase"] == "load":
                les.load_level(map_path)
                s["phase"] = "sim"; s["until"] = now + 2.0
            elif s["phase"] == "sim":
                unreal.SystemLibrary.execute_console_command(None, "ShowFlag.ZoneGraph 0")
                cam(shots[0], 0.0)
                les.editor_play_simulate()
                s["phase"] = "warm"; s["until"] = now + warmup
            elif s["phase"] == "warm":
                gw = ues.get_game_world()
                if gw:
                    unreal.GameplayStatics.set_global_time_dilation(gw, slomo)
                s["phase"] = "shot"; s["f"] = 0; s["t0"] = now; s["times"] = []
                s["g0"] = unreal.GameplayStatics.get_time_seconds(gw) if gw else 0.0
                os.makedirs(os.path.join(root, shots[s["i"]][0]), exist_ok=True)
            elif s["phase"] == "shot":
                shot = shots[s["i"]]
                nframes = max(2, int(shot[5] * fps))
                t = s["f"] / (nframes - 1)
                if s["f"] >= nframes:
                    with open(os.path.join(root, shot[0], "times.txt"), "w") as fh:
                        fh.write("\n".join("%.4f" % x for x in s["times"]))
                    s["i"] += 1
                    if s["i"] >= len(shots):
                        les.editor_request_end_play()
                        unreal.unregister_slate_post_tick_callback(s["h"])
                        unreal.log("[record] done %s" % map_path)
                        return
                    s["phase"] = "warm"; s["until"] = now + 0.5
                    cam(shots[s["i"]], 0.0)
                    return
                cam(shot, t)
                unreal.SystemLibrary.execute_console_command(None, "HighResShot 1280x720 filename=%s/%s/f_%04d.png" % (root, shot[0], s["f"]))
                gw = ues.get_game_world()
                s["times"].append((unreal.GameplayStatics.get_time_seconds(gw) - s["g0"]) if gw else now - s["t0"])
                s["f"] += 1
                s["until"] = now + 0.02
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning("[record] %s" % exc)
            try:
                les.editor_request_end_play()
            except Exception:  # noqa: BLE001
                pass
            unreal.unregister_slate_post_tick_callback(s["h"])

    s["h"] = unreal.register_slate_post_tick_callback(tick)


_start_record(globals().get("REC_MAP"), list(globals().get("REC_SHOTS", [])), float(globals().get("REC_WARMUP", 6.0)),
              float(globals().get("REC_SLOMO", 0.25)), float(globals().get("REC_FPS", 12.0)))
for _k in ("REC_MAP", "REC_SHOTS", "REC_WARMUP", "REC_SLOMO", "REC_FPS"):
    globals().pop(_k, None)
