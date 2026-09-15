"""Exercise the auto-spawned control HUD (ramms-ui URammsControlHUDSubsystem).

unreal._ramms_hud_op: 'status' | 'shot <name>' (high-res screenshot to
Saved/Screenshots) | 'joystick <x> <y>' (simulate the drive joystick) |
'joystick_release' | 'row <control id> <value>' (drive a slider row) |
'action <control id>' (click an action row) | 'hold <control id> <+|->'
(press a rate row's hold button) | 'release <control id>'."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, pawn = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(pawn)
op = getattr(unreal, "_ramms_hud_op", "status").split()
def log(s): unreal.log("[hud] " + s)
hud = unreal.RammsControlHUDSubsystem.get(pawn)
if hud is None:
    raise RuntimeError("[hud] no RammsControlHUDSubsystem for the local player")
host, panel, joy = hud.get_host(), hud.get_surface_panel(), hud.get_joystick()
hosts, panels, joys = [x for x in (host,) if x], [x for x in (panel,) if x], [x for x in (joy,) if x]
if op[0] == "status":
    log("hosts=%d panels=%d drive joysticks=%d rows=%s target=%s in_viewport=%s" % (
        len(hosts), len(panels), len(joys),
        panel.get_row_count() if panel else None, panel.get_target_surface().get_outer().get_name() if panel and panel.get_target_surface() else None,
        host.is_in_viewport() if host else None))
    if not (host and panel and joy and panel.get_row_count() > 0):
        raise RuntimeError("[hud] HUD not fully spawned")
elif op[0] == "row_state":
    row = panel.find_row(op[1])
    if not row:
        raise RuntimeError("[hud] no row for %s" % op[1])
    r = cs.get_control_target(op[1])  # None when no target; else the out value (or (bool, value))
    tgt = None if r is None else (r[1] if isinstance(r, tuple) else r)
    log("%s: slider(target)=%.2f surface target=%s live=%.2f" % (op[1], row.get_target_value(), "none" if tgt is None else "%.2f" % tgt, cs.get_control_value(op[1])))
elif op[0] == "layout":
    for line in panel.get_layout_report():
        log("  " + str(line))
elif op[0] == "scroll_to":
    panel.set_scroll_offset(float(op[1]))
    log("scroll_to %s -> offset %.1f" % (op[1], panel.get_scroll_offset()))
elif op[0] == "scroll":
    ext = panel.get_scroll_extent()
    cam = pawn.get_component_by_class(unreal.RammsRobotCameraComponent)
    log("panel scroll offset = %.1f (list height %.0f, end %.0f) ; camera over-UI=%s" % (panel.get_scroll_offset(), ext.x, ext.y, "%s/%s" % (cam.is_cursor_over_ui(), cam.get_widget_type_under_cursor()) if cam else None))
elif op[0] == "camera_state":
    cam = pawn.get_component_by_class(unreal.RammsRobotCameraComponent)
    arm = [c for c in pawn.get_components_by_class(unreal.SpringArmComponent) if c.get_name() == "FollowArm"]
    rot = arm[0].get_relative_transform().rotation.rotator() if arm else None
    log("camera arm=%.1f yaw=%.1f pitch=%.1f" % (cam.get_desired_arm_length(), rot.yaw if rot else 0.0, rot.pitch if rot else 0.0))
elif op[0] == "shot":
    # 'Shot showui' captures the viewport with Slate UI (HighResShot omits it).
    unreal.SystemLibrary.execute_console_command(w, "Shot showui")
    log("screenshot (with UI) requested; see Saved/Screenshots/MacEditor")
elif op[0] == "joystick":
    joy.simulate_input(unreal.Vector2D(float(op[1]), float(op[2])))
    log("joystick (%s, %s) -> drive.forward=%.2f drive.turn=%.2f" % (op[1], op[2], cs.get_control_value("drive.forward"), cs.get_control_value("drive.turn")))
elif op[0] == "joystick_release":
    joy.simulate_release()
    log("joystick released -> drive.forward=%.2f" % cs.get_control_value("drive.forward"))
elif op[0] == "row":
    row = panel.find_row(op[1])
    if not row:
        raise RuntimeError("[hud] no row for %s" % op[1])
    row.simulate_value(float(op[2]))
    log("row %s -> %s ; surface now %.3f" % (op[1], op[2], cs.get_control_value(op[1])))
elif op[0] == "action":
    row = panel.find_row(op[1])
    if not row:
        raise RuntimeError("[hud] no row for %s" % op[1])
    row.simulate_action()
    log("action %s clicked" % op[1])
elif op[0] in ("hold", "release"):
    row = panel.find_row(op[1])
    if not row:
        raise RuntimeError("[hud] no row for %s" % op[1])
    if op[0] == "hold":
        row.simulate_hold(len(op) > 2 and op[2] == "+")
    else:
        row.simulate_release()
    log("%s %s -> value %.2f" % (op[0], op[1], cs.get_control_value(op[1])))
