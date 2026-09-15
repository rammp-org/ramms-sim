#!/usr/bin/env python3
"""Send ramms-access v1 intent packets (UDP JSON) to a running RAMMS instance.

usage: access_send.py [--port 30040] [--hz 30] [--seconds 1.5]
                      [--drive X Y] [--ee-lin X Y Z] [--ee-ang P Y R] [--event NAME]...
Streams the same packet at --hz for --seconds (the component's watchdog needs a
live stream), then stops. Run from the host, no editor Python involved."""
import argparse, json, random, socket, time

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=30040)
ap.add_argument("--hz", type=float, default=30.0)
ap.add_argument("--seconds", type=float, default=1.5)
ap.add_argument("--drive", type=float, nargs=2, metavar=("X", "Y"))
ap.add_argument("--ee-lin", type=float, nargs=3, metavar=("X", "Y", "Z"))
ap.add_argument("--ee-ang", type=float, nargs=3, metavar=("P", "Y", "R"))
ap.add_argument("--conf", type=float, default=1.0)
ap.add_argument("--event", action="append", default=[])
a = ap.parse_args()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sid = random.randint(1, 2**31)
seq = 0
n = max(1, int(a.hz * a.seconds))
for i in range(n):
    seq += 1
    pkt = {"v": 1, "src": "access_send", "seq": seq, "sid": sid, "conf": a.conf}
    if a.drive:
        pkt["drive"] = {"x": a.drive[0], "y": a.drive[1]}
    ee = {}
    if a.ee_lin:
        ee["lin"] = a.ee_lin
    if a.ee_ang:
        ee["ang"] = a.ee_ang
    if ee:
        pkt["ee"] = ee
    if i == 0 and a.event:
        pkt["events"] = a.event
    sock.sendto(json.dumps(pkt).encode(), ("127.0.0.1", a.port))
    time.sleep(1.0 / a.hz)
print("sent %d packets (sid %d)" % (n, sid))
