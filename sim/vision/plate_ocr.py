"""[ROS 3.10] 번호판 로컬라이즈 + OCR — AMR1 이 현장에서 번호판을 읽는다.

    python3 sim/vision/plate_ocr.py --frame capture.jpg     # 오프라인 테스트

관측 지점(번호판 앞 2 m, OcrCam 정면)에서 찍은 프레임을 받아 번호판을
찾고 tesseract(kor)로 읽어 `12가3456` 형식만 통과시킨다.

## 후보를 세 가지 방법으로 찾는 이유 (전부 실측으로 필요해졌다)

판의 겉모습이 차체 색·조명에 따라 완전히 달라진다:
1. **파란 판** (전기차) — H 103~128 의 파란 사각형. 🚨 EV 차체 청록
   (H≈95)과 겹치지 않게 대역을 조이고, 안에 흰 글자가 있어야 판으로 본다.
2. **밝은 사각형** — 어두운 차체 위 흰 판: 판이 주변보다 확 밝다.
3. **글자 라인** — 밝은 차체 위 흰 판은 판/차체가 밝기로 안 갈린다
   (그늘에서 판 V≈138 vs 차체 130 실측). 대신 어두운 글자들을 가로로
   뭉쳐 "주변이 확 밝은 글자 띠"를 찾는다.

## OCR 은 변형을 여러 개 시도한다

그늘진 판은 Otsu 이진화가 획을 뭉개 `하`→`31` 같은 오독이 났다 (실측).
[Otsu / 적응형 / 2배 확대+Otsu] × [kor / kor+eng] 를 차례로 돌려 처음
패턴에 맞는 결과를 쓴다. 🚨 무턱대고 확대만 하면 오히려 나빠진다
(README — 3배 확대에서 `나` 를 놓쳤다). 변형 중 하나로만 시도한다.

도착 yaw 오차(±14°)만큼 판이 중앙에서 벗어나므로 ROI 를 넓게 잡고,
실패하면 호출부(amr1_nav)가 다음 프레임으로 재시도한다.
"""

import argparse
import os
import re
import subprocess
import tempfile

import cv2
import numpy as np

# 도착 오차(yaw ±14° ≈ 230 px, 위치 ±0.25 m ≈ 116 px)에 판 반폭 150 px 를
# 더하면 판이 중앙에서 ~500 px 까지 벗어난다 — 반폭 420 이던 ROI 에서
# 잘려 로컬라이즈가 실패했다 (실측). 거의 전폭으로 잡는다.
ROI = (160, 580, 60, 1220)           # v0, v1, u0, u1
PLATE_RE = re.compile(r"(\d{2})\s*([가-힣])\s*(\d{4})")


def _candidates(img):
    """번호판 후보 bbox 목록 [(score, x0, y0, x1, y1)] — 원본 좌표계."""
    v0, v1, u0, u1 = ROI
    roi = img[v0:v1, u0:u1]
    # 🚨 색 마스크는 **크로마만 블러**한 이미지에서 딴다. 원시 렌더는 색
    #    노이즈로 파란 판 마스크가 조각나 후보를 놓쳤는데, 같은 프레임을
    #    JPEG 로 거치면 성공했다 (실측: 원시 0 / JPEG 왕복 2 후보 — JPEG 의
    #    크로마 평활 효과). 루마(Y)는 그대로 둬야 어두운 글자 검출(마스크
    #    3번)이 안 뭉개진다 — BGR 전체 블러는 회귀를 냈다.
    ycc = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    ycc[..., 1] = cv2.GaussianBlur(ycc[..., 1], (5, 5), 0)
    ycc[..., 2] = cv2.GaussianBlur(ycc[..., 2], (5, 5), 0)
    hsv = cv2.cvtColor(cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR),
                       cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    out = []

    def add(x, y, w, h, pad, score):
        out.append((score,
                    max(0, u0 + x - pad), max(0, v0 + y - pad),
                    u0 + x + w + pad, v0 + y + h + pad))

    # 1) 파란 판 — 흰 글자(밝고 저채도)가 5% 이상 들어 있어야 한다
    # 🚨 라이브 원시 렌더는 노출·노이즈로 판의 채도가 들쭉해 마스크가
    #    조각난다 (JPEG 저장분은 압축 평활로 붙어서 오프라인만 성공하던
    #    미스터리의 정체). S 문턱을 낮추고 CLOSE 를 키워 조각을 붙인다.
    blue = (((H >= 103) & (H <= 128) & (S > 90) & (V > 60))
            .astype(np.uint8)) * 255
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    white = (S < 70) & (V > 160)
    for c in cv2.findContours(blue, cv2.RETR_EXTERNAL,
                              cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if not (140 <= w <= 560 and h > 0 and 2.2 <= w / h <= 7.5
                and w * h >= 9000):
            continue
        if white[y:y + h, x:x + w].mean() < 0.05:
            continue
        add(x, y, w, h, 6, w * h + 2_000_000)      # 파란 판 최우선

    # 2) 밝은 사각형 — 주변(어두운 차체)보다 확 밝은 판
    bright = ((S < 70) & (V > 140)).astype(np.uint8) * 255
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for c in cv2.findContours(bright, cv2.RETR_EXTERNAL,
                              cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if not (140 <= w <= 560 and 30 <= h <= 110 and 2.2 <= w / h <= 7.5):
            continue
        pad = 12
        yy0, yy1 = max(0, y - pad), min(V.shape[0], y + h + pad)
        if y <= yy0 or y + h >= yy1:
            continue
        xx0, xx1 = max(0, x - pad), min(V.shape[1], x + w + pad)
        ring = np.concatenate([V[yy0:y, xx0:xx1].ravel(),
                               V[y + h:yy1, xx0:xx1].ravel()])
        if ring.mean() > np.percentile(V[y:y + h, x:x + w], 60) - 40:
            continue                                # 주변이 충분히 어둡지 않다
        add(x, y, w, h, 6, w * h + 1_000_000)

    # 3) 글자 라인 — 어두운 글자 띠, 주변(판 바탕)이 확 밝아야
    dark = (V < 80).astype(np.uint8) * 255
    band = cv2.dilate(dark, np.ones((5, 25), np.uint8))
    for c in cv2.findContours(band, cv2.RETR_EXTERNAL,
                              cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if not (120 <= w <= 460 and 25 <= h <= 95 and 2.0 <= w / h <= 9.0):
            continue
        pad = 12
        yy0, yy1 = max(0, y - pad), min(V.shape[0], y + h + pad)
        if y <= yy0 or y + h >= yy1:
            continue
        xx0, xx1 = max(0, x - pad), min(V.shape[1], x + w + pad)
        ring = np.concatenate([V[yy0:y, xx0:xx1].ravel(),
                               V[y + h:yy1, xx0:xx1].ravel()])
        # 렌더 노출이 프레임마다 흔들려(같은 자세에서 글자 어두운 비율
        # 35%→16% 실측) 백분위를 p15 로 잡으면 밝은 프레임에서 판을
        # 놓친다 — 글자의 **가장 어두운 부분**(p5)과 비교한다.
        if ring.mean() < np.percentile(V[y:y + h, x:x + w], 5) + 60:
            continue
        add(x, y, w, h, 8, w * h)

    out.sort(reverse=True)
    return out[:5]


def _tesseract(gray_img, lang):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        cv2.imwrite(tmp, gray_img)
        return subprocess.run(
            ["tesseract", tmp, "stdout", "-l", lang, "--psm", "7"],
            capture_output=True, text=True, timeout=20).stdout
    finally:
        os.unlink(tmp)


def read_plate(crop_bgr):
    """크롭 하나를 여러 변형으로 읽어 `12가3456` 을 돌려준다. 실패 시 None."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)

    def otsu(g):
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return 255 - b if b.mean() < 127 else b

    def adaptive(g):
        b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY, 31, 10)
        return 255 - b if b.mean() < 127 else b

    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    variants = [otsu(gray), adaptive(gray), otsu(up)]
    # 변형별 결과가 갈릴 수 있어 (끝자리 2↔7 오독 실측) 다수결로 정한다.
    # 🚨 표는 **이진화 변형당 1표** — 같은 변형에 언어만 바꾸면 같은
    #    오독이 2표가 되어 조기 확정되는 함정이 있었다 (실측). 언어는
    #    kor+eng 우선, 한글을 못 읽으면 kor 로 보충만 한다.
    votes = {}
    for v in variants:
        text = None
        for lang in ("kor+eng", "kor"):
            m = PLATE_RE.search(_tesseract(v, lang).replace(" ", ""))
            if m:
                text = "".join(m.groups())
                break
        if text is None:
            continue
        votes[text] = votes.get(text, 0) + 1
        if votes[text] >= 2:
            return text
    return max(votes, key=votes.get) if votes else None


def ocr_frame(frame_bgr):
    """프레임 한 장 → (번호판 텍스트, 크롭). 못 읽으면 (None, None)."""
    for _, x0, y0, x1, y1 in _candidates(frame_bgr):
        crop = frame_bgr[y0:y1, x0:x1]
        text = read_plate(crop)
        if text:
            return text, crop
    return None, None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="프레임 한 장 OCR 테스트")
    ap.add_argument("--frame", required=True)
    a = ap.parse_args()
    img = cv2.imread(a.frame)
    assert img is not None, a.frame
    text, crop = ocr_frame(img)
    print(f"번호판: {text}  (크롭: {None if crop is None else crop.shape})")
