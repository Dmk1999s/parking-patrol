"""[ROS 3.10] `/map` 을 PNG 로 렌더 — 디스플레이 없는 EC2 에서 지도를 본다.

    patrol_ros
    python3 sim/slam/map_snapshot.py --out /tmp/map --every 20

RViz 는 디스플레이가 있어야 떠서 이 서버에서는 못 쓴다. 대신 slam_toolbox 가
발행하는 OccupancyGrid 를 받아 그림으로 굽는다 — 만들어지는 과정을 파일로
지켜볼 수 있다.

🚨 /map 은 **transient_local** 로 발행된다. 구독 QoS 를 맞추지 않으면
   (기본은 volatile) 연결은 되는데 **메시지가 한 장도 안 온다** — 오류 없다.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
import pyver  # noqa: E402

pyver.require_ros("sim/slam/map_snapshot.py")

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import numpy as np  # noqa: E402
import rclpy  # noqa: E402
from nav_msgs.msg import OccupancyGrid, Odometry  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import (DurabilityPolicy, QoSProfile,  # noqa: E402
                       ReliabilityPolicy)

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("PIL 이 없다:  pip3 install pillow")

SCALE = 3           # 셀당 픽셀 (0.05 m 해상도 × 3 = 화면상 15 cm/px 느낌)


class Snapshot(Node):
    def __init__(self, out, every):
        super().__init__("map_snapshot")
        self._out = out
        self._every = every
        self._last_saved = -1e9
        self._odom = None            # 로봇 위치 표시용 (odom≈map, 표시용으론 충분)
        qos = QoSProfile(depth=1,
                         reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, "/map", self._on_map, qos)
        self.create_subscription(Odometry, "/amr1/odom", self._on_odom, 10)
        self.get_logger().info(f"{out}_latest.png 에 {every}초마다 저장")

    def _on_odom(self, msg):
        self._odom = msg.pose.pose.position

    def _on_map(self, msg):
        import time
        now = time.monotonic()
        if now - self._last_saved < self._every:
            return
        self._last_saved = now

        w, h = msg.info.width, msg.info.height
        grid = np.array(msg.data, dtype=np.int8).reshape(h, w)
        img = np.full((h, w), 128, dtype=np.uint8)      # 미탐사 = 회색
        img[grid == 0] = 255                            # 자유 = 흰색
        img[grid > 50] = 0                              # 점유 = 검정
        # OccupancyGrid 는 row0 이 남쪽(원점) — 이미지는 row0 이 위라 뒤집는다
        img = np.flipud(img)

        im = Image.fromarray(img).convert("RGB")
        im = im.resize((w * SCALE, h * SCALE), Image.NEAREST)

        if self._odom is not None:
            # odom 좌표를 지도 픽셀로. 매핑 중 map≈odom 이라 표시용으론 충분.
            ox = msg.info.origin.position.x
            oy = msg.info.origin.position.y
            res = msg.info.resolution
            px = (self._odom.x - ox) / res * SCALE
            py = (h - (self._odom.y - oy) / res) * SCALE
            d = ImageDraw.Draw(im)
            r = 2 * SCALE
            d.ellipse((px - r, py - r, px + r, py + r), fill=(220, 40, 40))

        latest = f"{self._out}_latest.png"
        im.save(latest + ".tmp.png")
        os.replace(latest + ".tmp.png", latest)         # 읽는 쪽이 반쪽을 못 보게
        known = int((grid != -1).sum())
        self.get_logger().info(
            f"저장: {latest}  {w}×{h}셀  탐사 {known * msg.info.resolution**2:.0f} m²")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/parking_map")
    ap.add_argument("--every", type=float, default=20.0)
    a = ap.parse_args()
    rclpy.init()
    node = Snapshot(a.out, a.every)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.shutdown()


if __name__ == "__main__":
    main()
