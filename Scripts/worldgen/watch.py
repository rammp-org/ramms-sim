"""Run scripts dropped into Saved/WorldGen/cmd/ inside this editor session.

    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/watch.py").read())

Every 2 s the editor looks for *.py files in Saved/WorldGen/cmd/, runs each once
(oldest first) on the game thread and renames it to *.done (or *.failed, with the
traceback in *.log). Lets an external tool drive the editor without UI focus.
Re-running this file replaces the previous watcher.
"""
import glob, os, time, traceback
import unreal

_CMD = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "WorldGen", "cmd")
os.makedirs(_CMD, exist_ok=True)
_w = globals().setdefault("_RAMMS_WATCH", {"handle": None, "next": 0.0})
if _w.get("handle") is not None:
    try:
        unreal.unregister_slate_post_tick_callback(_w["handle"])
    except Exception:
        pass


def _ramms_watch_tick(dt):
    if time.time() < _w["next"]:
        return
    _w["next"] = time.time() + 2.0
    for path in sorted(glob.glob(os.path.join(_CMD, "*.py")), key=os.path.getmtime):
        base = path[:-3]
        try:
            src = open(path, encoding="utf-8").read()
            os.replace(path, base + ".running")
            unreal.log("[watch] running %s" % os.path.basename(path))
            exec(compile(src, path, "exec"), globals())
            os.replace(base + ".running", base + ".done")
        except Exception:
            tb = traceback.format_exc()
            unreal.log_warning("[watch] %s failed:\n%s" % (os.path.basename(path), tb))
            open(base + ".log", "w").write(tb)
            if os.path.exists(base + ".running"):
                os.replace(base + ".running", base + ".failed")
        break  # one script per tick; long ones register their own callbacks


_w["handle"] = unreal.register_slate_post_tick_callback(_ramms_watch_tick)
unreal.log("[watch] watching %s" % _CMD)
