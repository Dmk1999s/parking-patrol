"""주차장 배치와 차량 무작위 배정 — 형상 없이 **숫자만** 다룬다.

`lot.py` 가 이 결과를 받아 USD 로 세운다. 형상과 배치를 갈라 둔 이유는,
배치가 곧 **시뮬의 정답(ground truth)** 이기 때문이다. Isaac 을 띄우지 않고도
배치를 뽑아 보고 DB 에 넣을 값과 대조할 수 있어야 한다:

    python3 sim/scenes/layout.py --seed 7      # Isaac 없이 그냥 돈다

## 좌표계

`observation_x` / `observation_y` (Django `parking_events`) 와 같은 축이다.
+X 오른쪽, +Y 위(북), 단위는 미터.

    x:  0    2.3       4.3 4.7        9.7        15.7       20.7 21.1     28.0
        |AMR |불법차 주차|벽A|블록A      | 통로      |블록B      |벽B |소방차   |
             (벽에 세로) |   |일반3·경차3|          |전기차3·장애인2|

## 구역 규칙 (사용자 확정, 2026-08-14)

    NORMAL   흰색 선    아무 차나
    COMPACT  파란 선    경차만
    DISABLED 파란 선 + 휠체어  장애인 등록 차량만
    EV       초록 선    전기차만
    FIRE     주황       소방차만

🚨 **파란색이 경차와 장애인 양쪽에 쓰인다.** 색만으로는 구분이 안 되고
   휠체어 표시로 갈린다 — AMR1 의 색 판별 로직이 여기서 걸린다.

## 차량 종류를 AMR 이 어떻게 아는가 (사용자 확정)

    경차     차체가 작다 (1.55×3.60 vs 일반 1.80×4.30) — 크기로 판별
    전기차   **번호판이 파란 바탕에 흰 글자** — 실제 한국 규격과 같다
    장애인   번호판을 읽어 `/api/disabled/<번호판>/` 조회
"""

import argparse
import random

# ── 치수 (m) ────────────────────────────────────────────────────
STALL_DEPTH = 5.0          # 주차면 깊이 (차가 들어가는 방향)
AISLE_X0, AISLE_X1 = 9.7, 15.7

WALL_A_X = (4.3, 4.7)      # 불법차선과 블록A 사이 벽
WALL_B_X = (20.7, 21.1)    # 블록B 와 소방차구역 사이 벽
WALL_Y = (0.0, 14.0)
WALL_H = 1.2

BLOCK_A_X = (WALL_A_X[1], WALL_A_X[1] + STALL_DEPTH)   # 4.7 ~ 9.7
BLOCK_B_X = (AISLE_X1, AISLE_X1 + STALL_DEPTH)         # 15.7 ~ 20.7

FIRE_AREA = (21.5, 28.0, 4.0, 12.0)    # x0, x1, y0, y1

# 불법 주차 차량 — 벽 A 왼쪽에 세로(평행) 주차. **고정**이다.
ILLEGAL_X = 3.2
ILLEGAL_Y = (3.0, 7.8, 12.6)           # 간격 4.8 → 차 사이 0.5 m

AMR_START = ((1.2, -3.0), (3.2, -3.0))

# ── 구역 ────────────────────────────────────────────────────────
# w = 주차면 폭(차가 늘어서는 방향). 실제 규격에 맞춘다.
# 🚨 색을 밝게 잡으면 안 된다. 조명이 세면 채널이 포화되면서 **색상(H)이 밀린다**
#    — 처음에 소방차 주황을 (0.98,0.55,0.10) 으로 뒀더니 렌더에서 H=52° 노랑으로
#    나왔다(RGB 238,224,139: 빨강·초록이 같이 최대로 붙어 버렸다). AMR 이 색으로
#    구역을 판별하는데 노랑으로 읽히면 판별이 틀린다.
#    → 어두운 쪽으로 잡아 포화를 피한다. 렌더 실측 H 값은 README 에 적어 두었다.
ZONES = {
    "NORMAL":   dict(rgb=(0.90, 0.90, 0.90), w=2.5),
    "COMPACT":  dict(rgb=(0.10, 0.30, 0.80), w=2.2),
    "DISABLED": dict(rgb=(0.10, 0.30, 0.80), w=3.3),
    "EV":       dict(rgb=(0.04, 0.45, 0.15), w=2.5),
    "FIRE":     dict(rgb=(0.80, 0.28, 0.01), w=8.0),
}

# ── 차량 ────────────────────────────────────────────────────────
#   body   = (폭, 길이, 높이)   cabin = (폭, 길이, 높이)
#   ev     = 파란 번호판을 쓰는가
VEHICLES = {
    "SEDAN":   dict(body=(1.80, 4.30, 0.75), cabin=(1.62, 2.10, 0.55), ev=False),
    "COMPACT": dict(body=(1.55, 3.60, 0.70), cabin=(1.40, 1.70, 0.50), ev=False),
    "EV":      dict(body=(1.80, 4.30, 0.75), cabin=(1.62, 2.10, 0.55), ev=True),
    "FIRE":    dict(body=(2.40, 7.00, 1.30), cabin=(2.20, 2.40, 0.70), ev=False),
}

BODY_RGB = {
    "SEDAN":   [(0.55, 0.55, 0.60), (0.10, 0.15, 0.35), (0.75, 0.75, 0.78),
                (0.12, 0.12, 0.14), (0.45, 0.12, 0.12)],
    "COMPACT": [(0.90, 0.85, 0.30), (0.85, 0.85, 0.88), (0.20, 0.55, 0.35)],
    "EV":      [(0.20, 0.60, 0.75), (0.90, 0.90, 0.92), (0.35, 0.35, 0.40)],
    "FIRE":    [(0.80, 0.08, 0.08)],
}

_HANGUL = "가나다라마바사아자차카타파하배허호"


def is_legal(zone, kind, disabled_registered=False):
    """이 구역에 이 차가 서 있어도 되는가 — 시뮬의 정답.

    AMR1 이 현장에서 내려야 할 판단과 같다. 여기 값과 서버에 올라온
    `vehicle_type` 이 다르면 AMR 로직이 틀린 것이다.
    """
    if zone == "NORMAL":
        return True
    if zone == "COMPACT":
        return kind == "COMPACT"
    if zone == "EV":
        return kind == "EV"
    if zone == "DISABLED":
        return disabled_registered
    if zone == "FIRE":
        return kind == "FIRE"
    return False                     # 'Not' — 주차구역이 아니다


def _plate(rng):
    return (f"{rng.randint(10, 99)}{rng.choice(_HANGUL)}"
            f"{rng.randint(1000, 9999)}")


def _stall_rows():
    """(블록, 구역, 칸수) — 지도의 위→아래 순서."""
    return [
        ("A", "NORMAL", 3),
        ("A", "COMPACT", 3),
        ("B", "EV", 3),
        ("B", "DISABLED", 2),
    ]


def stalls():
    """주차면 목록. 차량 배정 전의 **자리 정보만** 담는다.

    각 항목: id, zone, block, center(x, y), yaw, size(w, depth)

    yaw 는 그 자리에 세울 차의 방향이다. 차는 코가 벽 쪽을 보고 들어가므로
    **번호판(뒤)이 통로를 향한다** — AMR 이 통로에서 읽을 수 있다.
        블록 A: 벽이 왼쪽(-X)  → 뒤가 +X  → yaw =  90
        블록 B: 벽이 오른쪽(+X) → 뒤가 -X  → yaw = -90
    """
    out = []
    top = WALL_Y[1]
    y = {"A": top, "B": top}
    for block, zone, n in _stall_rows():
        w = ZONES[zone]["w"]
        x0, x1 = (BLOCK_A_X if block == "A" else BLOCK_B_X)
        for _ in range(n):
            y[block] -= w
            out.append(dict(
                id=len(out),
                zone=zone,
                block=block,
                center=((x0 + x1) / 2.0, y[block] + w / 2.0),
                yaw=90.0 if block == "A" else -90.0,
                size=(w, STALL_DEPTH),
            ))

    # 소방차 전용 — 칸이 하나뿐이고 방향이 다르다(가로로 길다).
    fx0, fx1, fy0, fy1 = FIRE_AREA
    out.append(dict(
        id=len(out), zone="FIRE", block="F",
        center=((fx0 + fx1) / 2.0, (fy0 + fy1) / 2.0),
        yaw=0.0, size=(fx1 - fx0, fy1 - fy0),
    ))
    return out


def plan(seed=None, occupancy=0.65, illegal_bias=0.45):
    """배치를 뽑는다. 같은 seed 면 같은 배치가 나온다.

    Args:
        seed: 난수 씨앗. None 이면 매번 다르다.
        occupancy: 주차면이 차 있을 확률.
        illegal_bias: 차가 있을 때 **일부러 불법으로** 놓을 확률.
            0 이면 규칙에 맞는 차만 서서 단속할 게 없다 — 시연이 심심해진다.

    Returns:
        dict(seed, stalls=[...], illegal_fixed=[...])
        각 차량 항목에 `legal` 이 들어 있다 — 이게 정답이다.
    """
    rng = random.Random(seed)
    result = []

    for st in stalls():
        st = dict(st)
        st["vehicle"] = None
        if rng.random() < occupancy:
            zone = st["zone"]
            ok_kind = {"NORMAL": None, "COMPACT": "COMPACT",
                       "EV": "EV", "DISABLED": None, "FIRE": "FIRE"}[zone]

            if zone == "DISABLED":
                # 장애인 구역은 차종이 아니라 **등록 여부**로 갈린다.
                kind = rng.choice(["SEDAN", "COMPACT", "EV"])
                registered = rng.random() >= illegal_bias
            else:
                registered = False
                if ok_kind is None:                 # NORMAL — 아무거나 합법
                    kind = rng.choice(["SEDAN", "COMPACT", "EV"])
                elif rng.random() < illegal_bias:   # 일부러 틀린 차를 세운다
                    kind = rng.choice([k for k in ("SEDAN", "COMPACT", "EV")
                                       if k != ok_kind])
                else:
                    kind = ok_kind

            st["vehicle"] = dict(
                kind=kind,
                rgb=rng.choice(BODY_RGB[kind]),
                plate=_plate(rng),
                disabled_registered=registered,
                legal=is_legal(zone, kind, registered),
            )
        result.append(st)

    # 벽에 붙여 세로 주차한 불법 차량 3대 — **고정**이라 seed 와 무관하다.
    # 가운데 차는 앞뒤가 막혀 AMR 이 번호판에 접근하지 못한다.
    fixed = []
    for i, y in enumerate(ILLEGAL_Y):
        fixed.append(dict(
            id=f"illegal_{i}",
            zone="Not",
            center=(ILLEGAL_X, y),
            yaw=0.0,                       # 코가 +Y — 번호판은 -Y 쪽
            vehicle=dict(
                kind="SEDAN",
                rgb=BODY_RGB["SEDAN"][i % len(BODY_RGB["SEDAN"])],
                plate=_plate(rng),
                disabled_registered=False,
                legal=False,               # 주차구역이 아니므로 무조건 불법
            ),
            blocked=(i == 1),              # 가운데만 접근 불가
        ))

    return dict(seed=seed, stalls=result, illegal_fixed=fixed)


def summary(p):
    """배치를 사람이 읽을 수 있게. 시연 전에 정답을 확인할 때 쓴다."""
    lines = [f"배치 (seed={p['seed']})", ""]
    lines.append("  자리  구역        차종      번호판       판정")
    lines.append("  " + "-" * 52)
    for st in p["stalls"]:
        v = st["vehicle"]
        if not v:
            lines.append(f"  {st['id']:>3}  {st['zone']:<10} (빈 칸)")
            continue
        verdict = "정상" if v["legal"] else "불법"
        note = ""
        if st["zone"] == "DISABLED":
            note = " (등록됨)" if v["disabled_registered"] else " (미등록)"
        lines.append(f"  {st['id']:>3}  {st['zone']:<10} {v['kind']:<8} "
                     f"{v['plate']:<11} {verdict}{note}")
    lines.append("")
    lines.append("  벽쪽 불법주차 (고정)")
    for f in p["illegal_fixed"]:
        tag = "  ← 앞뒤가 막혀 번호판 확인 불가" if f["blocked"] else ""
        lines.append(f"  {f['id']:<12} {f['vehicle']['plate']:<11} 불법{tag}")

    n_illegal = sum(1 for s in p["stalls"] if s["vehicle"] and not s["vehicle"]["legal"])
    lines.append("")
    lines.append(f"  단속 대상: 주차면 {n_illegal}대 + 벽쪽 3대 "
                 f"(그중 1대는 확인 불가)")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="배치를 뽑아 본다 (Isaac 불필요)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--occupancy", type=float, default=0.65)
    ap.add_argument("--illegal-bias", type=float, default=0.45)
    a = ap.parse_args()
    print(summary(plan(a.seed, a.occupancy, a.illegal_bias)))
