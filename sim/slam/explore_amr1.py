"""[ROS 3.10] SLAM 매핑용 순찰 드라이버 — AMR1 을 웨이포인트로 몬다.

    patrol_ros
    python3 sim/slam/explore_amr1.py

`/amr1/odom` 을 보고 `/amr1/cmd_vel` 을 내는 단순 P 제어다. Nav2 가 아니다 —
**Nav2 는 지도가 있어야 도는데 지금은 그 지도를 만드는 중**이라, 지도 없이도
돌 수 있는 가장 단순한 것으로 몬다. 경로는 차가 어떻게 배치되든 항상 비어
있는 통로(레이아웃 상수로 보장)만 지나간다.

## 좌표 — 웨이포인트는 월드 좌표로 적고 odom 으로 변환한다

odom 은 로봇이 **켜진 자리**가 원점이다 (IsaacComputeOdometry). AMR1 은
`layout.AMR_START[0]` = (1.2, -3.0), yaw 0 에서 켜지므로:

    odom = world - (1.2, -3.0)

🚨 layout.py 의 AMR_START 를 바꾸면 여기 START 도 같이 바꿔야 한다.
   (layout.py 는 Isaac 쪽 3.12 파일이라 import 하지 않고 값을 복사해 둔다.)

## 경로 (월드 좌표) — 왜 이 순서인가

    서쪽 통로 ↑ → 북쪽 띠 → → 중앙 통로 ↓ → 남쪽 띠 → → 동쪽 통로 ↑ → 북쪽 띠 ←

마지막 구간이 시작 부근(북쪽 띠)을 다시 지나며 **루프를 닫는다** — SLAM 이
누적 오차를 이 지점에서 정산한다. 중앙 통로를 지날 때 양쪽 블록 주차면과
차들이 전부 스캔에 들어온다.

제어 관련해 한 가지: 시뮬 실측으로 각속도가 명령의 ~55% 만 나온다
(sim/README.md). 여기는 odom 폐루프 P 제어라 목표 방향에 도달할 때까지
계속 돌리므로 상관없다 — 개루프였다면 다 틀어졌을 것이다.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
import pyver  # noqa: E402

pyver.require_ros("sim/slam/explore_amr1.py")

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.node import Node  # noqa: E402

START = (1.2, -3.0)              # = layout.AMR_START[0]

# 월드 좌표 웨이포인트. 전부 통로 한복판이다 (레이아웃 상수 기준):
#   서쪽 통로  x ≈ 0.8   (지면 서쪽 끝 -2 와 불법주차 차량 서면 2.3 사이)
#   북쪽 띠    y ≈ 15.2  (벽이 y 14 에서 끝난다)
#   중앙 통로  x = 12.7  (블록 A 9.7 / 블록 B 15.7 의 한가운데)
#   남쪽 띠    y ≈ -3.5
#   동쪽 통로  x ≈ 28.8  (소방차 구역 동쪽 끝 28 과 지면 끝 30 사이)
WAYPOINTS = [
    (0.8, 15.2),      # 서쪽 통로를 끝까지 올라간다
    (12.7, 15.2),     # 북쪽 띠를 따라 중앙 통로 입구로
    (12.7, 0.0),      # 중앙 통로 종단 — 양쪽 블록이 전부 스캔에 들어온다
    (12.7, -3.5),     # 남쪽 띠로 빠져나온다
    (28.8, -3.5),     # 남쪽 띠를 따라 동쪽 끝으로
    (28.8, 15.2),     # 동쪽 통로를 올라간다 — 소방차 구역이 들어온다
    (14.0, 15.2),     # 북쪽 띠를 되짚어 간다 — 🔑 루프 클로저
]

# 기본 0.35 — 실물 TB3 정격(0.22)보다 빠르다. 시뮬이라 바퀴가 더 돌 수 있고,
# 매핑 품질 기준으로는 스캔 한 바퀴(0.1 s) 동안 밀리는 거리 3.5 cm ≤ 지도
# 1셀(5 cm)이라 문제없다. --speed 로 바꾼다. ⚠ 실물에서는 0.2 로 돌릴 것.
V_MAX = 0.35
# 🚨 회전을 천천히 한다. RTX 라이다는 스캔 한 바퀴(0.1 s) 동안 로봇이 돈
#    각도만큼 포인트가 통째로 밀린다 — 1.5 rad/s 로 돌렸더니 스캔이 ~8.6°
#    씩 왜곡돼 지도가 겹쳐 쌓였다 (실측). 0.5 rad/s 면 왜곡이 ~2.9° 로
#    줄어 지도 번짐이 셀 한두 칸 수준이 된다.
W_MAX = 0.5
ARRIVE = 0.4                     # 이 반경 안이면 도착 (m)
K_HEAD = 1.2                     # 방향 P 이득


class Explorer(Node):
    def __init__(self, waypoints=None, exit_on_done=False):
        super().__init__("amr1_explorer")
        self._world_wp = list(waypoints or WAYPOINTS)
        self._wp = [(x - START[0], y - START[1]) for x, y in self._world_wp]
        self._exit_on_done = exit_on_done
        self._i = 0
        self._n = 0
        self._pub = self.create_publisher(Twist, "/amr1/cmd_vel", 10)
        # 제어 주기를 벽시계 타이머가 아니라 odom 수신(시뮬 60 Hz)에 건다.
        # 시뮬이 실시간보다 느려도 제어가 시뮬 시간에 맞춰 같이 느려진다.
        self.create_subscription(Odometry, "/amr1/odom", self._on_odom, 10)
        self.get_logger().info(f"웨이포인트 {len(self._wp)}개 — 순찰 시작")

    def _on_odom(self, msg):
        self._n += 1
        if self._n % 6:                      # 60 Hz → 10 Hz 로 낮춰 명령
            return
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))

        if self._i >= len(self._wp):
            self._pub.publish(Twist())       # 정지 명령을 계속 낸다
            if self._exit_on_done:
                raise SystemExit(0)          # spin 을 뚫고 나가 finally 로 간다
            return

        tx, ty = self._wp[self._i]
        dx, dy = tx - p.x, ty - p.y
        dist = math.hypot(dx, dy)
        if dist < ARRIVE:
            wx, wy = self._world_wp[self._i]
            self.get_logger().info(f"WP{self._i} 도착 (월드 {wx}, {wy})")
            self._i += 1
            if self._i >= len(self._wp):
                self.get_logger().info("순찰 완료 — 정지. 지도를 저장할 것")
            return

        err = math.atan2(dy, dx) - yaw
        err = math.atan2(math.sin(err), math.cos(err))     # [-π, π]
        cmd = Twist()
        cmd.angular.z = max(-W_MAX, min(W_MAX, K_HEAD * err))
        # 방향이 크게 틀렸으면 제자리에서 먼저 돈다 — 통로가 좁아서
        # 크게 돌면서 전진하면 주차된 차를 스친다.
        cmd.linear.x = V_MAX if abs(err) < 0.4 else 0.03
        self._pub.publish(cmd)


def _parse_wp(s):
    """"x,y;x,y" → [(x, y), ...] — 월드 좌표."""
    return [tuple(float(v) for v in p.split(",")) for p in s.split(";") if p.strip()]


def main():
    global V_MAX
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--wp", metavar="X,Y;X,Y",
                    help="기본 순찰 경로 대신 이 웨이포인트(월드 좌표)만 돈다. "
                         "로봇을 특정 지점으로 옮길 때(구출 등) 쓴다")
    ap.add_argument("--exit-on-done", action="store_true",
                    help="마지막 웨이포인트 도착 시 노드를 끝낸다 (기본은 대기)")
    ap.add_argument("--speed", type=float, default=V_MAX,
                    help=f"직진 속도 m/s (기본 {V_MAX}). 실물 TB3 는 0.2 이하")
    args = ap.parse_args()
    V_MAX = args.speed

    rclpy.init()
    node = Explorer(waypoints=_parse_wp(args.wp) if args.wp else None,
                    exit_on_done=args.exit_on_done)

    # 🚨 SIGTERM 에서도 반드시 정지 명령을 내보낸다.
    #
    # PhysX 관절 드라이브는 **마지막 속도 목표를 계속 유지**한다 — 이 노드가
    # 정지 명령 없이 죽으면 로봇은 마지막 명령 그대로 **무인 주행**을 계속한다.
    # 실제로 `pkill`(SIGTERM)로 껐다가 로봇이 2분 동안 혼자 달려 주차 블록
    # 한가운데 처박힌 적이 있다. KeyboardInterrupt 는 SIGINT 만 잡으므로
    # SIGTERM 을 따로 걸어야 한다.
    import signal

    def _stop_and_exit(signum, frame):
        for _ in range(5):                   # QoS 큐에 확실히 실리게 몇 번
            node._pub.publish(Twist())
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop_and_exit)

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        for _ in range(5):
            node._pub.publish(Twist())       # 어떤 상황이든 멈추고 나간다
    rclpy.shutdown()


if __name__ == "__main__":
    main()
