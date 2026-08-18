"""오버헤드 웹캠 차량 탐지 → 맵 좌표(MarkerArray) 발행.

실제 시스템의 "웹캠 + YOLO" 자리를 시뮬에서 채우는 노드다. 프레임에서 차량을
찾아 **Nav2 안전 접근 보정 좌표(observation)** 를 계산해 발행하면,
`bridge/bridge_webcam.py` 가 받아 `POST /api/parking/` 로 올린다
(status=DETECTED). CLAUDE.md 규약대로 **좌표만** 보낸다 — zone_type /
vehicle_type 판별은 AMR1 몫이다.

    구독   webcam_images/webcam1/detections   sensor_msgs/Image (1280×720, 10 Hz)
    발행   webcam_objects/map_detections      visualization_msgs/MarkerArray

## 픽셀 → 월드 (선형인 이유)

웹캠은 회전 없이 수직 아래(-Z)를 본다 (`lot.py` build 참고). 그래서
이미지 +u = 월드 +X, +v = 월드 -Y 이고, 바닥(z=0)까지 핀홀 투영은 배율
하나로 끝난다:

    m/px = 높이 × 조리개 / 초점거리 / 해상도
         = 28 × 20.955 / 15.2 / 1280 ≈ 0.0302   (세로도 같은 값 — 검산됨)

숫자는 `layout.WEBCAM` 하나만 쓴다. 씬(lot.py)과 값이 갈라지면 좌표가
통째로 밀리므로 여기서 다시 정의하지 않는다.

## 왜 윤곽(contour) 방식이 아닌가 (실측)

처음에는 "비바닥 마스크 → 윤곽 → 자리에 스냅" 으로 갔다가 11대 중 3대만
잡혔다. 그림자가 차·벽을 한 덩어리로 이어 붙여 **블록 전체가 윤곽 하나**
(117k px)로 나오고, 중심이 그림자 쪽으로 밀려 스냅 반경을 벗어난다.
그래서 방향을 뒤집었다 — 자리(주차면·불법차선)는 사전에 알고 있으므로,
**자리마다** 안쪽 박스의 비바닥 픽셀 비율로 점유를 판정한다. 붙어 있는
블롭을 나눌 필요가 아예 없어진다.

    비바닥 = |픽셀 − 프레임 중앙값(=바닥색)| 채널 최대가 25 초과

점유 박스는 그림자를 피해서 잡는다 (전부 프레임 실측으로 확인한 값):

- 그림자는 남·동쪽으로 최대 ~1.6 m 뻗는다. A/B 주차면 점유 박스를 자리
  중심의 **남쪽 띠**(cy-0.6 ~ cy-0.1)로 줄이면 북쪽 이웃 차 그림자가
  안 들어온다 (경차 반폭 0.775 라 차가 있으면 띠가 꽉 찬다).
- 🚨 장애인 표지는 자리 중심에 칠한 2.31 m 파란 정사각형이라 어느 중앙
  박스로도 못 피하고, 렌더 색도 조명 때문에 (B228,G174) 로 밝아져 색으로
  거르기엔 청록 차량(EV)과 겹친다. 대신 표지 밖 **좌우 플랭크 패치**
  (|dx| 1.3~1.7 m)로 판정한다 — 제일 짧은 경차(3.6 m)도 반길이 1.8 이라
  차가 있으면 패치가 덮인다.
- 🚨 소방 경계선 주황은 렌더에서 노랑(R225,G177,B36)으로 뜬다 (layout.py
  의 색 포화 주석 참고). R>180, 120<G<0.9R, B<80 을 바닥 취급한다 —
  소방차 빨강(G 낮음)과 경차 노랑(G≈R, B>80)은 이 조합에 안 걸린다.

## observation 좌표

번호판(차 뒤)은 항상 통로를 향한다 (`layout.stalls()` 의 yaw 참고).
차종을 모르니 차 길이도 재지 않는다 — 자리 밴드 안 비바닥 픽셀의
**통로 쪽 경계**(2/98 퍼센타일)가 곧 번호판 자리다. 거기서 통로 방향으로
`APPROACH_DIST` 만큼 떨어진 점이 observation 이다 (lot.approach_pose 의
dist 와 같은 값). 그림자가 통로 쪽 경계를 부풀리면 AMR 이 조금 멀리 서게
될 뿐이라 안전한 방향으로만 틀린다.

실행 (Humble 쪽, python 3.10):
    source /opt/ros/humble/setup.bash
    python3 sim/vision/webcam_detect.py
"""

import math
import os
import sys

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from visualization_msgs.msg import Marker, MarkerArray

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scenes"))
import layout  # noqa: E402  (순수 파이썬 — Isaac 불필요)

RES = (1280, 720)
CAM_X, CAM_Y, CAM_Z = layout.WEBCAM["pos"]
M_PER_PX = CAM_Z * layout.WEBCAM["aperture"] / layout.WEBCAM["focal"] / RES[0]

COLOR_THRESH = 25        # 바닥색과의 채널 거리 (uint8)
OCC_FRACTION = 0.35      # 점유 박스 안 비바닥 비율이 이보다 크면 차가 있다
APPROACH_DIST = 2.0      # 번호판 → AMR 거리. lot.approach_pose 의 dist 와 같다
# 앞판(북쪽)에서 볼 때만 쓰는 거리.
# 🚨 두 제약이 겹친다. ① 바닥 북단이 17.0 이고 ② 지도의 빈 공간이 16.75
#    까지다 (북쪽엔 벽이 없어 라이다가 아무것도 못 맞히므로, 로봇이 실제로
#    밟은 데까지만 지도가 늘어난다). amr1_nav.goal_blocked 는 목표 주변
#    0.15 m 를 검사하므로 관측점은 16.60 이하여야 하고, 전역 코스트맵
#    robot_radius 0.28 도 지도 경계 안에 들어가야 한다.
#    또 픽셀로 잰 차 코가 layout 값(14.95)보다 ~0.17 m 북으로 나온다
#    (그림자·번짐) — 실측 관측점 = 15.12 + 이 값.
#    1.5 → 16.62 (검사 16.77 > 16.75 ❌).  1.3 → 16.42 (검사 16.57 ✅,
#    코스트맵 여유 0.33 > 0.28 ✅).
APPROACH_DIST_N = 1.3
CONFIRM_FRAMES = 3       # 연속 N번 점유로 잡혀야 발행 (한 프레임 노이즈 무시)
PROCESS_EVERY = 5        # 10 Hz 입력을 2 Hz 로 낮춰 처리


def _slots():
    """검사할 자리 목록 — 차량 배정과 무관한 기하 정보만.

    각 항목: key, axis('x' 통로가 ±X 쪽 / 'y' 통로가 -Y 쪽), sign(통로 방향),
             occs = 점유 판정 박스들 [(x0, x1, y0, y1), ...] — 그림자·표지를
                    피해 잡는다 (docstring "탐지 방법" 참고)
             band = 번호판 경계 탐색 밴드 (x0, x1, y0, y1) — 차폭보다 좁게
             obs_fix = 통로축에 수직인 고정 좌표 (A/B 는 cy, 소방·벽쪽은 cx)
    """
    out = []
    for st in layout.stalls():
        cx, cy = st["center"]
        if st["zone"] == "DISABLED":   # 표지(중심 2.31 m □) 밖 플랭크 패치
            occs = [(cx - 1.7, cx - 1.3, cy - 0.5, cy + 0.5),
                    (cx + 1.3, cx + 1.7, cy - 0.5, cy + 0.5)]
        elif st["yaw"] in (90.0, -90.0):   # 그림자 없는 남쪽 띠
            occs = [(cx - 1.2, cx + 1.2, cy - 0.6, cy - 0.1)]
        else:                          # 소방차 구역
            occs = [(cx - 1.0, cx + 1.0, cy - 1.5, cy + 1.5)]

        if st["yaw"] == 90.0:          # 블록 A — 번호판이 +X(통로) 쪽
            out.append(dict(key=f"stall_{st['id']}", axis="x", sign=+1,
                            occs=occs,
                            band=(cx - 2.6, cx + 3.6, cy - 0.7, cy + 0.7),
                            obs_fix=cy))
        elif st["yaw"] == -90.0:       # 블록 B — 번호판이 -X(통로) 쪽
            out.append(dict(key=f"stall_{st['id']}", axis="x", sign=-1,
                            occs=occs,
                            band=(cx - 3.6, cx + 2.6, cy - 0.7, cy + 0.7),
                            obs_fix=cy))
        else:                          # 소방차 구역 — 번호판이 -Y 쪽
            out.append(dict(key=f"stall_{st['id']}", axis="y", sign=-1,
                            occs=occs,
                            band=(cx - 1.3, cx + 1.3, cy - 4.1, cy + 3.6),
                            obs_fix=cx))
    for i, y in enumerate(layout.ILLEGAL_Y):
        x = layout.ILLEGAL_X            # 세로(코 +Y) 주차 — 번호판이 -Y 쪽
        out.append(dict(key=f"illegal_{i}", axis="y", sign=-1,
                        occs=[(x - 0.6, x + 0.6, y - 1.2, y + 1.2)],
                        band=(x - 0.8, x + 0.8, y - 2.6, y + 2.6),
                        obs_fix=x))
    return out


def world_to_px(x, y):
    return (RES[0] / 2.0 + (x - CAM_X) / M_PER_PX,
            RES[1] / 2.0 - (y - CAM_Y) / M_PER_PX)


def _free_at(mask, x, y, half=0.30):
    """관측점 (x, y) 에 로봇이 설 수 있는가 — 주변이 비어 있고 바닥 안인가.

    벽쪽 세로주차처럼 앞뒤로 차가 늘어서면 "번호판에서 N m" 점이 **이웃 차
    몸통 안**에 떨어진다. 웹캠은 이미 어디에 차가 있는지(mask) 알고 있으니
    좌표를 내보내기 전에 여기서 걸러 반대쪽 판을 보게 한다.
    """
    gx0, gx1, gy0, gy1 = layout.GROUND
    if not (gx0 + half < x < gx1 - half and gy0 + half < y < gy1 - half):
        return False
    u0, u1, v0, v1 = _rect_px(x - half, x + half, y - half, y + half)
    if u1 <= u0 or v1 <= v0:
        return False
    return bool(mask[v0:v1, u0:u1].mean() < 0.10)


def _rect_px(x0, x1, y0, y1):
    """월드 사각형 → (u0, u1, v0, v1) 픽셀. y 부호가 뒤집힌다."""
    u0, v1 = world_to_px(x0, y0)
    u1, v0 = world_to_px(x1, y1)
    return (max(0, int(u0)), min(RES[0], int(u1) + 1),
            max(0, int(v0)), min(RES[1], int(v1) + 1))


class WebcamDetect(Node):
    def __init__(self):
        super().__init__("webcam_detect")
        self.bridge = CvBridge()
        self.slots = _slots()
        self.hits = {}           # key → 연속 점유 횟수
        self.confirmed = {}      # key → (obs_x, obs_y, yaw°)
        self._n = 0

        self.pub = self.create_publisher(
            MarkerArray, "webcam_objects/map_detections", 10)
        self.create_subscription(
            Image, "webcam_images/webcam1/detections", self._on_frame, 10)
        self.get_logger().info(
            f"웹캠 탐지 시작 — {M_PER_PX:.4f} m/px, 자리 {len(self.slots)}개")

    def _on_frame(self, msg):
        self._n += 1
        if self._n % PROCESS_EVERY:
            return
        frame = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        seen = self._detect(frame)

        for key in list(self.hits):
            if key not in seen:
                self.hits[key] = 0
        for key, obs in seen.items():
            self.hits[key] = self.hits.get(key, 0) + 1
            if self.hits[key] == CONFIRM_FRAMES and key not in self.confirmed:
                self.confirmed[key] = obs
                self.get_logger().info(
                    f"차량 확정 {key}: 관측 좌표 ({obs[0]:.2f}, {obs[1]:.2f})")

        if self.confirmed:
            self._publish()

    def _detect(self, frame):
        floor = np.median(frame[100:620, 200:1080].reshape(-1, 3), axis=0)
        f16 = frame.astype(np.int16)
        dist = np.abs(f16 - floor.astype(np.int16)).max(axis=2)
        mask = dist > COLOR_THRESH
        # 소방 경계선(주황 → 렌더에서 노랑)은 바닥 취급 — docstring 참고
        b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
        mask &= ~((r > 180) & (g > 120) & (g < 0.9 * r) & (b < 80))
        # 🚨 그림자도 바닥 취급 — 실차 치수(총고 1.45)로 그림자가 길어져
        #    빈 칸(스톨 4)이 이웃 차 그림자에 거의 덮인다 (남쪽 띠 회피로는
        #    부족). 렌더 실측: 그림자 = 무채색(chroma ~9) + 중간 밝기(v 55
        #    ~115), 차체·캐빈 = 유채색(chroma ~30+), 바퀴 = 매우 어두움
        #    (v<40, 바닥 취급하면 안 되므로 하한을 둔다).
        #    ⚠ 무채색 회색 차체(BODY_RGB 의 0.85 은색 등)는 캐빈·바퀴로만
        #      잡히게 된다 — seed 7 에는 없지만 seed 를 바꾸면 확인할 것.
        v = f16.mean(axis=2)
        chroma = f16.max(axis=2) - f16.min(axis=2)
        floor_v = float(floor.mean())
        mask &= ~((chroma < 16) & (v > 40) & (v < floor_v * 0.82))

        seen = {}
        for sl in self.slots:
            pix = np.concatenate([
                mask[v0:v1, u0:u1].ravel()
                for u0, u1, v0, v1 in (_rect_px(*box) for box in sl["occs"])])
            if pix.size == 0 or pix.mean() < OCC_FRACTION:
                continue

            u0, u1, v0, v1 = _rect_px(*sl["band"])
            vs, us = np.nonzero(mask[v0:v1, u0:u1])
            if len(us) < 50:
                continue
            if sl["axis"] == "x":
                # 통로 쪽 경계 픽셀 → 월드 x. 2/98 퍼센타일로 점 노이즈 무시
                pct = 98 if sl["sign"] > 0 else 2
                edge = CAM_X + (np.percentile(us, pct) + u0 - RES[0] / 2.0) * M_PER_PX
                ox = edge + sl["sign"] * APPROACH_DIST
                oy = sl["obs_fix"]
                yaw = 180.0 if sl["sign"] > 0 else 0.0
            else:
                # 통로가 -Y 쪽 → 이미지에서는 v 가 큰 쪽이 경계다.
                # 차에는 앞·뒤 번호판이 둘 다 있으므로 남/북 두 관측점을
                # 만들어 **설 수 있는 쪽**을 고른다. 뒤판(남쪽)이 기본이고,
                # 막혔으면 앞판(북쪽)을 본다. 둘 다 막히면 남쪽을 그대로 두어
                # 이벤트는 남기고 AMR1 이 UNREACHABLE 로 종결하게 한다.
                ox = sl["obs_fix"]
                south = CAM_Y - (np.percentile(vs, 98) + v0 - RES[1] / 2.0) * M_PER_PX
                north = CAM_Y - (np.percentile(vs, 2) + v0 - RES[1] / 2.0) * M_PER_PX
                cand = [(south - APPROACH_DIST, 90.0),      # 뒤판을 본다
                        (north + APPROACH_DIST_N, 270.0)]   # 앞판을 본다
                oy, yaw = cand[0]
                for c_y, c_yaw in cand:
                    if _free_at(mask, ox, c_y):
                        oy, yaw = c_y, c_yaw
                        break
            seen[sl["key"]] = (ox, oy, yaw)
        return seen

    def _publish(self):
        arr = MarkerArray()
        for i, (key, (ox, oy, yaw)) in enumerate(sorted(self.confirmed.items())):
            m = Marker()
            m.header.frame_id = "map"
            m.header.stamp = self.get_clock().now().to_msg()
            m.ns = "webcam1"
            m.id = i
            m.type = Marker.CUBE
            m.pose.position.x = ox
            m.pose.position.y = oy
            m.pose.orientation.z = math.sin(math.radians(yaw) / 2.0)
            m.pose.orientation.w = math.cos(math.radians(yaw) / 2.0)
            arr.markers.append(m)
        self.pub.publish(arr)


def main():
    rclpy.init()
    node = WebcamDetect()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
