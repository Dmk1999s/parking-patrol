"""[ROS 3.10] 구역·차종 판별 — AMR1 이 현장(관측 지점)에서 내리는 판단.

    python3 sim/vision/zone_classify.py --frame f.jpg --pose 11.9,5.4,180

CLAUDE.md 2단계의 시뮬 구현이다. 도착한 관측 지점에서 OcrCam 프레임과
로봇의 현재 위치(월드)로 다음을 정한다:

    zone_type     주차선 색(OpenCV HSV) + 사전 정의 구역 좌표 비교
    vehicle_type  구역 규칙에 맞는 차인가 — 경차=차폭, 전기차=파란 번호판,
                  소방차=빨간 대형 차체. DISABLED 는 번호판+DB 조회가
                  필요해서 여기서는 판정하지 않는다 (OCR 단계로 미룸).

## 판별 순서 (CLAUDE.md 를 시뮬 색상에 맞게 적용)

실물 시나리오는 "주황 주차선 → NORMAL 스킵" 이지만 이 시뮬의 구역 색은
NORMAL=흰색 · COMPACT/DISABLED=파랑 · EV=초록 · FIRE=주황이다 (layout.ZONES,
사용자 확정). 그래서:

1. 로봇 위치·방향으로 **정면의 주차면**을 찾는다 — 사전 정의 좌표
   (`layout.stalls()`, AMR 팀의 "맵에 사전 정의한 구역 좌표"에 해당) 중
   7.5 m 안 + 진행 방향 ±40° 안에서 가장 가까운 것.
2. 정면에 주차면이 없으면 → `Not` (벽쪽 불법주차가 여기 걸린다).
3. 있으면 그 주차면의 구역이 zone_type. 바닥 띠의 주차선 색을 같이 재서
   교차 검증한다 (색이 갈리면 로그로 남긴다 — 좌표가 우선).

색만으로 안 가르는 이유: COMPACT 와 DISABLED 가 같은 파랑이고 (README),
흰 선은 벽·은색 차와 HSV 로 겹치기 쉽다. 좌표가 1차 근거, 색은 검증이다.

## 카메라 기하 (lot.py 실측 상수에서 유도)

OcrCam: 높이 0.20 m, 위로 6°, f_px = 1280·15.2/20.955 ≈ 928.
거리 d 의 바닥이 화면에서 어느 행(row)인지:

    row(d) = 360 + f·tan(6° + atan(0.20/d))

    d=4 m → r≈505   d=2 m → r≈552   d=1 m → r≈649

주차선 앞 경계는 로봇에서 ~2.3 m (번호판 2 m + 여유) → r≈540 부근.
바닥 띠는 row(4.0)~row(1.0) 을 쓴다.

⚠ HSV 임계값은 README "구역 색" 절(오버헤드 실측)을 출발점으로 **AMR
시점에서 재캘리브레이션한 값**이다. 조명·각도가 바뀌면 다시 잰다.
"""

import argparse
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scenes"))
import layout  # noqa: E402  (python3 로 그냥 돈다)

# ── 카메라 기하 (lot.py 와 짝) ──────────────────────────────────
F_PX = 1280 * 15.2 / 20.955          # ≈ 928
CAM_H, CAM_PITCH = 0.20, 6.0
W, H = 1280, 720

# ── 정면 주차면 탐색 ────────────────────────────────────────────
# 정상 관측점은 번호판 축선 위라 주차면 중심까지 ≤ ~5.8 m(소방)·정면 ≈0°다.
# 느슨하게 두면 벽쪽(Not) 관측점에서 대각선 너머 주차면이 걸린다 — 실측:
# (3.2,-1.51) yaw 76°(도착 오차 포함)에서 6.2 m·26° 의 COMPACT 가 잡혔다.
# 여유는 도착 오차(xy 0.25 m, yaw 14°)만큼만 준다.
STALL_MAX_DIST = 6.0                 # 관측점→주차면 중심
STALL_MAX_BEARING = 25.0             # 진행 방향에서 벗어난 각 (°)

# ── HSV 임계값 (OpenCV H 0~180) ────────────────────────────────
LINE_MASKS = {                       # 주차선 색 → (H0,H1,Smin,Vmin)
    "NORMAL":  (0, 180, 0, 150),     # 흰색: S 로 거른다 (아래 WHITE_S_MAX)
    "FIRE":    (10, 28, 110, 60),
    "EV":      (55, 90, 60, 40),
    "BLUE":    (95, 120, 60, 40),    # COMPACT/DISABLED 공통
}
WHITE_S_MAX = 55
LINE_MIN_PX = 800                    # 바닥 띠에서 이 이상 잡혀야 "선이 있다"

RED_S_MIN, RED_PX_MIN = 110, 30000   # 소방차(빨간 대형 차체)
PLATE_BLUE = (95, 130, 100, 60)      # EV 파란 번호판
# 🚨 도착 자세에 따라 파란 판 픽셀 수가 8386→2501 까지 흔들린다 (실측).
#    2500 으로 뒀다가 정상 전기차가 기준 미달로 불법 처리된 회귀가 있었다.
#    SEDAN 흰 판은 0~151 px 라 600 이면 양쪽 다 4배 이상 여유다.
PLATE_PX_MIN = 600
PLATE_Z, PLATE_H_M = 0.42, 0.110     # 판 중심 높이·판 높이 (lot.py·plate.py 와 짝)
PLATE_D_MIN, PLATE_D_MAX = 1.0, 3.0  # 관측점→판 거리 (설계 1.3~2.0 + 도착 오차)
COMPACT_MAX_W = 1.70                 # 차폭 이하면 경차 (1.55 vs 1.80)
DARK_V_MAX = 55                      # 차폭 측정용 어두운 픽셀 (바퀴·하부 그림자)
DARK_COL_MIN = 4                     # 열에 이만큼 쌓여야 차 실루엣


def row_at(h, d):
    """높이 h(m)·거리 d(m) 인 점이 놓이는 이미지 행."""
    ang = math.radians(CAM_PITCH) + math.atan2(CAM_H - h, d)
    return int(H / 2 + F_PX * math.tan(ang))


def ground_row(d):
    """거리 d(m)의 바닥이 놓이는 이미지 행."""
    return row_at(0.0, d)


def stall_ahead(wx, wy, yaw_deg):
    """로봇 정면의 주차면 (사전 정의 좌표 비교). 없으면 None."""
    best = None
    for st in layout.stalls():
        cx, cy = st["center"]
        dist = math.hypot(cx - wx, cy - wy)
        if dist > STALL_MAX_DIST:
            continue
        bearing = math.degrees(math.atan2(cy - wy, cx - wx)) - yaw_deg
        bearing = (bearing + 180.0) % 360.0 - 180.0
        if abs(bearing) > STALL_MAX_BEARING:
            continue
        if best is None or dist < best[0]:
            best = (dist, st)
    return best[1] if best else None


def _mask(hsv, h0, h1, smin, vmin):
    return ((hsv[..., 0] >= h0) & (hsv[..., 0] <= h1)
            & (hsv[..., 1] >= smin) & (hsv[..., 2] >= vmin))


def line_colors(hsv):
    """바닥 띠(1~4 m)의 주차선 색 픽셀 수."""
    band = hsv[ground_row(4.0):ground_row(1.0)]
    out = {}
    for name, (h0, h1, smin, vmin) in LINE_MASKS.items():
        if name == "NORMAL":       # 흰색: 저채도 + 고명도
            m = (band[..., 1] <= WHITE_S_MAX) & (band[..., 2] >= vmin)
        else:
            m = _mask(band, h0, h1, smin, vmin)
        out[name] = int(m.sum())
    return out


def is_fire_truck(hsv):
    """빨간 대형 차체 — 바닥 위 영역에서 빨강 픽셀이 충분한가."""
    body = hsv[200:ground_row(2.0)]
    red = (((body[..., 0] <= 8) | (body[..., 0] >= 172))
           & (body[..., 1] >= RED_S_MIN) & (body[..., 2] >= 60))
    return int(red.sum())


def has_blue_plate(hsv):
    """번호판이 놓일 수 있는 행 띠의 파란 번호판 — 전기차 규격.

    🚨 예전엔 rows 260:500 고정이라 아래 180 행이 4~6 m 앞 **바닥**이었다
    (ground_row: 4 m→504, 6 m→488). 먼 바닥의 파란 주차선·장애인 표지가
    번호판으로 세어져 EV 구역 세단이 정상 처리된 적이 있다 (실측 7823 px,
    같은 차가 다른 자세에선 0 px — 임계값으로는 못 막는 비결정 결함).
    판 높이로 띠를 좁히면 바닥은 아무리 멀어도 지평선(row 457) 아래라
    **원천 배제**된다 — 지금 띠는 206:406.
    """
    h0, h1, smin, vmin = PLATE_BLUE
    r0 = row_at(PLATE_Z + PLATE_H_M / 2, PLATE_D_MIN)
    r1 = row_at(PLATE_Z - PLATE_H_M / 2, PLATE_D_MAX)
    box = hsv[r0:r1, 400:880]
    return int(_mask(box, h0, h1, smin, vmin).sum())


def car_width_m(hsv, dist=2.0):
    """차폭 추정(m) — 차량 하부의 어두운 실루엣(바퀴·하부 그림자) 폭.

    차체 색이 은색·흰색이면 배경(하늘·바닥)과 HSV 로 안 갈라져서, 색과
    무관하게 어두운 **하부**의 좌우 끝으로 폭을 잰다. 관측점이 번호판에서
    2 m 로 고정이라 픽셀→미터 환산이 성립한다.

    ⚠ 그림자가 실루엣에 섞여 과대 측정된다 (실측 2.76 m, 실제 1.8) —
       depth 프레임이 있으면 car_width_depth 가 우선이다.
    """
    band = hsv[ground_row(3.0):ground_row(1.2)]
    dark = (band[..., 2] <= DARK_V_MAX)
    cols = np.where(dark.sum(axis=0) >= DARK_COL_MIN)[0]
    if len(cols) < 10:
        return None
    return float((cols[-1] - cols[0]) * dist / F_PX)


def car_width_depth(depth):
    """차폭 추정(m) — depth(distance_to_image_plane, 32FC1)로.

    차체 높이 대역(rows 300~500)에서 근거리(0.5~4 m) 픽셀만 차다 —
    그림자는 바닥이라 그 행에서는 4 m 너머(제외), 하늘·먼 벽도 제외.
    이미지 중앙에서 이어진 열 성분만 취해 프레임 가장자리에 걸린 이웃
    차를 배제하고, 성분의 중앙값 거리로 픽셀→미터 환산한다.
    """
    band = depth[300:500, :]
    near = np.isfinite(band) & (band > 0.5) & (band < 4.0)
    cols = near.mean(axis=0) > 0.3
    if not cols.any():
        return None
    c = len(cols) // 2
    if not cols[c]:                      # 중앙이 비면 가장 가까운 성분으로
        idx = np.where(cols)[0]
        c = idx[np.argmin(np.abs(idx - c))]
    lo = c
    while lo > 0 and cols[lo - 1]:
        lo -= 1
    hi = c
    while hi < len(cols) - 1 and cols[hi + 1]:
        hi += 1
    seg = band[:, lo:hi + 1]
    d = float(np.median(seg[near[:, lo:hi + 1]]))
    return float((hi - lo + 1) * d / F_PX)


def classify(frame_bgr, wx, wy, yaw_deg, depth=None):
    """관측 지점에서의 최종 판단.

    Args:
        depth: OcrCam depth 프레임 (32FC1, 미터). 있으면 경차 차폭을
            그림자 없이 정확히 잰다 (car_width_depth).

    Returns:
        dict(zone_type, vehicle_type(None=OCR 단계로 보류), stall_id,
             measurements=진단용 실측값)
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    st = stall_ahead(wx, wy, yaw_deg)
    colors = line_colors(hsv)
    meas = dict(line_px=colors)

    if st is None:
        return dict(zone_type="Not", vehicle_type="ILLEGAL",
                    stall_id=None, measurements=meas)

    zone = st["zone"]
    # 색 교차 검증 — 좌표가 우선이고, 어긋나면 로그용으로만 남긴다.
    color_zone = None
    strong = {k: v for k, v in colors.items() if v >= LINE_MIN_PX}
    if strong:
        color_zone = max(strong, key=strong.get)
        if color_zone == "BLUE":
            color_zone = zone if zone in ("COMPACT", "DISABLED") else "COMPACT"
    meas["color_zone"] = color_zone

    if zone == "NORMAL":
        vehicle = "NORMAL"                       # 정상 구역 → 스킵
    elif zone == "FIRE":
        meas["red_px"] = is_fire_truck(hsv)
        vehicle = "NORMAL" if meas["red_px"] >= RED_PX_MIN else "ILLEGAL"
    elif zone == "COMPACT":
        w = car_width_depth(depth) if depth is not None else None
        meas["width_by"] = "depth" if w is not None else "dark"
        if w is None:
            w = car_width_m(hsv)
        meas["car_width_m"] = w
        vehicle = ("NORMAL" if w is not None and w <= COMPACT_MAX_W
                   else "ILLEGAL")
    elif zone == "EV":
        meas["plate_blue_px"] = has_blue_plate(hsv)
        vehicle = "NORMAL" if meas["plate_blue_px"] >= PLATE_PX_MIN else "ILLEGAL"
    else:                                        # DISABLED — DB 조회 필요
        vehicle = None
    return dict(zone_type=zone, vehicle_type=vehicle,
                stall_id=st["id"], measurements=meas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="프레임 한 장으로 판별 테스트")
    ap.add_argument("--frame", required=True, help="OcrCam 캡처 (jpg/png)")
    ap.add_argument("--pose", required=True, metavar="X,Y,YAW", help="월드 좌표")
    a = ap.parse_args()
    x, y, yaw = (float(v) for v in a.pose.split(","))
    img = cv2.imread(a.frame)
    assert img is not None, a.frame
    r = classify(img, x, y, yaw)
    print(r)
