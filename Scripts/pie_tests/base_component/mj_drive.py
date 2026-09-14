import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
a.get_component_by_class(unreal.RammsDifferentialDriveController).set_drive_input(unreal.Vector2D(0.0, 1.0))
unreal.log("[drv] set_drive_input forward")
