#!/usr/bin/env python3
"""Minimal client for Unreal's Python Remote Execution (no dependencies).

Runs a python snippet or script file inside a running editor that has
Project Settings > Python > Remote Execution enabled (this project does:
multicast 239.0.0.1:6766, loopback). Speaks the PythonScriptPlugin remote
execution protocol: multicast ping/pong discovery, then the editor connects
back to us over TCP for commands.

Usage:
  python Scripts/editor_remote_exec.py --code  "unreal.log('hi')"
  python Scripts/editor_remote_exec.py --file  Plugins/RammsCrowd/Content/Python/ramms_crowd_assign_foot_ik.py
  python Scripts/editor_remote_exec.py --eval  "unreal.SystemLibrary.get_project_directory()"

Exit code 0 on success (and prints the editor-side output), 1 otherwise.
"""

import argparse
import json
import socket
import struct
import sys
import time
import uuid

MULTICAST_GROUP = ("239.0.0.1", 6766)
BIND_ADDR = "127.0.0.1"
MAGIC = "ue_py"
PROTO_VERSION = 1
DISCOVER_TIMEOUT_S = 6.0
COMMAND_TIMEOUT_S = 120.0


def make_msg(msg_type, source, dest=None, data=None):
    msg = {"version": PROTO_VERSION, "magic": MAGIC, "type": msg_type, "source": source}
    if dest is not None:
        msg["dest"] = dest
    if data is not None:
        msg["data"] = data
    return json.dumps(msg).encode("utf-8")


def parse_msg(payload):
    try:
        msg = json.loads(payload.decode("utf-8"))
        if msg.get("magic") == MAGIC and msg.get("version") == PROTO_VERSION:
            return msg
    except (ValueError, UnicodeDecodeError):
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--code", help="python statements to execute (ExecuteStatement mode)")
    group.add_argument("--file", help="path to a python file whose contents are executed")
    group.add_argument("--eval", help="single expression to evaluate and print")
    args = ap.parse_args()

    if args.file:
        # ExecuteFile takes a PATH to a python file (resolved editor-side).
        import os
        command, exec_mode = os.path.abspath(args.file), "ExecuteFile"
    elif args.code:
        command, exec_mode = args.code, "ExecuteStatement"
    else:
        command, exec_mode = args.eval, "EvaluateStatement"

    node_id = str(uuid.uuid4())

    # Multicast socket: shared with the editor's own bind, loopback interface.
    mcast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    mcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mcast.bind(("", MULTICAST_GROUP[1]))
    mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP[0]), socket.inet_aton(BIND_ADDR))
    mcast.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    mcast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(BIND_ADDR))
    mcast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    mcast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
    mcast.settimeout(0.5)

    # Discover an editor node.
    remote_id = None
    deadline = time.monotonic() + DISCOVER_TIMEOUT_S
    while time.monotonic() < deadline and remote_id is None:
        mcast.sendto(make_msg("ping", node_id), MULTICAST_GROUP)
        try:
            payload, _ = mcast.recvfrom(4096)
        except socket.timeout:
            continue
        msg = parse_msg(payload)
        if msg and msg.get("type") == "pong" and msg.get("source") != node_id:
            remote_id = msg["source"]
            info = msg.get("data", {})
            print("found editor node: %s (%s)" % (info.get("project_name", "?"), remote_id))
    if remote_id is None:
        print(
            "ERROR: no editor responded on %s:%d - is the editor running with Remote Execution enabled?"
            % MULTICAST_GROUP,
            file=sys.stderr,
        )
        mcast.close()
        return 1

    # Open our TCP listener; the editor connects back to it.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((BIND_ADDR, 0))
    listener.listen(1)
    listener.settimeout(DISCOVER_TIMEOUT_S)
    cmd_endpoint = listener.getsockname()

    mcast.sendto(make_msg("open_connection", node_id, remote_id,
                          {"command_ip": cmd_endpoint[0], "command_port": cmd_endpoint[1]}),
                 MULTICAST_GROUP)
    try:
        conn, _ = listener.accept()
    except socket.timeout:
        print("ERROR: editor did not open the command connection.", file=sys.stderr)
        return 1

    try:
        conn.settimeout(COMMAND_TIMEOUT_S)
        conn.sendall(make_msg("command", node_id, remote_id,
                              {"command": command, "unattended": True, "exec_mode": exec_mode}))
        buf = b""
        result = None
        while result is None:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            msg = parse_msg(buf)  # single JSON object per command
            if msg and msg.get("type") == "command_result":
                result = msg
    finally:
        mcast.sendto(make_msg("close_connection", node_id, remote_id), MULTICAST_GROUP)
        conn.close()
        listener.close()
        mcast.close()

    if result is None:
        print("ERROR: connection closed without a command result.", file=sys.stderr)
        return 1

    data = result.get("data", {})
    for entry in data.get("output", []):
        print("[%s] %s" % (entry.get("type", "?"), entry.get("output", "").rstrip()))
    if data.get("result") not in (None, "", "None"):
        print("result: %s" % data["result"])
    if not data.get("success", False):
        print("ERROR: command failed in the editor.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
