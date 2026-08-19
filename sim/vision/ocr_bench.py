"""번호판 OCR 벤치 — 씬을 안 띄우고 텍스처만 구워 OCR 에 먹인다.

    ~/ocr_venv/bin/python sim/vision/ocr_bench.py            # 2 m, 열화 없음
    ~/ocr_venv/bin/python sim/vision/ocr_bench.py --blur 0 0.6 1.2 1.8
    ~/ocr_venv/bin/python sim/vision/ocr_bench.py --ink 127 148   # 글자 높이 비교
    ~/ocr_venv/bin/python sim/vision/ocr_bench.py --font <ttf>    # 폰트 대체 경로

🚨 `~/ocr_venv` 로 돌린다 — `plate_ocr` 가 easyocr 을 쓴다.
   글리프는 기본적으로 **고시 도면 아틀라스**에서 온다 (`scenes/plate_glyphs`).
   `--font` 는 아틀라스에 없는 글자용 대체 경로를 시험할 때만 뜻이 있다.

`OCR_PLATE_FONT.md` 의 원칙 — **씬에 붙이기 전에 OCR 부터 먹인다** — 을 위한
도구다. Isaac Sim 기동 없이 30초면 판가름 난다.

## 🚨 구운 PNG 를 plate_ocr.py --frame 에 그대로 주면 안 된다

무조건 None 이 나온다. `ocr_frame` 은 1280×720 카메라 프레임을 전제로
ROI(160~580, 60~1220)를 자르고 판 폭 140~560 px 만 후보로 본다 — 판이
프레임을 꽉 채우면 전부 걸러진다. 여기서는 실제로 찍힐 크기로 줄여
차체색 배경에 합성한 뒤 먹인다.

## 무엇을 재는가

- **차체 두 종** — 로컬라이저의 서로 다른 경로를 둘 다 태운다. 어두운 차체는
  마스크 2(밝은 사각형), 밝은 차체는 마스크 3(글자 라인)으로 판을 찾는다.
- **블러 σ** — 깨끗한 입력은 웬만하면 다 읽혀서 차이가 안 난다. **무너지는
  지점**을 재야 마진이 보인다 (실측: 글자 64.4 mm 는 σ1.5 에서 붕괴,
  80 mm 는 σ2.4 까지 생존 — 같은 6/6 이라도 여유가 다르다).

## 거리 스윕의 한계

`--dist` 는 3.4 m 까지만 뜻이 있다. 그 너머는 판 폭이 140 px 밑으로 떨어져
**글자 크기와 무관하게** 로컬라이즈가 죽는다 (`plate_ocr._candidates` 의 게이트).
멀리서의 한계를 보고 싶으면 거리 대신 블러를 키우는 쪽이 정직하다.

## 씬 렌더와 다른 점 (여기서 통과해도 씬에서 깨질 수 있다)

합성 프레임에는 조명·그림자·노출 흔들림·원근 왜곡이 없다. 여기는 **서체와
글자 크기만 분리해서 보는 자리**고, 최종 판정은 통짜 리허설이다.
"""

import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scenes"))
import plate  # noqa: E402  (python3 로 그냥 돈다)

from plate_ocr import ocr_frame  # noqa: E402

# OcrCam(1280×720, 화각 69.16°)에서 1 m 거리의 1 m 가 몇 px 인가.
# 거리 d 에서의 판 폭 = PLATE_W_M * PX_PER_M_1M / d.
PX_PER_M_1M = 928.5
FRAME_W, FRAME_H = 1280, 720

BODIES = {"어두운 차체": (60, 60, 60), "밝은 차체": (185, 185, 185)}

# seed 7 이 실제로 굽는 번호 중 6개. 무작위로 뽑으면 실행마다 결과가
# 흔들려 "서체를 바꿔서 깨진 건지"를 못 가린다.
PLATES = [("766라2186", False), ("664조1968", False), ("183무9604", False),
          ("606서8353", False), ("529머9858", True), ("470무5070", True)]


def bake(ink):
    """잉크 높이 ink px 로 표본을 굽고 {번호: 경로} 를 돌려준다.

    `plate.render` 는 파일이 있으면 다시 안 굽는다 — 서체·잉크마다 디렉터리를
    갈라야 이전 실행분을 그대로 읽는 사고가 안 난다.
    """
    plate.INK_H_PX = ink
    stem = os.path.splitext(os.path.basename(plate.font_path() or "none"))[0]
    out = os.path.join(os.environ.get("PATROL_SCRATCH", "/tmp"),
                       "ocr_bench", f"{stem}_{ink}")
    os.makedirs(out, exist_ok=True)
    return {t: plate.render(t, os.path.join(out, f"{t}.png"), ev=ev)
            for t, ev in PLATES}


def compose(png, dist, body, sigma):
    """구운 판을 dist m 에서 찍힐 크기로 줄여 차체색 프레임에 합성한다."""
    w = int(round(plate.PLATE_W_M * PX_PER_M_1M / dist))
    h = int(round(w * plate.TEX_H / plate.TEX_W))
    small = cv2.resize(cv2.imread(png), (w, h), interpolation=cv2.INTER_AREA)
    f = np.full((FRAME_H, FRAME_W, 3), body, np.uint8)
    y, x = (FRAME_H - h) // 2, (FRAME_W - w) // 2
    f[y:y + h, x:x + w] = small
    if sigma > 0:
        f = cv2.GaussianBlur(f, (0, 0), sigma)
    return f, w, h


def main():
    ap = argparse.ArgumentParser(description="번호판 텍스처 OCR 벤치")
    ap.add_argument("--font", help="이 TTF 를 먼저 쓴다 (서체 교체 검증)")
    ap.add_argument("--ink", type=int, nargs="+", default=[plate.INK_H_PX],
                    help="잉크 높이 px (기본 158 = 80 mm)")
    ap.add_argument("--dist", type=float, nargs="+", default=[2.0],
                    help="촬영 거리 m (3.4 m 초과는 무의미 — 위 주석)")
    ap.add_argument("--blur", type=float, nargs="+", default=[0.0],
                    help="가우시안 σ")
    a = ap.parse_args()

    if a.font:
        assert os.path.isfile(a.font), a.font
        plate._FONT_CANDIDATES.insert(0, a.font)
    import plate_glyphs
    print(f"글리프: 고시 도면 {len(plate_glyphs.CHARS)}자"
          f" / 대체 폰트 {plate.font_path()}")

    failed = 0
    for ink in a.ink:
        paths = bake(ink)
        print(f"\n잉크 {ink} px ({ink / plate.TEX_H * 110:.1f} mm)")
        for dist in a.dist:
            _, w, h = compose(paths[PLATES[0][0]], dist, (0, 0, 0), 0)
            print(f"  거리 {dist} m — 판 {w}×{h} px, 글자 {round(ink * h / plate.TEX_H)} px"
                  + ("   🚨 판 폭 140 px 미만: 로컬라이즈 자체가 안 된다"
                     if w < 140 else ""))
            for sigma in a.blur:
                cells = []
                for bname, body in BODIES.items():
                    miss = []
                    for t, _ in PLATES:
                        got, _c = ocr_frame(compose(paths[t], dist, body, sigma)[0])
                        if got != t:
                            miss.append(f"{t}→{got}")
                    failed += len(miss)
                    cells.append(f"{bname} {len(PLATES) - len(miss)}/{len(PLATES)}"
                                 + (f" ({', '.join(miss)})" if miss else ""))
                print(f"    σ={sigma:<4} " + "   ".join(cells))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
