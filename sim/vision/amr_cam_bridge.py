"""[ROS 3.10] AMR 카메라 → 웹 브리지 — OcrCam 영상을 모니터 대시보드로.

    patrol_ros
    python3 sim/vision/amr_cam_bridge.py                  # AMR1
    python3 sim/vision/amr_cam_bridge.py --robot amr2     # AMR2

씬이 발행하는 `amr_images/<robot>/ocr` (sensor_msgs/Image, 1280×720,
ros_bridge.wire 의 cam_robots) 를 받아 JPEG(q60)·base64 로
`POST /api/<robot>/frame/` 에 올린다. 서버는 메모리에만 들고 있고, 모니터
대시보드(`/monitor/`)의 "AMR (Police) 카메라" 패널이
`GET /api/<robot>/frame/latest/` 를 폴링해 표시한다 — **서버 코드 무수정**
(bridge_webcam.py 와 같은 패턴). 카메라 발행은 `--robots` 배선과 별개라
씬이 `--robots amr1` 이어도 AMR2 화면이 나온다.

전송은 벽시계 4 Hz 타이머 — 토픽(시뮬 10 Hz)이 그보다 느려도/빨라도
대시보드 갱신률은 일정하다.

## --gate — "출동 중에만 표시" (AMR2 시나리오에서 쓸 것)

`<robot>/on_duty` (std_msgs/Bool) 가 True 인 동안만 실화면을 올리고,
False(또는 발행자 없음)면 STANDBY 판을 올린다. 서버가 마지막 프레임을
계속 들고 있어서 전송만 끊으면 **멈춘 화면이 방송 중처럼 보이기 때문**에
빈 판을 능동적으로 올린다. on_duty 는 출동 노드가 출동 시작에 True,
복귀 완료에 False 를 발행한다 (라칭 QoS 아님 — 브리지를 먼저 띄울 것).

실물에서는 AMR 이 직접 POST 하므로 이 브리지는 시뮬 전용이다.
"""

import argparse
import base64
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
import pyver  # noqa: E402

pyver.require_ros("sim/vision/amr_cam_bridge.py")

os.environ.setdefault("ROS_DOMAIN_ID", "2")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import requests  # noqa: E402
import rclpy  # noqa: E402
from cv_bridge import CvBridge  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import Image  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

SERVER = os.environ.get("PATROL_SERVER", "http://127.0.0.1:8000")
JPEG_QUALITY = 60        # bridge_webcam.py 와 같은 값
POST_HZ = 4.0            # 벽시계 기준 전송률


def _standby(robot):
    img = np.full((360, 640, 3), 24, np.uint8)
    text = f"{robot.upper()} STANDBY"
    size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
    cv2.putText(img, text, ((640 - size[0]) // 2, (360 + size[1]) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (160, 160, 160), 2, cv2.LINE_AA)
    return img


class AmrCamBridge(Node):
    def __init__(self, robot, gate):
        super().__init__(f"{robot}_cam_bridge")
        self._robot = robot
        self._url = f"{SERVER}/api/{robot}/frame/"
        self._bridge = CvBridge()
        self._frame = None
        self._on_duty = not gate         # 게이트 없으면 항상 방송
        self._standby_sent = False

        self.create_subscription(Image, f"amr_images/{robot}/ocr",
                                 self._on_frame, 10)
        if gate:
            self.create_subscription(Bool, f"{robot}/on_duty",
                                     self._on_duty_cb, 10)
        self.create_timer(1.0 / POST_HZ, self._tick)
        self.get_logger().info(
            f"{robot} OcrCam → {self._url}"
            + (" (출동 중에만 — on_duty 게이트)" if gate else ""))

    def _on_frame(self, msg):
        self._frame = self._bridge.imgmsg_to_cv2(msg, "bgr8")

    def _on_duty_cb(self, msg):
        if msg.data != self._on_duty:
            self._on_duty = msg.data
            self.get_logger().info("출동 — 방송 시작" if msg.data
                                   else "복귀 — STANDBY")

    def _tick(self):
        if not self._on_duty:
            if not self._standby_sent:       # 대기판은 한 번만 올리면 된다
                self._standby_sent = True
                self._post(_standby(self._robot))
            return
        self._standby_sent = False
        if self._frame is not None:
            self._post(self._frame)

    def _post(self, img):
        _, buf = cv2.imencode(".jpg", img,
                              [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        payload = {"frame": base64.b64encode(buf).decode("utf-8")}
        threading.Thread(
            target=self._post_http, args=(payload,), daemon=True).start()

    def _post_http(self, payload):
        try:
            requests.post(self._url, json=payload, timeout=1)
        except Exception:
            pass                             # 서버 잠깐 죽어도 다음 틱에 복구


def main():
    ap = argparse.ArgumentParser(description="AMR OcrCam → 모니터 대시보드")
    ap.add_argument("--robot", choices=("amr1", "amr2"), default="amr1")
    ap.add_argument("--gate", action="store_true",
                    help="<robot>/on_duty 가 True 인 동안만 실화면을 올린다 "
                         "(꺼져 있으면 STANDBY 판). AMR2 시나리오용")
    args = ap.parse_args()

    rclpy.init()
    node = AmrCamBridge(args.robot, args.gate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
