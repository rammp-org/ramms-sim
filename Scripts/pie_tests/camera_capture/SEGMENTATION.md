# Segmentation capture

Class masks from the camera capture subsystem on a generated world: CameraCapture's segmentation
pass (custom-depth stencil, see its README, "Segmentation") with RammsWorldGen's labels (its README,
"Segmentation labels") and this project's class table (`Config/DefaultGame.ini`,
`[/Script/CameraCapture.CameraCaptureSegmentationSettings]`: 149 fine classes rolling up to 29 coarse
ones, pedestrians as `Person` (actors and the Mass visualizer's distant instances) and the robot as `Robot`,
stencil 200 left to the camera projector).

```
segmentation_capture.py   the PIE run: a camera at the PlayerStart, colour + depth + class masks
                          for a few seconds, then PIE ends (runs inside the editor)
segmentation_preview.py   a 2x2 preview of one frame: colour, overlay, fine and coarse classes (host)
```

## Run

In the editor's Python console, with a generated map open:

```python
import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/camera_capture/"
SEG_SECONDS = 8.0   # optional: SEG_OUT, SEG_EVERY, SEG_W, SEG_H, SEG_F, SEG_Z, SEG_PITCH, SEG_YAW
exec(open(D + "segmentation_capture.py").read())
```

Output goes to `Saved/SegCapture/<map>/` (progress in `Saved/SegCapture/segmentation_capture.log`):
`segmentation_classes.csv` / `.json`, and per frame `frame_N.exr` (colour + depth),
`frame_N_class.png`, `frame_N_class_coarse.png` and `frame_N.json` with the classes in view. Then

```sh
python Scripts/pie_tests/camera_capture/segmentation_preview.py Saved/SegCapture/Map_Gen_Downtown/<actor>/SegCam/frame_0000012
```

The first frame's mask is dropped while `M_SegStencil` compiles (the log says so).

## Results (2026-10-28)

The seven generated maps, one camera 1.2 m above the PlayerStart, 640x480, frame 12 of each run. "Unlabelled" is the share of
pixels that hit geometry (finite depth) but carry no class:

| map | fine classes in view | unlabelled |
| --- | --- | --- |
| Map_Gen_MainStreet | 34 | 0.005 % |
| Map_Gen_Downtown | 35 | 0 % |
| Map_Gen_Suburban | 26 | 0 % |
| Map_Gen_Park | 17 | 0.01 % |
| Map_Gen_Indoor | 8 | 0 % |
| Map_Gen_Store | 16 | 0 % |
| Map_Gen_Office | 7 | 0.03 % |

Foliage is cut out leaf by leaf (the custom-depth pass honours masked materials), and pedestrians and
the robot come out whole. Water and glass are translucent and do not render custom depth, so they show
the class of what is behind them (a pond reads as its `Mud` rim).
