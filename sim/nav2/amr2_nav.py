"""[ROS 3.10] AMR2 (Police 2) 출동 노드 — 번호판 재확인 + 경보.

    patrol_ros
    python3 sim/nav2/amr2_nav.py            # SCANNED 를 전부 소진할 때까지

시나리오(CLAUDE.md 3단계): `GET /api/vehicle/next/` 로 SCANNED 이벤트의
`amr_vehicle_x/y` (AMR1 이 번호판을 읽은 관측점 — 통로 위 검증된 좌표)를
받아 Nav2 로 이동, 도착 후 OCR 로 번호판을 다시 읽어 DB 의
`plate_number` 와 비교한다:

    일치     → POST /api/vehicle/verify/ {match: true}  → WARNING_ISSUED
    불일치   → POST /api/vehicle/verify/ {match: false} → 이벤트 삭제
    좌표 없음(null) → 시작 위치로 복귀 후 종료

verify 로 상태가 바뀌면 `/next/` 가 다음 건을 주므로, null 이 나올 때까지
반복하면 자연히 전 건을 순회한다.

## 좌표계 — 상수가 둘이다 (⚠ amr1_nav 와 다른 부분)

    지도 변환(목표):   map  = world − AMR_START[0]   (map 프레임은 공용)
    자기 위치(odom):   world = odom + AMR_START[1]   (odom 원점 = amr2 시작)

## 예외 처리

- OCR 3프레임 실패: verify 를 **보내지 않고** 로컬 스킵 목록에 넣는다 —
  match=false 로 보내면 멀쩡한 이벤트가 삭제된다. `/next/` 가 같은 건을
  다시 주면(상태가 안 바뀌었으니) 스킵 목록과 대조해 종료한다.
  ⚠ 정책 공백: 이 건은 SCANNED 로 남는다 — 실물은 운영자 알림이 필요.
- 이동 실패·goal_blocked 도 같은 방식으로 스킵.
- `/amr2/on_duty` 발행 → amr_cam_bridge --gate 가 출동 중에만 카메라 방송.
"""

import argparse
import math
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "setup"))
sys.path.insert(0, os.path.join(_HERE, "..", "scenes"))
sys.path.insert(0, os.path.join(_HERE, "..", "vision"))
import pyver  # noqa: E402

pyver.require_ros("sim/nav2/amr2_nav.py")

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import cv2  # noqa: E402
import requests  # noqa: E402
import rclpy  # noqa: E402
from cv_bridge import CvBridge  # noqa: E402
from geometry_msgs.msg import PoseStamped  # noqa: E402
from nav2_msgs.action import NavigateToPose  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.action import ActionClient  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from sensor_msgs.msg import Image  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

import layout  # noqa: E402
import plate_ocr  # noqa: E402

_REPO = os.path.normpath(os.path.join(_HERE, "..", ".."))

MAP_OFF = layout.AMR_START[0]        # world→map (map 프레임 공용 기준)
START_SELF = layout.AMR_START[1]     # amr2 odom 원점 = (3.2, -3.0)
AISLE_MID = (layout.AISLE_X0 + layout.AISLE_X1) / 2.0

SERVER = os.environ.get("PATROL_SERVER", "http://127.0.0.1:8000")
POLL_INTERVAL = 2.0


def goal_yaw(wx, wy):
    """관측점에서 바라볼 방향 — amr1_nav 와 같은 복원 규칙."""
    if layout.AISLE_X0 < wx < layout.AISLE_X1:
        return 180.0 if wx < AISLE_MID else 0.0
    return 90.0


class Amr2Nav(Node):
    def __init__(self):
        super().__init__("amr2_nav")
        self.set_parameters([Parameter("use_sim_time", value=True)])
        self._ac = ActionClient(self, NavigateToPose, "/amr2/navigate_to_pose")
        self._goal_handle = None
        self._duty_pub = self.create_publisher(Bool, "/amr2/on_duty", 10)
        self._duty = False
        self._cv = CvBridge()
        self._frame = None
        self._pose = None
        self.create_subscription(Image, "amr_images/amr2/ocr",
                                 self._on_image, 5)
        self.create_subscription(Odometry, "/amr2/odom", self._on_odom, 10)
        from nav_msgs.msg import OccupancyGrid
        from rclpy.qos import QoSProfile, DurabilityPolicy
        self._map = None
        self.create_subscription(
            OccupancyGrid, "/map", lambda m: setattr(self, "_map", m),
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))

    def set_duty(self, on):
        self._duty = on
        for _ in range(3):
            self._duty_pub.publish(Bool(data=on))

    def _on_image(self, msg):
        self._frame = (time.monotonic(), self._cv.imgmsg_to_cv2(msg, "bgr8"))

    def _on_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        yaw = math.degrees(math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                      1.0 - 2.0 * (q.y * q.y + q.z * q.z)))
        self._pose = (p.x + START_SELF[0], p.y + START_SELF[1], yaw)

    # ── 서버 ─────────────────────────────────────────────────────
    def fetch_next(self):
        """GET /api/vehicle/next/ — 없으면 None (복귀 신호)."""
        try:
            r = requests.get(f"{SERVER}/api/vehicle/next/", timeout=2)
            d = r.json()
            if d.get("vehicle_info", "x") is None:
                return None
            return d
        except Exception as e:
            self.get_logger().warn(f"서버 요청 실패: {e}")
            return None

    def verify(self, event_id, match):
        try:
            r = requests.post(f"{SERVER}/api/vehicle/verify/", timeout=2,
                              json={"event_id": event_id, "match": match})
            self.get_logger().info(
                f"verify(match={match}) → {r.status_code} {r.json()}")
        except Exception as e:
            self.get_logger().warn(f"verify 실패: {e}")

    # ── 지도 검증 + 이동 (amr1_nav 와 같은 방어) ─────────────────
    def goal_blocked(self, wx, wy, radius=0.15):
        if self._map is None:
            t0 = time.monotonic()
            while self._map is None and time.monotonic() - t0 < 5.0:
                rclpy.spin_once(self, timeout_sec=0.2)
            if self._map is None:
                self.get_logger().warn("/map 미수신 — 목표 검증 생략")
                return False
        info = self._map.info
        mx, my = wx - MAP_OFF[0], wy - MAP_OFF[1]
        n = max(1, int(radius / info.resolution))
        c0 = int((mx - info.origin.position.x) / info.resolution)
        r0 = int((my - info.origin.position.y) / info.resolution)
        for r in range(r0 - n, r0 + n + 1):
            for c in range(c0 - n, c0 + n + 1):
                if not (0 <= r < info.height and 0 <= c < info.width):
                    return True
                v = self._map.data[r * info.width + c]
                if v < 0 or v >= 50:
                    return True
        return False

    def navigate(self, wx, wy, yaw_deg=None, check=True):
        """check=False 는 복귀용 — 자기 스폰 자리는 지도상 미탐사(로봇이
        자기 밑은 스캔 못 한다)라 goal_blocked 에 걸리기 때문."""
        rclpy.spin_once(self, timeout_sec=0.2)
        if check and self.goal_blocked(wx, wy):
            self.get_logger().warn(
                f"목표 ({wx:.2f}, {wy:.2f})가 지도상 장애물/미탐사 안 — 출동 생략")
            return False
        if yaw_deg is None:
            yaw_deg = goal_yaw(wx, wy)
        mx, my = wx - MAP_OFF[0], wy - MAP_OFF[1]

        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = mx
        pose.pose.position.y = my
        pose.pose.orientation.z = math.sin(math.radians(yaw_deg) / 2.0)
        pose.pose.orientation.w = math.cos(math.radians(yaw_deg) / 2.0)
        goal = NavigateToPose.Goal()
        goal.pose = pose

        self.get_logger().info(
            f"목표: 월드 ({wx:.2f}, {wy:.2f}) yaw {yaw_deg:.0f}° "
            f"= map ({mx:.2f}, {my:.2f})")
        if not self._ac.wait_for_server(timeout_sec=60.0):
            self.get_logger().error("amr2 navigate_to_pose 액션 서버가 없다")
            return False
        # 수락 응답 유실 재전송 — amr1_nav 와 같은 DDS 레이스 대비
        self._goal_handle = None
        for attempt in range(3):
            send = self._ac.send_goal_async(goal, feedback_callback=self._on_feedback)
            rclpy.spin_until_future_complete(self, send, timeout_sec=10.0)
            if send.done():
                self._goal_handle = send.result()
                break
            self.get_logger().warn(f"목표 수락 응답 유실 — 재전송 ({attempt + 1}/3)")
        if not self._goal_handle or not self._goal_handle.accepted:
            self.get_logger().error("목표가 거부됐다")
            return False
        self._fb_t = 0.0
        result = self._goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result)
        self._goal_handle = None
        ok = result.result().status == 4
        self.get_logger().info("도착 ✅" if ok else
                               f"실패 (status={result.result().status})")
        return ok

    def _on_feedback(self, fb):
        now = time.monotonic()
        if now - getattr(self, "_fb_t", 0.0) > 5.0:
            self._fb_t = now
            self._duty_pub.publish(Bool(data=self._duty))
            self.get_logger().info(
                f"  남은 거리 {fb.feedback.distance_remaining:.2f} m")

    def cancel(self):
        if self._goal_handle is not None:
            self.get_logger().info("목표 취소 — 로봇 정지")
            self._goal_handle.cancel_goal_async()
            time.sleep(0.5)

    # ── 번호판 재확인 ────────────────────────────────────────────
    def recheck_plate(self, expected, attempts=3):
        """도착 지점에서 번호판을 다시 읽어 (일치여부, 읽은텍스트)를 준다.

        OCR 자체가 실패하면 (None, None) — 불일치와 구분한다.
        """
        t_arrival = time.monotonic()
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.5)
            if self._frame and self._frame[0] > t_arrival:
                break
            if time.monotonic() - t_arrival > 15.0:
                return None, None
        last_t = self._frame[0]
        for i in range(attempts):
            text, _ = plate_ocr.ocr_frame(self._frame[1])
            self.get_logger().info(f"재확인 시도 {i + 1}: {text} (기대 {expected})")
            if text:
                return text == expected, text
            t0 = time.monotonic()
            while (rclpy.ok() and self._frame[0] <= last_t
                   and time.monotonic() - t0 < 10.0):
                rclpy.spin_once(self, timeout_sec=0.3)
            last_t = self._frame[0]
        return None, None


def main():
    ap = argparse.ArgumentParser(description="AMR2 — 번호판 재확인·경보")
    ap.add_argument("--home", metavar="X,Y",
                    default=f"{START_SELF[0]},{START_SELF[1]}",
                    help="복귀 지점 (기본: 시작 좌표)")
    args = ap.parse_args()
    hx, hy = (float(v) for v in args.home.split(","))

    rclpy.init()
    node = Amr2Nav()

    def _exit(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _exit)

    skipped = set()                      # OCR·이동 실패로 보류한 event_id
    try:
        while rclpy.ok():
            v = node.fetch_next()
            if v is None or v.get("event_id") in skipped:
                if v is not None:
                    node.get_logger().info(
                        f"남은 건이 보류 목록({sorted(skipped)})뿐 — 종료")
                else:
                    node.get_logger().info("SCANNED 없음 — 복귀")
                break
            eid, plate = v["event_id"], v["plate_number"]
            node.get_logger().info(f"── 이벤트 id={eid} 번호판 {plate} ──")
            node.set_duty(True)
            if not node.navigate(v["amr_vehicle_x"], v["amr_vehicle_y"]):
                node.get_logger().warn("이동 실패 — 보류")
                skipped.add(eid)
                continue
            match, text = node.recheck_plate(plate)
            if match is None:
                node.get_logger().warn("재확인 OCR 실패 — verify 보류 (SCANNED 유지)")
                skipped.add(eid)
                continue
            node.verify(eid, bool(match))
            if not match:
                node.get_logger().warn(f"번호판 불일치: 읽음 {text} ≠ DB {plate}")
        # 복귀
        node.get_logger().info(f"복귀: ({hx}, {hy})")
        node.navigate(hx, hy, 0.0, check=False)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.set_duty(False)
        node.cancel()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
