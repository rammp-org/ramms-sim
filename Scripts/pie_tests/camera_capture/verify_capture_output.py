#!/usr/bin/env python3
"""Verify what a mismatched-depth capture actually wrote.

A minimal EXR reader, because the point of this check is the pixel values and
no EXR library is installed here. Handles what UE's ImageWriteQueue emits:
scanline images, NO_COMPRESSION or ZIP/ZIPS, HALF or FLOAT channels.

Checks, for the first frame in a capture directory:

  * frame_N.exr        is the COLOUR grid, and its alpha channel carries real
                       depth rather than the zeros the pre-fix code wrote
  * frame_N_depth.exr  is the DEPTH grid, with values matching the alpha
                       channel's range
  * frame_N_motion.exr is the DEPTH grid, not the colour one
  * frame_N.json       reports both grids

Usage:
    python3 Scripts/pie_tests/camera_capture/verify_capture_output.py \
        camera_capture_pie_test/Actor_0/TestDepthMismatchCam
"""

import json
import os
import struct
import sys
import zlib

MAGIC = 0x01312F76
HALF, FLOAT, UINT = 1, 2, 0
NO_COMPRESSION, RLE, ZIPS, ZIP = 0, 1, 2, 3


def _read_null_str(buf, pos):
    end = buf.index(b"\0", pos)
    return buf[pos:end].decode("utf-8"), end + 1


def read_exr(path):
    """Return (width, height, {channel: [values row-major]})."""
    with open(path, "rb") as fh:
        buf = fh.read()

    magic, = struct.unpack_from("<I", buf, 0)
    if magic != MAGIC:
        raise ValueError("%s is not an EXR (magic 0x%08x)" % (path, magic))
    pos = 8  # magic + version

    channels, compression, data_window = None, None, None
    while True:
        name, pos = _read_null_str(buf, pos)
        if name == "":
            break
        _type, pos = _read_null_str(buf, pos)
        size, = struct.unpack_from("<i", buf, pos)
        pos += 4
        payload = buf[pos:pos + size]
        pos += size

        if name == "channels":
            channels = []
            p = 0
            while payload[p] != 0:
                cname, p = _read_null_str(payload, p)
                ptype, = struct.unpack_from("<i", payload, p)
                channels.append((cname, ptype))
                p += 16  # pixel type + pLinear + reserved + sampling x/y
        elif name == "compression":
            compression = payload[0]
        elif name == "dataWindow":
            x0, y0, x1, y1 = struct.unpack_from("<iiii", payload, 0)
            data_window = (x0, y0, x1, y1)

    if channels is None or data_window is None:
        raise ValueError("%s: incomplete header" % path)

    x0, y0, x1, y1 = data_window
    width, height = x1 - x0 + 1, y1 - y0 + 1
    if compression not in (NO_COMPRESSION, ZIPS, ZIP):
        raise ValueError("%s: unsupported compression %s" % (path, compression))

    rows_per_block = 16 if compression == ZIP else 1
    num_blocks = (height + rows_per_block - 1) // rows_per_block

    offsets = struct.unpack_from("<%dQ" % num_blocks, buf, pos)
    bytes_per = {HALF: 2, FLOAT: 4, UINT: 4}
    # EXR stores channels alphabetically within a scanline block.
    chans = sorted(channels, key=lambda c: c[0])
    row_bytes = sum(bytes_per[t] for _, t in chans) * width

    out = {name: [] for name, _ in chans}
    for off in offsets:
        y, size = struct.unpack_from("<ii", buf, off)
        raw = buf[off + 8:off + 8 + size]
        nrows = min(rows_per_block, height - (y - y0))
        expected = row_bytes * nrows

        if compression != NO_COMPRESSION and len(raw) < expected:
            raw = zlib.decompress(raw)
            # EXR's ZIP post-process, in reverse: undo the byte delta, then
            # un-deinterleave the two halves.
            data = bytearray(raw)
            for i in range(1, len(data)):
                data[i] = (data[i - 1] + data[i] - 128) & 0xFF
            half = (len(data) + 1) // 2
            flat = bytearray(len(data))
            flat[0::2] = data[:half]
            flat[1::2] = data[half:]
            raw = bytes(flat)

        p = 0
        for _ in range(nrows):
            for cname, ctype in chans:
                n = width * bytes_per[ctype]
                chunk = raw[p:p + n]
                p += n
                if ctype == FLOAT:
                    out[cname].extend(struct.unpack("<%df" % width, chunk))
                elif ctype == HALF:
                    out[cname].extend(struct.unpack("<%de" % width, chunk))
                else:
                    out[cname].extend(struct.unpack("<%dI" % width, chunk))

    return width, height, out


def main(camera_dir):
    frames = sorted(f for f in os.listdir(camera_dir)
                    if f.endswith(".json") and f.startswith("frame_"))
    if not frames:
        print("no frames in %s" % camera_dir)
        return 1
    stem = frames[0][:-len(".json")]
    print("frame: %s" % stem)

    meta = json.load(open(os.path.join(camera_dir, frames[0])))
    cw, ch = meta["color_width"], meta["color_height"]
    dw, dh = meta["depth_width"], meta["depth_height"]
    print("  metadata: colour %dx%d, depth %dx%d, resampled_into_alpha=%s"
          % (cw, ch, dw, dh, meta["depth_resampled_into_alpha"]))

    fails = []

    def check(ok, what):
        print("  %s  %s" % ("pass" if ok else "FAIL", what))
        if not ok:
            fails.append(what)

    check(cw != dw or ch != dh, "the two grids really do differ")

    # --- combined colour + depth-in-alpha ---
    w, h, chans = read_exr(os.path.join(camera_dir, stem + ".exr"))
    print("  %s.exr: %dx%d channels=%s" % (stem, w, h, sorted(chans)))
    check((w, h) == (cw, ch), "combined EXR is on the colour grid")

    alpha = chans.get("A", [])
    nonzero = sum(1 for v in alpha if v != 0.0)
    amax = max(alpha) if alpha else 0.0
    amin = min(alpha) if alpha else 0.0
    adistinct = len(set(alpha))
    print("      alpha: %d/%d non-zero, range %.4f..%.4f, %d distinct"
          % (nonzero, len(alpha), amin, amax, adistinct))
    # The pre-fix bug: alpha was 0.0 for every pixel.
    check(nonzero > 0, "alpha carries depth (pre-fix this was zero everywhere)")
    # Not a units check: the DMV material emits depth normalised to 0..1, even
    # though FCaptureData calls it "cm, world-space" and the stream metadata
    # advertises depth_unit cm. That discrepancy predates this fix and is not
    # what is being tested here -- what matters is that the values vary, because
    # a constant plane would also be "non-zero" while carrying nothing.
    check(adistinct > 1000, "alpha varies across the image rather than being constant")

    # --- native-resolution depth ---
    dpath = os.path.join(camera_dir, stem + "_depth.exr")
    check(os.path.exists(dpath), "native-resolution depth EXR exists")
    if os.path.exists(dpath):
        w, h, dchans = read_exr(dpath)
        print("  %s_depth.exr: %dx%d" % (stem, w, h))
        check((w, h) == (dw, dh), "depth EXR is on the depth grid")
        dr = dchans.get("R", [])
        ddistinct = len(set(dr))
        print("      depth R: range %.4f..%.4f, %d distinct"
              % (min(dr) if dr else 0.0, max(dr) if dr else 0.0, ddistinct))
        check(ddistinct > 1000, "depth EXR varies across the image")
        # The alpha channel is a nearest-neighbour resample of exactly this, so
        # it must contain the same SET of values -- no more, no fewer. This is
        # the nearest-vs-bilinear property, checked on real GPU data rather than
        # on a synthetic ramp.
        check(set(dr) == set(alpha),
              "resampled alpha holds exactly the native depth's value set "
              "(%d vs %d distinct)" % (adistinct, ddistinct))

    # --- motion vectors ---
    mpath = os.path.join(camera_dir, stem + "_motion.exr")
    if os.path.exists(mpath):
        w, h, _ = read_exr(mpath)
        print("  %s_motion.exr: %dx%d" % (stem, w, h))
        check((w, h) == (dw, dh), "motion EXR is on the depth grid, not the colour one")

    print("%s (%d failing)" % ("ALL GREEN" if not fails else "FAILURES", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
