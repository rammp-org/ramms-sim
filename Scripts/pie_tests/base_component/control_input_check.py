"""Exercise the pawn's RammsControlInputComponent (Enhanced Input -> surface).

unreal._ramms_ci_op: 'status' | 'inject <IA name> <x> <y> <z> [hold_s]' |
'expect <control id> <min> <max>' (fails when the surface value is outside) |
'mark <control id>' then 'expect_change <control id> <min> <max>' (its change since) |
'pad_axis <key> <v> [<key> <v> ...]' | 'pad_key <key> <down|up>' | 'pad_release'
(a gamepad at its keys) | 'pad_hold <s> <key> <v> [...]' (held for s of game time,
let go by the editor) | 'owner <control id> <source>' (fails on another holder)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, pawn = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(pawn)
ci = pawn.get_component_by_class(unreal.RammsControlInputComponent)
op = getattr(unreal, "_ramms_ci_op", "status").split()
def log(s): unreal.log("[ci] " + s)
if not ci:
    raise RuntimeError("no RammsControlInputComponent on %s" % pawn.get_name())
if op[0] == "status":
    maps = [m.get_name() for m in ci.get_editor_property("input_maps")]
    log("bound=%s maps=%s actions=%s" % (ci.is_bound(), maps, [str(a) for a in ci.get_bound_action_names()]))
    if not ci.is_bound():
        raise RuntimeError("[ci] input component is not bound to the player's Enhanced Input component")
elif op[0] == "inject":
    hold = float(op[5]) if len(op) > 5 else 0.0
    ok = ci.inject_action_by_name(op[1], unreal.Vector(float(op[2]), float(op[3]), float(op[4])), hold)
    log("inject %s (%s, %s, %s) hold %.1fs -> %s" % (op[1], op[2], op[3], op[4], hold, ok))
    if not ok:
        raise RuntimeError("[ci] %s is not bound by any input map" % op[1])
elif op[0] == "camera":
    cam = pawn.get_component_by_class(unreal.RammsRobotCameraComponent)
    active = cam.get_active_camera() if cam else None
    log("active camera: %s" % (active.get_name() if active else None))
    unreal._ramms_ci_cam_prev = getattr(unreal, "_ramms_ci_cam", None)
    unreal._ramms_ci_cam = active.get_name() if active else None
elif op[0] == "camera_changed":
    if unreal._ramms_ci_cam == unreal._ramms_ci_cam_prev:
        raise RuntimeError("[ci] camera did not change (%s)" % unreal._ramms_ci_cam)
    log("camera changed %s -> %s" % (unreal._ramms_ci_cam_prev, unreal._ramms_ci_cam))
elif op[0] == "urlab":
    m = [x for x in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor) if x.get_class().get_name() == "AMjManager"]
    if not m:
        log("no AMjManager in this world")
    else:
        m = m[0]
        ih = m.get_editor_property("input_handler")
        ticking = ih.is_component_tick_enabled() if ih else None
        log("URLab InputHandler ticking=%s" % ticking)
        if ticking:
            raise RuntimeError("[ci] URLab hotkeys are still enabled")
elif op[0] == "expect":
    v = cs.get_control_value(op[1])
    lo, hi = float(op[2]), float(op[3])
    log("%s = %.3f (expect %.2f..%.2f) -> %s" % (op[1], v, lo, hi, "ok" if lo <= v <= hi else "FAIL"))
    if not (lo <= v <= hi):
        raise RuntimeError("[ci] %s = %.3f outside %.2f..%.2f" % (op[1], v, lo, hi))
elif op[0] == "mark":
    unreal._ramms_ci_mark = (op[1], cs.get_control_value(op[1]))
    log("mark %s = %.3f" % unreal._ramms_ci_mark)
elif op[0] == "expect_change":
    mid, v0 = getattr(unreal, "_ramms_ci_mark", (None, 0.0))
    if mid != op[1]:
        raise RuntimeError("[ci] no mark on %s (mark it first)" % op[1])
    d = cs.get_control_value(op[1]) - v0
    lo, hi = float(op[2]), float(op[3])
    log("%s changed %+.3f since the mark (expect %.2f..%.2f) -> %s" % (op[1], d, lo, hi, "ok" if lo <= d <= hi else "FAIL"))
    if not (lo <= d <= hi):
        raise RuntimeError("[ci] %s changed %.3f, outside %.2f..%.2f" % (op[1], d, lo, hi))
elif op[0] in ("pad_axis", "pad_key", "pad_release", "pad_hold"):
    # A gamepad at its keys (URammsInputTestLibrary), so Enhanced Input sees
    # the pad itself: the context's dead zones and swizzles, held buttons, and
    # the device the input component reports. An axis stays where it is put.
    pc = unreal.GameplayStatics.get_player_controller(w, 0)
    if pc is None:
        raise RuntimeError("[ci] no player controller")
    lib = unreal.RammsInputTestLibrary

    def press(k, down):
        # The name checked first: SetKeyDown's result is whether the
        # controller consumed the key, false for a key Enhanced Input took,
        # so it cannot tell a misspelled name from a delivered press.
        key = unreal.Key()
        key.import_text(k)
        if not unreal.InputLibrary.key_is_valid(key):
            raise RuntimeError("[ci] %s is not a key's name" % k)
        lib.set_key_down(pc, unreal.Name(k), down)

    if op[0] == "pad_axis":
        for k, v in zip(op[1::2], op[2::2]):
            if not lib.set_axis_key(pc, unreal.Name(k), float(v)):
                raise RuntimeError("[ci] %s is not an analog key" % k)
        log("pad axes %s" % " ".join(op[1:]))
    elif op[0] == "pad_key":
        if op[2] not in ("down", "up"):
            raise RuntimeError("[ci] pad_key %s: down or up, not %s" % (op[1], op[2]))
        press(op[1], op[2] == "down")
        log("pad %s %s" % (op[1], op[2]))
    elif op[0] == "pad_hold":
        # Held for a fixed stretch of game time and let go by the editor's own
        # tick, so the remote calls around it add nothing to the hold: an
        # analog key at its value, a button down for any nonzero value.
        seconds, held = float(op[1]), []
        for k, v in zip(op[2::2], op[3::2]):
            if lib.set_axis_key(pc, unreal.Name(k), float(v)):
                held.append((k, True))
            else:
                press(k, float(v) != 0.0)
                held.append((k, False))
        until = unreal.GameplayStatics.get_time_seconds(w) + seconds
        handle = [None]

        def let_go(_dt):
            try:
                if unreal.GameplayStatics.get_time_seconds(w) < until:
                    return
                for k, analog in held:
                    if analog:
                        lib.set_axis_key(pc, unreal.Name(k), 0.0)
                    else:
                        lib.set_key_down(pc, unreal.Name(k), False)
            except Exception:
                pass  # PIE ended: nothing left to let go of
            unreal.unregister_slate_post_tick_callback(handle[0])

        handle[0] = unreal.register_slate_post_tick_callback(let_go)
        log("pad %s held for %.2f s of game time" % (" ".join(op[2:]), seconds))
    else:
        lib.release_all_injected_keys(pc)
        log("pad released")
elif op[0] == "owner":
    # Who holds a control: 'owner <control id> <keyboard|gamepad|touch|remote|autonomy|script>'.
    got = cs.get_axis_owner(op[1])
    name = getattr(got, "name", str(got)).lower()
    log("%s held by %s (expect %s) -> %s" % (op[1], name, op[2], "ok" if name == op[2] else "FAIL"))
    if name != op[2]:
        raise RuntimeError("[ci] %s held by %s, expected %s" % (op[1], name, op[2]))
