"""Host side of the mini-golf scenario: drives the running ramms-sim editor through
minigolf_op.py, one op per call, using Scripts/editor_remote_exec.py. Plain Python 3,
stdlib only. The editor must be open with Python Remote Execution enabled.

    python Scripts/pie_tests/minigolf/run_minigolf.py map [--hole 1] [--no-putter] [--friction 0.6,0.005,0.00135]
            [--gen3-bp PATH] [--solref T,D] [--wall-solref T,D] [--wall-friction S,T,R] [--timestep S] [--putter FILE]
        author the level (PIE stopped) -> /Game/Maps/URL/Map_MiniGolf_URL
    python Scripts/pie_tests/minigolf/run_minigolf.py probe [--frame 72]
        start PIE, drive the arm to a stroke pose, print where the bracelet settles relative to the base
    python Scripts/pie_tests/minigolf/run_minigolf.py kick [--kick 1.41]
        launch the ball by its free joint's velocity and report the roll (the rolling-friction calibration)
    python Scripts/pie_tests/minigolf/run_minigolf.py record [--hole 3 --chair 56,104,130 --sim-speed 50]
        the putt: start PIE, approach, play the stroke from frame 72, record -> recordings/hole1 vN.json;
        --chair v_cm_s,fa,fb slides the Gen3 along +x between frames fa and fb (needs the free-base Blueprint)
    python Scripts/pie_tests/minigolf/run_minigolf.py twoputt --hole 2 --chair 60,104,130 --chair2 25,104,130 --sim-speed 50
        a hole played as one recorded sequence of segments: putt, return the arm to its pose at frame 0, drive the Gen3 actor to
        park beside the ball facing the cup, putt again -> recordings/hole2-twoputt vK.json (format ramms-minigolf/3)
    python Scripts/pie_tests/minigolf/run_minigolf.py fitputter [--aim-yaw D] [--out FILE]
        bring the arm to the address pose and write the putter head's pose on the bracelet (data/putter_head.json)
    python Scripts/pie_tests/minigolf/run_minigolf.py stop
        end PIE

Recordings go to recordings/ next to this file (gitignored), numbered and never overwritten.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                        # Scripts/pie_tests
import common  # noqa: E402

OP = HERE / "minigolf_op.py"
BUILD = HERE / "make_minigolf_map.py"
DATA = HERE / "data"
REC = HERE / "recordings"
MAP = "/Game/Maps/URL/Map_MiniGolf_URL"
OP_VAR, OP_TAG = "_minigolf_op", "MINIGOLF"
BUILD_TAG = "MINIGOLFMAP"
# Duplicated from make_minigolf_map.py (HOLES[n]["cup"], the ball0 at (10, Y), and MOUNT), which runs inside the editor and
# cannot be imported here: keep them in step. The sequence's drive needs them to park the arm's base beside the ball.
CUPS = {1: (160.0, -95.0), 2: (160.0, -295.0), 3: (360.0, -95.0)}      # cm, X0 = -40, Y = -95
BALL_OFFSET = (10.0, -95.0)                                          # the ball's start; also where it sits in the chair frame
MOUNT = (-35.0, -8.0, 35.0)                                          # the Gen3 actor's mount, in the chair frame


def op(cmd):
    """One op call: `op("status")`, `op("goto 3 0 0 0 0 0 0 0")`."""
    return common.remote(OP, OP_VAR, cmd, OP_TAG)


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def stroke_degrees(frame):
    return load_json("stroke_hole1.json")["frames"][frame]


def start_pie(map_path=MAP):
    """Start PIE on `map_path` (default the minigolf level). The op stops a running PIE instead of starting, so call again after it did."""
    r = op("start " + map_path)
    if r.get("stopped"):
        time.sleep(2.0)
        r = op("start " + map_path)
    return r


def wait_ready(seconds=90):
    t0 = time.time()
    last = None
    while time.time() - t0 < seconds:
        try:
            st = op("status")
            last = st
            if st.get("ready") and st.get("bound") and st.get("sim", 0) > 1.0:
                return st
            if st.get("initialized") and not st.get("running"):
                op("run")                     # the map comes up paused: no pawn to start the sim
        except RuntimeError as e:
            last = str(e)[-600:]
        time.sleep(1.0)
    raise SystemExit("the sim did not come up in %d s; last: %s" % (seconds, last))


def build_map(a):
    setup = ["unreal._ramms_minigolf_map = %r" % a.map, "unreal._ramms_minigolf_hole = %d" % a.hole,
             "unreal._ramms_minigolf_base_yaw = %r" % a.base_yaw,
             "unreal._ramms_minigolf_friction = %r" % [float(v) for v in a.friction.split(",")]]
    if not a.no_putter:
        setup.append("unreal._ramms_minigolf_putter = %r" % (json.loads(Path(a.putter).read_text(encoding="utf-8")) if a.putter
                                                              else load_json("putter_head.json")))
    if a.gen3_bp:
        setup.append("unreal._ramms_minigolf_gen3_bp = %r" % a.gen3_bp)
    if a.solref:
        setup.append("unreal._ramms_minigolf_contact = %r" % {"solref": [float(v) for v in a.solref.split(",")]})
    if a.wall_solref:
        setup.append("unreal._ramms_minigolf_wall_solref = %r" % [float(v) for v in a.wall_solref.split(",")])
    if a.wall_friction:
        setup.append("unreal._ramms_minigolf_wall_friction = %r" % [float(v) for v in a.wall_friction.split(",")])
    if a.timestep:
        setup.append("unreal._ramms_minigolf_timestep = %r" % a.timestep)
    # The builder takes its parameters from attributes on `unreal`, so this is remote_code (arbitrary editor code) rather
    # than a one-string op.
    code = "import unreal; %s; exec(open(r'%s', encoding='utf-8').read())" % ("; ".join(setup), BUILD)
    line = common.remote_code(code, BUILD_TAG + " ")
    print("[map]", json.loads(line.split(BUILD_TAG + " ", 1)[1]))


def probe(a):
    """Drive the arm to the stroke's pose at --frame and report where the bracelet settles relative to the base."""
    deg = stroke_degrees(a.frame)
    q = [math.radians(d) for d in deg]
    q = [((v + math.pi) % (2 * math.pi)) - math.pi for v in q]      # wrap into the actuators' ctrlrange
    print("[probe] starting PIE", start_pie(a.map))
    st = wait_ready()
    print("[probe] ready: sim %.2f, base %s" % (st["sim"], st["base"]["pos"]))
    info = op("arm")
    print("[probe] actuators", info["actuators"][:8], "joints at rest", info["joints"])
    r = op("probe " + " ".join("%.5f" % v for v in q) + " %g" % a.settle)
    print("[probe] take over", r["take_over"], "applied", r["ctrl_applied"])
    print("[probe] ctrl", [round(v, 3) for v in q], "-> joints", r["joints"], "settled", r["settled_sim_s"])
    print("[probe] bracelet in base (Unreal cm)", r["bracelet_in_base"], "base quat", r["base"]["quat"])
    REC.mkdir(exist_ok=True)
    (REC / ("probe-f%d.json" % a.frame)).write_text(json.dumps({"frame": a.frame, "ctrl": q, "reply": r}, indent=1), encoding="utf-8")


def record(a):
    """Start PIE, bring the arm to the stroke's frame f0 pose, play frames f0..f1 on the sim clock, and keep the per-tick
    recording as recordings/hole<N> vK.json. Prints what the ball did."""
    out = common.next_path(REC, "hole%d" % a.hole)
    start_pie(a.map)
    st = wait_ready()
    time.sleep(2.0)                                       # the control slots exist a moment after the sim reports ready
    if a.sim_speed != 100:
        print("[record] sim speed", op("speed %g" % a.sim_speed))
    q0 = [math.radians(d) for d in stroke_degrees(a.f0)]
    print("[record] ready at sim %.2f; moving to the frame %d pose over %g s" % (st["sim"], a.f0, a.approach))
    print("[record]", op("goto %g " % a.approach + " ".join("%.5f" % v for v in q0))["take_over"])
    time.sleep(a.approach * 100.0 / a.sim_speed + 1.5)    # the approach runs on the sim clock: slower sim, longer wait
    pose = op("pose")
    print("[record] at address: joints", pose["joints"], "bracelet", pose["bracelet"]["pos"])
    print("[record] bodies", op("headbody"))
    chair = ("|" + a.chair.replace(",", "|")) if a.chair else ""
    print("[record]", op("play %s|%d|%d|%s%s" % (DATA / "stroke_hole1.json", a.f0, a.f1, out, chair)))
    while True:
        time.sleep(1.0)
        pr = op("progress")
        if pr["done"]:
            break
        print("[record] frame %.0f, %d samples" % (pr["frame"] or 0, pr["samples"]))
    if pr["error"]:
        raise SystemExit("play failed: %s" % pr["error"])
    rows = json.loads(out.read_text(encoding="utf-8"))["samples"]
    print("[record] %d samples over %.2f s of sim (wall %.2f), written %s" % (len(rows), rows[-1][0] - rows[0][0], rows[-1][1] - rows[0][1], out))
    summarize(rows)
    if not a.keep_pie:
        op("stop")


def twoputt(a):
    """A hole as a two-putt, one recorded sequence (the `sequence` op): the chair-assisted first putt, the arm back to its
    frame 0 pose, the chair (the Gen3 actor) driven to park beside the ball facing the cup, and the same stroke again with an
    optional second slide (--chair2). Waits on `progress`, then prints each putt's ball start, end and z, and the drives.
    -> recordings/hole<N>-twoputt vK.json."""
    out = common.next_path(REC, "hole%d-twoputt" % a.hole)
    REC.mkdir(exist_ok=True)
    start_pie(a.map)
    wait_ready()
    time.sleep(2.0)
    if a.sim_speed != 100:
        print("[twoputt] sim speed", op("speed %g" % a.sim_speed))
    q0 = [math.radians(d) for d in stroke_degrees(a.f0)]
    op("goto %g " % a.approach + " ".join("%.5f" % v for v in q0))
    time.sleep(a.approach * 100.0 / a.sim_speed + 1.5)
    chair = [float(v) for v in a.chair.split(",")] if a.chair else None
    chair2 = [float(v) for v in a.chair2.split(",")] if a.chair2 else None
    spec = {"stroke": str(DATA / "stroke_hole1.json"),
            "segments": [{"play": [a.f0, a.f1], "chair": chair, "hold": 12, "base_yaw": a.base_yaw},
                         {"goto": 0, "seconds": 1.5},
                         {"drive": "ball", "seconds": a.drive_seconds, "cup": list(CUPS[a.hole]), "ball_offset": list(BALL_OFFSET),
                          "mount": list(MOUNT), "base_yaw": a.base_yaw, "hold_frame": 0},
                         {"settle": 0.5},
                         {"play": [a.f0, a.f1], "chair": chair2, "hold": 30, "base_yaw": a.base_yaw}]}
    REC.mkdir(exist_ok=True)
    spec_path = REC / "twoputt_spec.json"
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print("[twoputt]", op("sequence %s|%s" % (spec_path, out)))
    while True:
        time.sleep(1.0)
        pr = op("progress")
        if pr["done"]:
            break
    if pr["error"]:
        raise SystemExit("sequence failed: %s" % pr["error"])
    rec = json.loads(out.read_text(encoding="utf-8"))
    rows = rec["samples"]
    print("[twoputt] %d samples over %.1f s of sim; drives: %s" % (len(rows), rows[-1][0] - rows[0][0],
          [{k: [round(x, 1) for x in v] if isinstance(v, list) else v for k, v in d.items()} for d in rec.get("drives", [])]))
    for seg in (0, 4):                                   # the two play segments
        srows = [r for r in rows if r[9] == seg and r[6]]
        if srows:
            print("[twoputt] segment %d: ball %s -> %s (z %.1f), seq frames %.0f..%.0f" % (
                seg, [round(v, 1) for v in srows[0][6][:3]], [round(v, 1) for v in srows[-1][6][:3]], srows[-1][6][2],
                srows[0][2], srows[-1][2]))
    if not a.keep_pie:
        op("stop")


def kick(a):
    """Launch the ball at --kick m/s down the lane (the free joint's velocity) on a fresh PIE and report the roll: the
    rolling-friction calibration. A free sphere given a pure linear velocity skids to 5/7 of it before it rolls."""
    start_pie(a.map)
    wait_ready()
    time.sleep(1.0)
    print("[kick]", op("kick %g 5" % a.kick))
    time.sleep(7.0)
    r = op("kickresult")
    path = r["path"]
    x0, xe = path[0][1], r["last"][1]
    # the launch speed from the first 0.35 s, the deceleration from the stop distance
    early = [p for p in path if p[0] < 0.35]
    v0 = (early[-1][1] - early[0][1]) / (early[-1][0] - early[0][0]) / 100.0 if len(early) > 1 else float("nan")
    d = (xe - x0) / 100.0
    print("[kick] v0 %.2f m/s (asked %.2f), stopped after %.0f cm: decel %.2f m/s^2; y drift %.1f cm" % (
        v0, a.kick, d * 100, v0 * v0 / (2 * d) if d > 0 else float("nan"), r["last"][2] - path[0][2]))
    if not a.keep_pie:
        op("stop")


def fitputter(a):
    """Measure the putter head's pose on the bracelet: start PIE, bring the arm to the stroke's frame f0 pose, read the
    bracelet, and express the stroke's planned putter transform at that frame (data/stroke_hole1.json "address_putter",
    Unreal cm, chair space) in the bracelet's frame. The head box centre is 4 cm toward the toe and 76 cm down the shaft from
    the putter's origin. --aim-yaw turns the face about world Z. Writes data/putter_head.json (or --out). Re-run after any
    change to the address pose, then rebuild the map."""
    def qmul(p, q):
        x1, y1, z1, w1 = p
        x2, y2, z2, w2 = q
        return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)

    def qinv(q):
        return (-q[0], -q[1], -q[2], q[3])

    def qrot(q, v):
        r = qmul(qmul(q, (v[0], v[1], v[2], 0.0)), qinv(q))
        return (r[0], r[1], r[2])

    start_pie(a.map)
    wait_ready()
    time.sleep(2.0)
    q0 = [math.radians(d) for d in stroke_degrees(a.f0)]
    op("goto %g " % a.approach + " ".join("%.5f" % v for v in q0))
    time.sleep(a.approach + 1.5)
    pose = op("pose")
    pb, qb = tuple(pose["bracelet"]["pos"]), tuple(pose["bracelet"]["quat"])
    fr = load_json("stroke_hole1.json")["address_putter"]
    pp, qp = tuple(fr["loc"]), tuple(fr["quat"])
    rel_q = qmul(qinv(qb), qp)
    rel_p = qrot(qinv(qb), tuple(x - y for x, y in zip(pp, pb)))
    head_local = (4.0, 0.0, -76.0)
    head_rel_p = tuple(x + y for x, y in zip(rel_p, qrot(rel_q, head_local)))
    h = math.radians(a.aim_yaw) / 2.0
    aim = (0.0, 0.0, math.sin(h), math.cos(h))                       # a turn about world Z
    aimed = qmul(qinv(qb), qmul(aim, qmul(qb, rel_q)))
    spec = {"rel_pos": [round(v, 4) for v in head_rel_p], "rel_quat": [round(v, 6) for v in aimed], "size": [10.0, 2.5, 2.0],
            "aim_yaw_deg": a.aim_yaw, "frame": a.f0, "bracelet": {"pos": pb, "quat": qb}, "joints": pose["joints"],
            "note": "Putter head box relative to bracelet_link, measured at the stroke's frame %d pose (run_minigolf.py fitputter), "
                    "the face yawed %.1f deg about world Z. rel_pos is Unreal cm in the bracelet's frame, rel_quat is Unreal "
                    "(x, y, z, w), size is the full box size in cm." % (a.f0, a.aim_yaw)}
    target = Path(a.out) if a.out else DATA / "putter_head.json"
    target.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    print("[fit] bracelet", [round(v, 1) for v in pb], "head rel", spec["rel_pos"], "head world check",
          [round(v, 1) for v in tuple(x + y for x, y in zip(pb, qrot(qb, head_rel_p)))], "planned head", [round(v, 1) for v in fr["head"]])
    print("[fit] wrote", target)
    if not a.keep_pie:
        op("stop")


def summarize(rows):
    """What the ball did: where it started, when it first moved, its peak speed, where it ended; and the head's path.
    Rows are [sim_s, wall_s, frame, joints, bracelet xf, head xf, ball xf], xf = [x y z qx qy qz qw] in Unreal cm."""
    balls = [(r[0], r[2], r[6]) for r in rows if r[6]]
    if not balls:
        print("[record] no ball in the recording")
        return
    x0 = balls[0][2][:3]
    moved = [(t, f, b) for t, f, b in balls if math.dist(b[:3], x0) > 0.3]
    vmax, tmax = 0.0, None
    for (t1, f1, b1), (t2, f2, b2) in zip(balls, balls[1:]):
        if t2 > t1:
            v = math.dist(b1[:3], b2[:3]) / (t2 - t1)
            if v > vmax:
                vmax, tmax = v, (t2, f2)
    end = balls[-1][2][:3]
    print("[ball] start %s, first moved at frame %s, peak %.0f cm/s at frame %s, end %s (%.0f cm from start, z %.1f)" % (
        [round(v, 1) for v in x0], round(moved[0][1], 1) if moved else None, vmax, round(tmax[1], 1) if tmax else None,
        [round(v, 1) for v in end], math.dist(end[:2], x0[:2]), end[2]))
    heads = [(r[2], r[5]) for r in rows if r[5]]
    if heads:
        lo = min(heads, key=lambda h: h[1][2])
        print("[head] lowest z %.1f at frame %.1f; x range %.1f..%.1f" % (lo[1][2], lo[0], min(h[1][0] for h in heads), max(h[1][0] for h in heads)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["map", "probe", "fitputter", "record", "twoputt", "kick", "stop"])
    ap.add_argument("--hole", type=int, default=1, help="map: which hole to build (1-3); record names its file after it")
    ap.add_argument("--map", default=MAP, help="the level: map writes it, probe/record/kick start PIE on it")
    ap.add_argument("--base-yaw", type=float, default=-90.0, help="map: yaw of the Gen3 Blueprint at its mount, degrees")
    ap.add_argument("--no-putter", action="store_true", help="map: leave the putter head out")
    ap.add_argument("--friction", default="0.6,0.005,0.00135", help="map: green and ball friction slide,torsion,roll (MuJoCo units)")
    ap.add_argument("--putter", help="map: a putter head JSON (default data/putter_head.json; data/putter_head_hole3.json aims +2.6 deg)")
    ap.add_argument("--gen3-bp", default="", help="map: the Gen3 Blueprint (default the fixed base; /Game/Robots/URL/gen3_2f85 has the mocap-welded free base the chair-assist stroke needs)")
    ap.add_argument("--solref", default="", help="map: ball and putter-head contact solref 'timeconst,dampratio' (MuJoCo's default 0.02,1 is critically damped)")
    ap.add_argument("--wall-solref", default="", help="map: walls' contact solref 'timeconst,dampratio' (default 0.004,0.3)")
    ap.add_argument("--wall-friction", default="", help="map: walls' friction 'slide,torsion,roll' (default 0.3,0.001,0.0001)")
    ap.add_argument("--timestep", type=float, default=0.0, help="map: the MuJoCo model timestep in s (default 0.002)")
    ap.add_argument("--aim-yaw", type=float, default=0.0, help="fitputter: yaw the face about world Z, degrees (+ turns the face toward +y)")
    ap.add_argument("--out", default="", help="fitputter: write this file instead of data/putter_head.json")
    ap.add_argument("--sim-speed", type=float, default=100.0, help="record: physics sim speed percent (50 halves the per-tick control and mocap steps)")
    ap.add_argument("--chair", default="", help="record: 'v_cm_s,fa,fb': slide the arm's base along +x at v between frames fa and fb (the chair-assist stroke)")
    ap.add_argument("--chair2", default="", help="twoputt: 'v_cm_s,fa,fb' slide on the SECOND putt (along the parked chair's heading)")
    ap.add_argument("--drive-seconds", type=float, default=4.0, help="twoputt: how long the chair takes to park beside the ball")
    ap.add_argument("--f0", type=int, default=72, help="record: first stroke frame (the arm at address)")
    ap.add_argument("--f1", type=int, default=240, help="record: last stroke frame")
    ap.add_argument("--approach", type=float, default=3.0, help="record: seconds to ramp from the start pose to the frame f0 pose")
    ap.add_argument("--keep-pie", action="store_true", help="leave PIE running afterwards")
    ap.add_argument("--kick", type=float, default=1.41, help="kick: the ball's launch speed, m/s")
    ap.add_argument("--frame", type=int, default=72, help="probe: the stroke frame to drive the arm to")
    ap.add_argument("--settle", type=float, default=3.0, help="probe: seconds of sim time to settle")
    a = ap.parse_args()
    if a.cmd == "stop":
        print(op("stop"))
    elif a.cmd == "map":
        build_map(a)
    elif a.cmd == "record":
        record(a)
    elif a.cmd == "twoputt":
        twoputt(a)
    elif a.cmd == "kick":
        kick(a)
    elif a.cmd == "fitputter":
        fitputter(a)
    else:
        probe(a)


if __name__ == "__main__":
    main()
