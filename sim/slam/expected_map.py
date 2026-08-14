"""[공용 3.10] 정답 점유 지도 — 라이다 높이(z 0.18 m)에서 **보여야 하는** 것.

    python3 sim/slam/expected_map.py --seed 7 --out expected.png

SLAM 결과를 눈으로 검증할 때 쓴다. 웹캠(항공 시점)과 지도(2D 수평 단면)는
보이는 게 다르다:

    검정      라이다에 잡히는 것 — 벽, 차의 옆면(사이드실 높이), AMR
    옅은 색   주차선 페인트 — 높이 6 mm 라 **라이다에 절대 안 잡힌다.**
              웹캠에는 선명하지만 지도에는 있을 수 없다. 참고용으로만 그린다
    흰색      빈 공간. 주차장 가장자리는 벽이 없으므로 지도에서도 **경계선이
              없다** — 빈 공간이 그냥 흐릿하게 끝나는 것이 정상이다
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scenes"))
import layout  # noqa: E402  (숫자만 다루는 파일이라 어느 파이썬에서든 돈다)

from PIL import Image, ImageDraw  # noqa: E402

RES = 0.05          # m/셀 — slam_params.yaml 의 resolution 과 같게
SCALE = 3           # 셀당 픽셀 — map_snapshot.py 와 같게
X0, X1, Y0, Y1 = -2.0, 30.0, -6.0, 17.0      # lot.GROUND


def _px(x, y, h):
    """월드 (x, y) → 이미지 픽셀. row 0 이 북쪽(y max)이 되게 뒤집는다."""
    return ((x - X0) / RES * SCALE, (h - (y - Y0) / RES) * SCALE)


def _rect(d, cx, cy, w, l, yaw_deg, h, fill):
    """중심 (cx,cy), 폭 w(로컬 x), 길이 l(로컬 y), yaw 회전한 사각형."""
    a = math.radians(yaw_deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for dx, dy in ((-w / 2, -l / 2), (w / 2, -l / 2), (w / 2, l / 2), (-w / 2, l / 2)):
        x = cx + dx * ca - dy * sa
        y = cy + dx * sa + dy * ca
        pts.append(_px(x, y, h))
    d.polygon(pts, fill=fill)


def render(plan):
    w_cells = int((X1 - X0) / RES)
    h_cells = int((Y1 - Y0) / RES)
    im = Image.new("RGB", (w_cells * SCALE, h_cells * SCALE), (255, 255, 255))
    d = ImageDraw.Draw(im)
    h = h_cells

    # ── 참고용: 주차선 (라이다에 안 보인다 — 옅게) ─────────────
    line_rgb = {"NORMAL": (200, 200, 200), "COMPACT": (150, 180, 255),
                "DISABLED": (150, 180, 255), "EV": (150, 220, 170),
                "FIRE": (255, 200, 150)}
    for st in plan["stalls"]:
        cx, cy = st["center"]
        sw, depth = st["size"]
        c = line_rgb[st["zone"]]
        if st["zone"] == "FIRE":
            _rect(d, cx, cy - depth / 2, sw, 0.24, 0, h, c)
            _rect(d, cx, cy + depth / 2, sw, 0.24, 0, h, c)
            _rect(d, cx - sw / 2, cy, 0.24, depth, 0, h, c)
            _rect(d, cx + sw / 2, cy, 0.24, depth, 0, h, c)
        else:
            # 블록 주차면은 가로로 길다 — 폭이 Y, 깊이가 X (lot.py 와 동일)
            _rect(d, cx, cy - sw / 2, depth, 0.12, 0, h, c)
            _rect(d, cx, cy + sw / 2, depth, 0.12, 0, h, c)

    # ── 라이다에 실제로 잡히는 것 (검정) ───────────────────────
    K = (0, 0, 0)
    for wx0, wx1 in (layout.WALL_A_X, layout.WALL_B_X):          # 벽 2개
        wy0, wy1 = layout.WALL_Y
        _rect(d, (wx0 + wx1) / 2, (wy0 + wy1) / 2, wx1 - wx0, wy1 - wy0, 0, h, K)

    def car(cx, cy, yaw, kind):
        bw, bl, _ = layout.VEHICLES[kind]["body"]
        # 사이드실(rocker) 발자국 — 라이다 스캔 평면이 지나는 단면이다
        _rect(d, cx, cy, bw * 0.96, bl * 0.98, yaw, h, K)

    for st in plan["stalls"]:
        if st["vehicle"]:
            car(*st["center"], st["yaw"], st["vehicle"]["kind"])
    for f in plan["illegal_fixed"]:
        car(*f["center"], f["yaw"], f["vehicle"]["kind"])

    # 서 있는 AMR2 도 장애물이다 (AMR1 이 스캔하면 잡힌다)
    ax, ay = layout.AMR_START[1]
    d.ellipse([_px(ax - 0.09, ay + 0.09, h), _px(ax + 0.09, ay - 0.09, h)], fill=K)
    return im


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--occupancy", type=float, default=0.65)
    ap.add_argument("--illegal-bias", type=float, default=0.45)
    ap.add_argument("--out", default="expected_map.png")
    a = ap.parse_args()
    im = render(layout.plan(a.seed, a.occupancy, a.illegal_bias))
    im.save(a.out)
    print(f"저장: {a.out}  (검정 = 라이다가 봐야 할 것 / 옅은 색 = 페인트, 지도에 없어야 정상)")
