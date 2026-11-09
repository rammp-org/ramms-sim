#!/usr/bin/env bash
# Start the RMSS -> ROS 2 bridge. Extra args go to the node, e.g.:
#   Scripts/ros/run_bridge.sh --ros-args -p compressed:=true
# python3 -s skips ~/.local site-packages, whose numpy 2 / cv2 builds clash with ROS 2 Humble's.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
source /opt/ros/${ROS_DISTRO:-humble}/setup.bash
# Large CycloneDDS socket buffers for full-resolution images, when the kernel allows them
# (sudo sysctl -w net.core.rmem_max=2147483647); see cyclonedds.xml.
if [ -z "$CYCLONEDDS_URI" ] && [ "$(cat /proc/sys/net/core/rmem_max)" -ge 67108864 ]; then
	export CYCLONEDDS_URI="file://$here/cyclonedds.xml"
fi
[ -n "$CYCLONEDDS_URI" ] || echo "note: full-res image_raw drops over DDS until net.core.rmem_max is raised (see cyclonedds.xml); preview/compressed is unaffected" >&2
exec python3 -s "$here/ramms_ros_bridge.py" "$@"
