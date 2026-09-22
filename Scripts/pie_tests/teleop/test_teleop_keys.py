"""Hold real keys and check keyboard teleop acts on them.

The companion test (test_teleop_surface.py) covers discovery -- that teleop
finds the surface and its controls. This covers the half underneath: that
teleop's own tick path reads the keyboard and writes the controls.

It works because teleop POLLS. Every tick it asks IsInputKeyDown, so a single
injected press reads as held on every later frame until a release is injected;
there is no need to fake a key repeat per frame.

Key injection comes from URammsInputTestLibrary (editor only), because
APlayerController::InputKey is not BlueprintCallable and Python exposes only
the read side of the key API.

Two phases, because sampling needs ticks between them:

    unreal._ramms_key_phase = "arm"      # press the key, start sampling
    unreal._ramms_key_phase = "report"   # release, assert, print

Run inside the editor with PIE on a teleop test level:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/teleop/test_teleop_keys.py
"""

import unreal

PHASE = getattr(unreal, "_ramms_key_phase", "arm")
DRIVE_ID = unreal.Name("drive.forward")
SAMPLE_FRAMES = 45

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("no PIE world -- start play on a teleop test level first")

pawn = next((a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
             if a.get_component_by_class(unreal.RammsKeyboardTeleopComponent)), None)
if pawn is None:
    raise RuntimeError("no pawn with a teleop component in this level")
surface = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
pc = unreal.GameplayStatics.get_player_controller(world, 0)
lib = unreal.RammsInputTestLibrary


def stop_sampler():
    h = getattr(unreal, "_ramms_key_h", None)
    if h is not None:
        try:
            unreal.unregister_slate_post_tick_callback(h)
        except Exception:
            pass
        unreal._ramms_key_h = None


if PHASE == "arm":
    stop_sampler()
    if pc is None:
        raise RuntimeError("no player controller to deliver keys to")
    # Whatever a previous run left held, so a failure does not poison this one.
    lib.release_all_injected_keys(pc)

    delivered = lib.set_key_down(pc, "W", True)
    print("[keys] W delivered=%s" % delivered)

    # Not sampled here: IsInputKeyDown still reads false immediately after the
    # injection, because PlayerInput folds the event into its state during the
    # frame's input processing. By the first tick it reads as held, which is
    # also when teleop polls it -- so sample it there.
    unreal._ramms_key_data = {"delivered": delivered, "held": None, "samples": []}
    st = {"n": 0}

    def sample(dt):
        st["n"] += 1
        if unreal._ramms_key_data["held"] is None:
            unreal._ramms_key_data["held"] = lib.is_key_down(pc, "W")
        unreal._ramms_key_data["samples"].append(surface.get_control_value(DRIVE_ID))
        if st["n"] >= SAMPLE_FRAMES:
            # Release from inside the callback: if the report phase never runs,
            # the key must not stay stuck down.
            lib.set_key_down(pc, "W", False)
            stop_sampler()

    unreal._ramms_key_h = unreal.register_slate_post_tick_callback(sample)
    print("[keys] armed -- sampling drive.forward for %d frames" % SAMPLE_FRAMES)

else:
    stop_sampler()
    if pc is not None:
        lib.release_all_injected_keys(pc)
    d = getattr(unreal, "_ramms_key_data", None)
    if not d:
        raise RuntimeError("nothing sampled -- run the arm phase first")

    s = d["samples"]
    failures = []

    def check(ok, msg):
        print("[keys] %s %s" % ("PASS" if ok else "FAIL", msg))
        if not ok:
            failures.append(msg)

    check(d["delivered"], "the player controller accepted the injected key")
    check(d["held"], "the key read as held on the first tick (what teleop polls)")
    check(len(s) > 0, "sampled %d frames while the key was held" % len(s))
    peak = max(s) if s else 0.0
    check(peak > 0.0,
          "teleop drove drive.forward while W was held (peak %.3f)" % peak)

    # After the release the sampler stops, so the tail of the samples is still
    # the held value; what matters is that teleop wrote at all.
    print("[keys] drive.forward: first=%.3f peak=%.3f last=%.3f"
          % (s[0] if s else -1, peak, s[-1] if s else -1))
    after = surface.get_control_value(DRIVE_ID)
    check(not lib.is_key_down(pc, "W"),
          "W reads as released afterwards (drive.forward now %.3f)" % after)

    print("[keys] ---- %d checks failed ----" % len(failures))
    for f in failures:
        print("[keys] FAILED: %s" % f)
