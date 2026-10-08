"""Assert that depth and motion actually TRACK a moving camera.

moving_camera_depth.py drives the camera and writes files; this is the half that
decides whether the result is right. The two were documented as a pair and only
the first half existed, so the regression it describes had no assertion behind
it.

The bug it guards: a pooled FRHIGPUTextureReadback arrived with its fence still
signalled from a previous use, so the harvest read an earlier frame's staging
buffer -- forever. Colour kept updating while depth froze on the first frame it
ever captured. A static scene cannot see that, because the depth of a still
scene is legitimately identical every frame; the camera has to move, and the
check has to prove the depth CHANGED rather than merely that it exists.

    python3 Scripts/pie_tests/camera_capture/verify_moving_capture.py <camera dir>
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_capture_output import read_exr


def main(camera_dir):
    frames = sorted(f for f in os.listdir(camera_dir) if f.endswith(".json"))
    if len(frames) < 3:
        print("FAIL: need at least 3 frames to say anything about change, found %d" % len(frames))
        return 1

    fails = []

    def check(ok, what):
        print("  %s  %s" % ("pass" if ok else "FAIL", what))
        if not ok:
            fails.append(what)

    stems = [f[:-len(".json")] for f in frames]
    print("%d frames in %s" % (len(stems), camera_dir))

    # Did the camera actually move? Without this the rest proves nothing: a
    # stationary camera SHOULD give identical depth, so identical depth would
    # look like the bug.
    locs = []
    for stem in stems:
        meta = json.load(open(os.path.join(camera_dir, stem + ".json")))
        locs.append(tuple(meta["world_transform"]["location"]))
    moved = max(abs(a - b) for first, last in [(locs[0], locs[-1])] for a, b in zip(first, last))
    print("  camera moved %.1f cm between the first and last frame" % moved)
    check(moved > 10.0, "the camera really moved, so identical depth would be a fault")

    # Depth must differ between frames. Hashing the whole plane is what caught
    # the original: byte-identical EXRs across every frame of a moving capture.
    depth_sigs = []
    motion_nonzero = []
    missing_motion = []
    for stem in stems:
        meta = json.load(open(os.path.join(camera_dir, stem + ".json")))
        dpath = os.path.join(camera_dir, stem + "_depth.exr")
        src = dpath if os.path.exists(dpath) else os.path.join(camera_dir, stem + ".exr")
        _, _, chans = read_exr(src)
        plane = chans.get("R") if os.path.exists(dpath) else chans.get("A")
        if not plane:
            continue
        depth_sigs.append(hash(tuple(plane[::97])))

        # A missing motion file is a failure, not a skip. Skipping left
        # motion_nonzero empty when every file was absent, and the run then
        # passed on depth alone -- the same hole that was just closed in
        # verify_capture_output, reintroduced here by writing this file from
        # scratch rather than from that one.
        mpath = os.path.join(camera_dir, stem + "_motion.exr")
        if meta.get("motion_width") and meta.get("motion_height"):
            if not os.path.exists(mpath):
                missing_motion.append(stem)
                continue
            _, _, mch = read_exr(mpath)
            r, g = mch.get("R", []), mch.get("G", [])
            motion_nonzero.append(sum(1 for i in range(0, len(r), 37) if r[i] or g[i]))

    distinct = len(set(depth_sigs))
    print("  %d distinct depth planes across %d frames" % (distinct, len(depth_sigs)))
    check(distinct > 1, "depth changes as the camera moves (frozen depth gave exactly 1)")
    check(distinct >= max(2, len(depth_sigs) // 3),
          "depth changes on most frames, not just once (%d of %d)" % (distinct, len(depth_sigs)))

    check(not missing_motion,
          "every frame whose metadata declares a motion grid has a motion EXR (%d missing)"
          % len(missing_motion))

    if motion_nonzero:
        total = sum(motion_nonzero)
        print("  motion vectors non-zero at %d sampled pixels across %d frames"
              % (total, len(motion_nonzero)))
        check(total > 0, "motion vectors are not uniformly zero while the camera moves")

    print("%s (%d failing)" % ("ALL GREEN" if not fails else "FAILURES", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
