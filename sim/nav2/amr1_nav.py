"""[ROS 3.10] AMR1 출동 노드 — 서버 좌표를 받아 Nav2 로 간다.

    patrol_ros
    python3 sim/nav2/amr1_nav.py                 # GET /api/parking/next/ → 이동
    python3 sim/nav2/amr1_nav.py --all           # DETECTED 전부 차례로 (시연·검증)
    python3 sim/nav2/amr1_nav.py --goal 11.9,9.0 # 월드 좌표로 직접 (테스트)

시나리오(CLAUDE.md 2단계): 서버는 좌표를 **한 번** 줄 뿐 경로 안내를 하지
않는다. 이 노드가 `GET /api/parking/next/` 로 DETECTED 이벤트의
observation_x/y (월드 좌표)를 받아 Nav2 `navigate_to_pose` 액션에 넣으면
경로 계획·회피는 전부 Nav2 가 한다. 현장 판별(구역 색)과 OCR 은 다음 단계 —
지금은 도착까지만 한다.

## 좌표 변환 (nav2_params_amr1.yaml 머리말 참고)

    map = world - layout.AMR_START[0]        # map 프레임 = amr1/odom 프레임

## 목표 yaw — DB 에는 없다. 좌표에서 되살린다

관측 좌표는 webcam_detect.py 가 번호판에서 APPROACH_DIST 만큼 물러난 통로
위 점이고, 그때 바라볼 방향(yaw)도 함께 정해 마커 orientation 에 넣지만
서버 DB(parking_events)에는 yaw 컬럼이 없어 좌표만 남는다. 다행히 방향은
좌표만으로 복원된다 — webcam_detect._detect() 와 같은 규칙:

    중앙 통로 서쪽 절반 (블록 A 앞, x≈11.9)  → yaw 180° (서쪽 차를 본다)
    중앙 통로 동쪽 절반 (블록 B 앞, x≈14.2)  → yaw   0°
    통로 밖 (벽쪽 x≈3.2 · 소방구역)          → yaw  90° (북쪽 차를 본다)

OcrCam 이 로봇 진행 방향(로컬 +X)을 보므로 yaw 가 맞아야 도착 즉시 번호판이
프레임에 들어온다.

⚠ 이 노드가 죽어도 로봇은 Nav2 가 몰고 있다 — 종료 시그널에서 반드시 목표를
  취소한다 (explore_amr1.py 의 무인 주행 사고와 같은 계열의 함정).
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
import pyver  # noqa: E402

pyver.require_ros("sim/nav2/amr1_nav.py")

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import requests  # noqa: E402
import rclpy  # noqa: E402
from geometry_msgs.msg import PoseStamped  # noqa: E402
from nav2_msgs.action import NavigateToPose  # noqa: E402
from rclpy.action import ActionClient  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402

import layout  # noqa: E402  (sim/scenes — Isaac 없이 python3 로 돈다)

START = layout.AMR_START[0]                       # (1.2, -3.0) — odom 원점
AISLE_MID = (layout.AISLE_X0 + layout.AISLE_X1) / 2.0     # 12.7

SERVER = os.environ.get("PATROL_SERVER", "http://127.0.0.1:8000")
POLL_INTERVAL = 2.0          # 이벤트가 아직 없을 때 재조회 간격 (초, 벽시계)


def goal_yaw(wx, wy):
    """관측 좌표(월드)에서 바라볼 방향을 복원한다 — 머리말의 규칙."""
    if layout.AISLE_X0 < wx < layout.AISLE_X1:
        return 180.0 if wx < AISLE_MID else 0.0
    return 90.0


class Amr1Nav(Node):
    def __init__(self):
        super().__init__("amr1_nav")
        # 씬이 /clock 을 발행한다 — 타임스탬프를 시뮬 시간으로 맞춘다.
        self.set_parameters([Parameter("use_sim_time", value=True)])
        self._ac = ActionClient(self, NavigateToPose, "/amr1/navigate_to_pose")
        self._goal_handle = None

    # ── 서버 ──────────────────────────────────────────────────────
    def fetch_next(self):
        """GET /api/parking/next/ — DETECTED 가 생길 때까지 기다린다."""
        while rclpy.ok():
            try:
                r = requests.get(f"{SERVER}/api/parking/next/", timeout=2)
                d = r.json()
                if d.get("event_id") is not None:
                    return d
                self.get_logger().info("DETECTED 이벤트 없음 — 대기")
            except Exception as e:
                self.get_logger().warn(f"서버 요청 실패: {e}")
            time.sleep(POLL_INTERVAL)
        return None

    def fetch_all(self):
        """GET /api/parking/list/ — DETECTED 전부 (등록 순). 시연·검증용."""
        while rclpy.ok():
            try:
                r = requests.get(f"{SERVER}/api/parking/list/", timeout=2)
                ev = [e for e in r.json() if e.get("status") == "DETECTED"]
                if ev:
                    return sorted(ev, key=lambda e: e["created_at"])
                self.get_logger().info("DETECTED 이벤트 없음 — 대기")
            except Exception as e:
                self.get_logger().warn(f"서버 요청 실패: {e}")
            time.sleep(POLL_INTERVAL)
        return []

    # ── Nav2 ──────────────────────────────────────────────────────
    def navigate(self, wx, wy, yaw_deg=None):
        """월드 좌표 목표로 이동. 성공 여부를 돌려준다."""
        if yaw_deg is None:
            yaw_deg = goal_yaw(wx, wy)
        mx, my = wx - START[0], wy - START[1]

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
            self.get_logger().error("navigate_to_pose 액션 서버가 없다 — Nav2 를 먼저 띄울 것")
            return False

        send = self._ac.send_goal_async(goal, feedback_callback=self._on_feedback)
        rclpy.spin_until_future_complete(self, send)
        self._goal_handle = send.result()
        if not self._goal_handle or not self._goal_handle.accepted:
            self.get_logger().error("목표가 거부됐다")
            return False

        self._fb_t = 0.0
        result = self._goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result)
        self._goal_handle = None
        code = result.result().status
        ok = code == 4                                  # STATUS_SUCCEEDED
        self.get_logger().info("도착 ✅" if ok else f"실패 (status={code})")
        return ok

    def _on_feedback(self, fb):
        now = time.monotonic()
        if now - getattr(self, "_fb_t", 0.0) > 5.0:     # 5초(벽시계)마다 한 줄
            self._fb_t = now
            self.get_logger().info(
                f"  남은 거리 {fb.feedback.distance_remaining:.2f} m")

    def cancel(self):
        if self._goal_handle is not None:
            self.get_logger().info("목표 취소 — 로봇 정지")
            self._goal_handle.cancel_goal_async()
            # 취소 요청이 나갈 시간을 준다 (spin 은 시그널 문맥이라 못 돈다)
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser(description="AMR1 — 서버 좌표로 Nav2 출동")
    ap.add_argument("--all", action="store_true",
                    help="DETECTED 이벤트 전부를 등록 순서로 방문 (시연·검증)")
    ap.add_argument("--goal", metavar="X,Y[,YAW]",
                    help="서버 대신 월드 좌표 목표를 직접 준다 (테스트)")
    args = ap.parse_args()

    rclpy.init()
    node = Amr1Nav()

    def _cancel_and_exit(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cancel_and_exit)

    try:
        if args.goal:
            v = [float(x) for x in args.goal.split(",")]
            node.navigate(v[0], v[1], v[2] if len(v) > 2 else None)
        elif args.all:
            events = node.fetch_all()
            node.get_logger().info(f"DETECTED {len(events)}건 — 순서대로 방문")
            done = 0
            for e in events:
                node.get_logger().info(f"── 이벤트 id={e['id']} ──")
                if node.navigate(e["observation_x"], e["observation_y"]):
                    done += 1
            node.get_logger().info(f"방문 완료 {done}/{len(events)}")
        else:
            e = node.fetch_next()
            if e:
                node.get_logger().info(f"이벤트 id={e['event_id']} 수신 (한 번)")
                node.navigate(e["observation_x"], e["observation_y"])
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.cancel()                    # 어떤 경로로 나가든 목표를 물고 죽지 않는다
    rclpy.shutdown()


if __name__ == "__main__":
    main()
