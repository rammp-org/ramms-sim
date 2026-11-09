#!/usr/bin/env python3
"""RMSS -> ROS 2 bridge for the RAMMS sim cameras.

Connects to the RammsStreaming server (TCP 30030, see Plugins/RammsStreaming/README.md) and
republishes every camera it streams:

  /<ns>/cam/<name>/image_raw          sensor_msgs/Image (bgr8)
  /<ns>/cam/<name>/image_raw/compressed  sensor_msgs/CompressedImage (jpeg), if compressed:=true
  /<ns>/cam/<name>/preview/compressed    small JPEG for live viewing (Foxglove), preview_scale (0.5);
                                      0 disables it
  /<ns>/cam/<name>/camera_info        sensor_msgs/CameraInfo ("equidistant" = OpenCV fisheye for
                                      fisheye cameras, "plumb_bob" with zero D for pinholes)
  /<ns>/cam/<name>/depth              sensor_msgs/Image (32FC1, metres), when the sim streams depth
  /tf_static                          base_link -> <name>_link -> <name>_optical (REP-103)
  /tf, /<ns>/odom/ground_truth        odom -> base_link from the sim's true robot pose

All cameras captured on the same sim frame carry the same stamp (the sim's kick time).
Run through run_bridge.sh, which sources ROS 2 and avoids the user site-packages.
"""
import array
import json
import math
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster

HEADER = struct.Struct("<4sBBHHIqII2s")  # 32 bytes, little-endian
MAGIC = b"RMSS"
FRAME_RGB, FRAME_DEPTH, FRAME_RGBD = 0x01, 0x02, 0x03
COMP_NONE, COMP_LZ4, COMP_JPEG, COMP_PNG = 0, 1, 2, 3

# camera link (x fwd, y left, z up) -> optical (z fwd, x right, y down)
Q_LINK_TO_OPTICAL = (-0.5, 0.5, -0.5, 0.5)


def ue_pose_to_ros(p):
    """UE pose (cm, left-handed: x fwd, y right, z up) -> ROS (m, x fwd, y left, z up), quat xyzw."""
    f = {k: float(p[k]) for k in ("x", "y", "z", "qx", "qy", "qz", "qw")}  # JSON may hold ints
    return ((f["x"] / 100.0, -f["y"] / 100.0, f["z"] / 100.0),
            (-f["qx"], f["qy"], -f["qz"], f["qw"]))


def as_u8(buf):
    """uint8[] message fields take array('B') as-is; bytes or ndarrays are checked element by element
    in Python (~0.3 s for one 6.9 MB image)."""
    a = array.array("B")
    a.frombytes(buf if isinstance(buf, (bytes, bytearray)) else memoryview(buf).cast("B"))
    return a


def recv_exact(sock, n):
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        k = sock.recv_into(view[got:], n - got)
        if k == 0:
            raise ConnectionError("RMSS server closed the connection")
        got += k
    return buf


def decode_image(comp, payload, w, h):
    """Returns an HxWx3 BGR uint8 array."""
    if comp == COMP_NONE:
        return np.frombuffer(payload, np.uint8, w * h * 4).reshape(h, w, 4)[:, :, :3]
    import cv2
    return cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)


def decode_depth_m(comp, payload, w, h):
    if comp == COMP_LZ4:
        import lz4.block
        payload = lz4.block.decompress(bytes(payload), uncompressed_size=w * h * 4)
    return np.frombuffer(payload, np.float32, w * h).reshape(h, w) / 100.0  # cm -> m


class RmssRosBridge(Node):
    def __init__(self):
        super().__init__("ramms_ros_bridge")
        self.host = self.declare_parameter("host", "127.0.0.1").value
        self.port = self.declare_parameter("port", 30030).value
        self.ns = self.declare_parameter("namespace", "rammp_gen1").value.strip("/")
        self.base_frame = self.declare_parameter("base_frame", "base_link").value
        self.odom_frame = self.declare_parameter("odom_frame", "odom").value
        self.compressed = self.declare_parameter("compressed", False).value
        self.jpeg_quality = self.declare_parameter("jpeg_quality", 85).value
        self.publish_raw = self.declare_parameter("publish_raw", True).value
        self.preview_scale = float(self.declare_parameter("preview_scale", 0.5).value)

        self.qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.cams = {}  # name -> dict(pubs, extrinsics key)
        self.static_tf = StaticTransformBroadcaster(self)
        self.static_list = {}
        self.tf = TransformBroadcaster(self)
        self.odom_pub = self.create_publisher(Odometry, f"/{self.ns}/odom/ground_truth", 10)
        self.last_odom_frame = None
        self.prev_odom = None
        self.stats = {}
        self.latest = {}  # camera set -> newest unpublished kick {(type, camera): frame}
        self.meta_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=int(self.declare_parameter("workers", 6).value))
        self.dropped = 0
        self.cv = threading.Condition()
        self.create_timer(5.0, self.report)

    # ------------------------------------------------------------------ helpers
    def cam(self, name):
        c = self.cams.get(name)
        if c is None:
            base = f"/{self.ns}/cam/{name}"
            c = {
                "image": self.create_publisher(Image, f"{base}/image_raw", self.qos),
                "info": self.create_publisher(CameraInfo, f"{base}/camera_info", self.qos),
                "depth": self.create_publisher(Image, f"{base}/depth", self.qos),
                "comp": self.create_publisher(CompressedImage, f"{base}/image_raw/compressed", self.qos)
                if self.compressed else None,
                "preview": self.create_publisher(CompressedImage, f"{base}/preview/compressed", self.qos)
                if self.preview_scale > 0 else None,
                "extr": None,
            }
            self.cams[name] = c
            self.get_logger().info(f"new camera '{name}' -> {base}/...")
        return c

    def stamp(self, meta, header_ts_us):
        t = meta.get("unix_time") or header_ts_us * 1e-6
        sec = int(t)
        return Time(seconds=sec, nanoseconds=int((t - sec) * 1e9)).to_msg()

    def camera_info(self, meta, stamp, frame_id, w, h):
        intr = meta.get("intrinsics", {})
        sx = w / max(intr.get("res_x", w), 1)
        sy = h / max(intr.get("res_y", h), 1)
        fx, fy = intr.get("fx", w / 2) * sx, intr.get("fy", w / 2) * sy
        cx, cy = intr.get("cx", w / 2) * sx, intr.get("cy", h / 2) * sy
        m = CameraInfo()
        m.header.stamp, m.header.frame_id = stamp, frame_id
        m.width, m.height = w, h
        dist = meta.get("distortion")
        if dist and dist.get("model") == "equidistant":
            m.distortion_model = "equidistant"
            m.d = [float(k) for k in dist["k"][:4]]
        else:
            m.distortion_model = "plumb_bob"
            m.d = [0.0] * 5
        m.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
        m.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        m.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        return m

    def update_static_tf(self, name, meta, stamp):
        rel = meta.get("rel_transform")
        if not rel:
            return
        key = tuple(round(rel[k], 4) for k in ("x", "y", "z", "qx", "qy", "qz", "qw"))
        c = self.cams[name]
        if c["extr"] == key:
            return
        c["extr"] = key
        (x, y, z), q = ue_pose_to_ros(rel)
        link = TransformStamped()
        link.header.stamp, link.header.frame_id, link.child_frame_id = stamp, self.base_frame, f"{name}_link"
        link.transform.translation.x, link.transform.translation.y, link.transform.translation.z = x, y, z
        (link.transform.rotation.x, link.transform.rotation.y,
         link.transform.rotation.z, link.transform.rotation.w) = q
        opt = TransformStamped()
        opt.header.stamp, opt.header.frame_id, opt.child_frame_id = stamp, f"{name}_link", f"{name}_optical"
        (opt.transform.rotation.x, opt.transform.rotation.y,
         opt.transform.rotation.z, opt.transform.rotation.w) = Q_LINK_TO_OPTICAL
        self.static_list[name] = [link, opt]
        # /tf_static is latched per publisher: always send the full set.
        self.static_tf.sendTransform([t for pair in self.static_list.values() for t in pair])
        self.get_logger().info(f"{name}: base_link -> {name}_link xyz=({x:.3f}, {y:.3f}, {z:.3f}) m")

    def update_odom(self, meta, stamp, t_sec):
        frame = meta.get("frame")
        act = meta.get("actor_transform")
        if not act or frame == self.last_odom_frame:
            return
        self.last_odom_frame = frame
        (x, y, z), q = ue_pose_to_ros(act)
        tf = TransformStamped()
        tf.header.stamp, tf.header.frame_id, tf.child_frame_id = stamp, self.odom_frame, self.base_frame
        tf.transform.translation.x, tf.transform.translation.y, tf.transform.translation.z = x, y, z
        tf.transform.rotation.x, tf.transform.rotation.y, tf.transform.rotation.z, tf.transform.rotation.w = q
        self.tf.sendTransform(tf)
        od = Odometry()
        od.header.stamp, od.header.frame_id, od.child_frame_id = stamp, self.odom_frame, self.base_frame
        od.pose.pose.position.x, od.pose.pose.position.y, od.pose.pose.position.z = x, y, z
        (od.pose.pose.orientation.x, od.pose.pose.orientation.y,
         od.pose.pose.orientation.z, od.pose.pose.orientation.w) = q
        if self.prev_odom:
            (px, py, pz, pyaw, pt) = self.prev_odom
            dt = t_sec - pt
            if dt > 1e-4:
                yaw = math.atan2(2 * (q[3] * q[2] + q[0] * q[1]), 1 - 2 * (q[1] ** 2 + q[2] ** 2))
                vx, vy = (x - px) / dt, (y - py) / dt
                # twist is expressed in the child (base) frame
                od.twist.twist.linear.x = math.cos(yaw) * vx + math.sin(yaw) * vy
                od.twist.twist.linear.y = -math.sin(yaw) * vx + math.cos(yaw) * vy
                od.twist.twist.angular.z = math.atan2(math.sin(yaw - pyaw), math.cos(yaw - pyaw)) / dt
        yaw = math.atan2(2 * (q[3] * q[2] + q[0] * q[1]), 1 - 2 * (q[1] ** 2 + q[2] ** 2))
        self.prev_odom = (x, y, z, yaw, t_sec)
        self.odom_pub.publish(od)

    def report(self):
        if self.stats:
            msg = "rates: " + ", ".join(f"{k} {v / 5.0:.1f} Hz" for k, v in sorted(self.stats.items()))
            if self.dropped:
                msg += f" (skipped {self.dropped / 5.0:.1f}/s stale frames; publishing slower than the sim)"
            self.get_logger().info(msg)
            self.stats.clear()
            self.dropped = 0

    # ------------------------------------------------------------------ main loop
    def on_frame(self, mtype, flags, ts_us, meta, payload):
        name = meta.get("camera_name") or meta.get("camera", "camera").split("::")[-1]
        name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
        comp = (flags & 0x0006) >> 1 if flags & 0x0001 else COMP_NONE
        with self.meta_lock:  # publishers, TF and odometry: one frame at a time; the image work runs in parallel
            c = self.cam(name)
            stamp = self.stamp(meta, ts_us)
            t_sec = meta.get("unix_time") or ts_us * 1e-6
            optical = f"{name}_optical"
            self.update_static_tf(name, meta, stamp)
            self.update_odom(meta, stamp, t_sec)

        if mtype in (FRAME_RGB, FRAME_RGBD):
            w, h = int(meta["w"]), int(meta["h"])
            rgb_payload = payload
            if mtype == FRAME_RGBD:
                return  # TODO: split RGBD once the sim streams it (JPEG + LZ4 halves)
            img = decode_image(comp, rgb_payload, w, h)
            if self.publish_raw and c["image"].get_subscription_count() > 0:  # skip the 7 MB copy when unwatched
                m = Image()
                m.header.stamp, m.header.frame_id = stamp, optical
                m.height, m.width, m.encoding, m.step = h, w, "bgr8", w * 3
                m.data = as_u8(np.ascontiguousarray(img))
                c["image"].publish(m)
            if c["comp"] is not None:
                import cv2
                if comp == COMP_JPEG:
                    data = bytes(payload)
                else:
                    data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(self.jpeg_quality)])[1].tobytes()
                cm = CompressedImage()
                cm.header.stamp, cm.header.frame_id, cm.format, cm.data = stamp, optical, "jpeg", as_u8(data)
                c["comp"].publish(cm)
            if c["preview"] is not None and c["preview"].get_subscription_count() > 0:
                import cv2
                small = cv2.resize(img, (int(w * self.preview_scale), int(h * self.preview_scale)), interpolation=cv2.INTER_AREA)
                pm = CompressedImage()
                pm.header.stamp, pm.header.frame_id, pm.format = stamp, optical, "jpeg"
                pm.data = as_u8(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, int(self.jpeg_quality)])[1])
                c["preview"].publish(pm)
            c["info"].publish(self.camera_info(meta, stamp, optical, w, h))
            with self.meta_lock:
                self.stats[name] = self.stats.get(name, 0) + 1
        elif mtype == FRAME_DEPTH:
            w, h = int(meta.get("depth_w", meta["w"])), int(meta.get("depth_h", meta["h"]))
            d = decode_depth_m(comp, payload, w, h)
            m = Image()
            m.header.stamp, m.header.frame_id = stamp, optical
            m.height, m.width, m.encoding, m.step = h, w, "32FC1", w * 4
            m.data = as_u8(np.ascontiguousarray(d, np.float32))
            c["depth"].publish(m)
            with self.meta_lock:
                self.stats[name + "/depth"] = self.stats.get(name + "/depth", 0) + 1

    def publish_loop(self):
        while rclpy.ok():
            with self.cv:
                self.cv.wait_for(lambda: self.latest or not rclpy.ok(), timeout=1.0)
                items = [item for kick in self.latest.values() for item in kick.values()]
                self.latest = {}
            # one worker per camera of the kick: JPEG decode/encode releases the GIL, so the six encode at once
            for item, err in zip(items, self.pool.map(self.publish_one, items)):
                if err:  # keep publishing other frames
                    self.get_logger().error(f"frame publish failed: {err}", throttle_duration_sec=5.0)

    def publish_one(self, item):
        try:
            self.on_frame(*item)
            return None
        except Exception as e:
            return e

    def hand_over(self, kick):
        key = frozenset(kick)
        with self.cv:
            if key in self.latest:
                self.dropped += len(self.latest[key])
            self.latest[key] = kick
            self.cv.notify()

    def run(self):
        threading.Thread(target=self.publish_loop, daemon=True).start()
        while rclpy.ok():
            try:
                with socket.create_connection((self.host, self.port), timeout=5.0) as s:
                    s.settimeout(None)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 << 20)
                    self.get_logger().info(f"connected to RMSS {self.host}:{self.port}")
                    kick, kick_ts = {}, None
                    while rclpy.ok():
                        hdr = recv_exact(s, HEADER.size)
                        magic, ver, mtype, ch, flags, seq, ts, mlen, plen, _ = HEADER.unpack(hdr)
                        if magic != MAGIC:
                            raise ConnectionError(f"bad magic {magic!r}; resyncing")
                        meta_raw = recv_exact(s, mlen) if mlen else b""
                        payload = recv_exact(s, plen) if plen else b""
                        if mtype not in (FRAME_RGB, FRAME_DEPTH, FRAME_RGBD):
                            continue
                        meta = json.loads(meta_raw.decode("utf-8")) if mlen else {}
                        # Hand over to the publisher thread one whole capture kick (one stamp) at a time,
                        # keeping only the newest kick per camera set: the socket is always drained, so a
                        # slow publish never pushes back on the sim, and a dropped kick takes all its
                        # cameras (no frame loses single cameras, which multi-camera calibration needs).
                        k_ts = meta.get("unix_time") or ts  # the sim stamps a kick's cameras alike
                        if kick and k_ts != kick_ts:
                            self.hand_over(kick)
                            kick = {}
                        kick_ts = k_ts
                        kick[(mtype, meta.get("camera", ""))] = (mtype, flags, ts, meta, payload)
            except (OSError, ConnectionError) as e:
                self.get_logger().warn(f"RMSS: {e}; retrying in 2 s (is the sim in Play?)", throttle_duration_sec=10.0)
                time.sleep(2.0)


def main():
    rclpy.init()
    node = RmssRosBridge()
    spin = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin.start()
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
