import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
# The keyboard teleop component re-issues the (idle) key state every tick and
# would overwrite a scripted drive input: pause it for the test.
tele = a.get_component_by_class(unreal.RammsKeyboardTeleopComponent)
if tele:
    tele.set_component_tick_enabled(False)
a.get_component_by_class(unreal.RammsDifferentialDriveController).set_drive_input(unreal.Vector2D(0.0, 1.0))
unreal.log("[drv] set_drive_input forward (teleop tick paused=%s)" % (tele is not None))
