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
sys.path.insert(0, os.path.join(_HERE, "..", "vision"))
import pyver  # noqa: E402

pyver.require_ros("sim/nav2/amr1_nav.py")

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

import layout  # noqa: E402  (sim/scenes — Isaac 없이 python3 로 돈다)
import zone_classify  # noqa: E402  (sim/vision)

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
        # 출동 상태 — amr_cam_bridge --gate 가 이걸 보고 카메라 방송을
        # 켜고 끈다 ("움직이는 로봇의 카메라만"). 라칭 QoS 가 아니라서
        # 전이 시점 외에 피드백(5초 주기)에서도 반복 발행해 준다.
        self._duty_pub = self.create_publisher(Bool, "/amr1/on_duty", 10)
        self._duty = False
        # 현장 판별용 — OcrCam 최신 프레임과 현재 자세(odom → 월드)
        self._cv = CvBridge()
        self._frame = None               # (mono_time, bgr)
        self._pose = None                # (wx, wy, yaw°)
        self.create_subscription(Image, "amr_images/amr1/ocr",
                                 self._on_image, 5)
        self.create_subscription(Odometry, "/amr1/odom", self._on_odom, 10)
        self.save_frames = None          # 캘리브레이션용 저장 디렉토리
        # 출동 전 목표 검증용 정적 지도 (map_server, transient local)
        from nav_msgs.msg import OccupancyGrid
        from rclpy.qos import QoSProfile, DurabilityPolicy
        self._map = None
        self.create_subscription(
            OccupancyGrid, "/map", lambda m: setattr(self, "_map", m),
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))

    def goal_blocked(self, wx, wy, radius=0.15):
        """관측점이 지도상 빈 공간이 아니면 True — 이동 없이 스킵하기 위해.

        벽쪽 세로주차처럼 관측점이 이웃 차량 몸체 **안**에 떨어지는 이벤트로
        출동하면, 플래너가 차량 사이 틈으로 우회로를 내다 로봇이 낀다
        (실측 2회). 목표 주변 radius 안이 전부 확실한 빈 공간(0≤v<50)일
        때만 출동한다. 지도를 아직 못 받았으면 판단 보류(False).
        """
        if self._map is None:
            # transient_local 라치가 아직 안 왔으면 잠깐 기다린다 — 첫 목표
            # 직전에 호출되면 구독 연결이 막 맺어진 참일 수 있다.
            t0 = time.monotonic()
            while self._map is None and time.monotonic() - t0 < 5.0:
                rclpy.spin_once(self, timeout_sec=0.2)
            if self._map is None:
                self.get_logger().warn("/map 미수신 — 목표 검증 생략")
                return False
        info = self._map.info
        mx, my = wx - START[0], wy - START[1]
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

    def _on_image(self, msg):
        self._frame = (time.monotonic(), self._cv.imgmsg_to_cv2(msg, "bgr8"))

    def _on_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        yaw = math.degrees(math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                      1.0 - 2.0 * (q.y * q.y + q.z * q.z)))
        self._pose = (p.x + START[0], p.y + START[1], yaw)

    # ── 현장 판별 (도착 후) ───────────────────────────────────────
    def classify_here(self, event_id=None):
        """도착 지점에서 프레임을 새로 받아 구역·차종을 판별하고 서버에 올린다.

        DISABLED 는 vehicle_type 판정에 번호판+DB 조회가 필요해서 PATCH 를
        하지 않는다 — OCR 단계(다음 작업)에서 함께 올린다.
        """
        t_arrival = time.monotonic()
        while rclpy.ok():                # 도착 이후 프레임이 와야 신선하다
            rclpy.spin_once(self, timeout_sec=0.5)
            if self._frame and self._frame[0] > t_arrival and self._pose:
                break
            if time.monotonic() - t_arrival > 15.0:
                self.get_logger().warn("프레임 대기 시간 초과 — 판별 생략")
                return None
        frame, (wx, wy, yaw) = self._frame[1], self._pose

        res = zone_classify.classify(frame, wx, wy, yaw)
        self.get_logger().info(
            f"판별: zone={res['zone_type']} vehicle={res['vehicle_type']} "
            f"(stall={res['stall_id']}, {res['measurements']})")

        if self.save_frames and event_id is not None:
            os.makedirs(self.save_frames, exist_ok=True)
            path = os.path.join(self.save_frames,
                                f"ev{event_id}_{wx:.2f}_{wy:.2f}_{yaw:.0f}.jpg")
            cv2.imwrite(path, frame)

        if event_id is not None and res["vehicle_type"] is not None:
            try:
                r = requests.patch(
                    f"{SERVER}/api/parking/{event_id}/zone/",
                    json={"zone_type": res["zone_type"],
                          "vehicle_type": res["vehicle_type"]}, timeout=2)
                self.get_logger().info(f"PATCH zone → {r.status_code}")
            except Exception as e:
                self.get_logger().warn(f"PATCH 실패: {e}")
        elif res["vehicle_type"] is None:
            self.get_logger().info("DISABLED — 번호판 확인(OCR 단계)까지 판정 보류")
        return res

    def set_duty(self, on):
        self._duty = on
        for _ in range(3):                    # QoS 큐에 확실히 실리게
            self._duty_pub.publish(Bool(data=on))

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
        rclpy.spin_once(self, timeout_sec=0.2)          # /map 라치 수신 기회
        if self.goal_blocked(wx, wy):
            self.get_logger().warn(
                f"목표 ({wx:.2f}, {wy:.2f})가 지도상 장애물/미탐사 안 — "
                "접근 불가, 출동 생략")
            return False
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

        # 🚨 목표 수락 응답이 DDS 에서 간헐적으로 유실된다 (bt_navigator 쪽에
        #    "Failed to send goal response (timeout)" 만 남고 클라이언트는
        #    영원히 기다리는 레이스 — 실측). 응답을 10초만 기다리고 재전송한다.
        #    유실 케이스에도 서버는 목표를 이미 물고 있을 수 있는데,
        #    NavigateToPose 는 새 목표가 오면 이전 것을 선점하므로 무해하다.
        self._goal_handle = None
        for attempt in range(3):
            send = self._ac.send_goal_async(goal, feedback_callback=self._on_feedback)
            rclpy.spin_until_future_complete(self, send, timeout_sec=10.0)
            if send.done():
                self._goal_handle = send.result()
                break
            self.get_logger().warn(f"목표 수락 응답 유실 — 재전송 ({attempt + 1}/3)")
        if not self._goal_handle or not self._goal_handle.accepted:
            self.get_logger().error("목표가 거부됐다 (또는 응답 3회 유실)")
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
            self._duty_pub.publish(Bool(data=self._duty))   # 늦게 뜬 브리지용
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
    ap.add_argument("--no-classify", action="store_true",
                    help="도착 후 구역·차종 판별(+PATCH)을 건너뛴다")
    ap.add_argument("--save-frames", metavar="DIR",
                    help="도착 프레임을 저장 (판별 캘리브레이션용)")
    args = ap.parse_args()

    rclpy.init()
    node = Amr1Nav()

    def _cancel_and_exit(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cancel_and_exit)

    try:
        node.save_frames = args.save_frames
        classify = not args.no_classify
        if args.goal:
            v = [float(x) for x in args.goal.split(",")]
            node.set_duty(True)
            if node.navigate(v[0], v[1], v[2] if len(v) > 2 else None) and classify:
                node.classify_here()               # 로그만 (이벤트 없음)
        elif args.all:
            events = node.fetch_all()
            node.get_logger().info(f"DETECTED {len(events)}건 — 순서대로 방문")
            node.set_duty(True)
            done = 0
            for e in events:
                node.get_logger().info(f"── 이벤트 id={e['id']} ──")
                if node.navigate(e["observation_x"], e["observation_y"]):
                    done += 1
                    if classify:
                        node.classify_here(e["id"])
            node.get_logger().info(f"방문 완료 {done}/{len(events)}")
        else:
            e = node.fetch_next()
            if e:
                node.get_logger().info(f"이벤트 id={e['event_id']} 수신 (한 번)")
                node.set_duty(True)
                if node.navigate(e["observation_x"], e["observation_y"]) and classify:
                    node.classify_here(e["event_id"])
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.set_duty(False)             # 복귀/종료 — 카메라 방송 끔
        node.cancel()                    # 어떤 경로로 나가든 목표를 물고 죽지 않는다
    rclpy.shutdown()


if __name__ == "__main__":
    main()
