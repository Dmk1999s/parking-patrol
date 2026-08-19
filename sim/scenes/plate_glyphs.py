"""번호판 글리프 아틀라스 — 고시 별표 도면에서 글자를 오려 쓴다.

    python3 sim/scenes/plate_glyphs.py            # 별표 PDF → PNG 아틀라스

## 왜 폰트가 아니라 이미지인가

`plate.py` 가 글자를 **셀 단위로 하나씩** 그리므로(고시 배분) 폰트가 필요
없다. 그리고 별표 도면은 벡터가 아니라 **JPEG 래스터**라, TTF 로 만들려면
어차피 손 벡터화를 거쳐야 한다 — 그 손을 거친 결과물은 원본의 재현본일
뿐이다. 도면을 그대로 오려 쓰면 **재현본이 아니라 원본**이다.

해상도도 남는다: 300 dpi 렌더에서 글리프가 ~440 px 높이로 나오는데
텍스처는 148 px 만 쓴다.

## 어떻게 오리는가 (전부 실측으로 정해진 값)

도면 한 쪽에 글자가 **4개**(2×2)씩 있고, 그 주위를 치수선·치수 글씨·격자
해칭이 둘러싼다. 글자만 남기는 열쇠는 **획 두께**다:

    획 ~55 px  vs  치수선 1~3 px  vs  치수 글씨 4~6 px   (300 dpi 기준)

`MORPH_OPEN(15×15)` 한 번이면 얇은 것이 전부 사라지고 글자는 크기 그대로
남는다. 🚨 연결요소 넓이로 거르면 안 된다 — 치수선이 글자에 **닿아 있어서**
같은 연결요소가 되고, 그러면 bbox 가 페이지 전체로 늘어난다 (실측).

한글은 자모가 떨어져 있어(ㄱ+ㅏ) 조각으로 나온다. 81×81 로 부풀려 묶는다 —
글자 사이 간격은 500 px 넘고 자모 사이는 100 px 안쪽이라 안전하다.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS = os.path.join(HERE, "plate_glyphs")
PDF = os.path.join(HERE, "..", "고시별표", "별표2의2.pdf")

# 쪽마다 4개씩, **위→아래 · 왼→오** 순서. 별표 2-2 를 눈으로 확인한 배열이다.
# 🚨 여기 없는 글자는 **실제 번호판에 없다.** 차·카·타·파·배 와 사업용
#    바·사·아·자 는 별표에 없다 — `layout._HANGUL` 이 그걸 쓰고 있었다.
PAGES = {
    1:  "01",       2:  "2345",     3:  "6789",
    4:  "가나다라",   5:  "마거너더",   6:  "러머고노",
    7:  "도로모구",   8:  "누두루무",   9:  "버서어저",
    10: "보소오조",   11: "부수우주",   12: "허하호",
}
CHARS = "".join(PAGES[k] for k in sorted(PAGES))


def _page_glyphs(png):
    """도면 한 쪽 → 글자 마스크 목록 (위→아래, 왼→오)."""
    import cv2
    import numpy as np

    g = cv2.cvtColor(cv2.imread(png), cv2.COLOR_BGR2GRAY)
    ink = (g < 120).astype(np.uint8)
    core = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
    merged = cv2.dilate(core, np.ones((81, 81), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(merged, 8)

    res = []
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if not (120 <= w <= 700 and 250 <= h <= 700):   # 판 도면·엠블럼 제외
            continue
        m = core[y:y + h, x:x + w] * (lab[y:y + h, x:x + w] == i)
        ys, xs = np.nonzero(m)
        if len(ys) < 5000:
            continue
        res.append(((y // 300, x), m[ys.min():ys.max() + 1,
                                     xs.min():xs.max() + 1] * 255))
    res.sort(key=lambda r: r[0])
    return [m for _, m in res]


def extract(pdf=PDF, out=ATLAS, dpi=300):
    """별표 PDF 에서 글리프를 뽑아 `out/<코드포인트>.png` 로 저장."""
    import glob
    import subprocess
    import tempfile

    import cv2

    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf,
                        os.path.join(tmp, "p")], check=True)
        done = []
        for png in sorted(glob.glob(os.path.join(tmp, "p-*.png"))):
            page = int(os.path.basename(png)[2:-4])
            want = PAGES.get(page)
            if not want:
                continue
            got = _page_glyphs(png)
            if len(got) != len(want):
                print(f"  ⚠ {page}쪽: {len(want)}자 기대, {len(got)}개 추출 — 건너뜀")
                continue
            for ch, m in zip(want, got):
                cv2.imwrite(os.path.join(out, f"{ord(ch)}.png"), 255 - m)
                done.append(ch)
    print(f"{len(done)}자 저장 → {out}\n  {''.join(done)}")
    return done


_CACHE = {}


def load(ch):
    """글자 하나의 잉크 마스크(PIL "L", 255=잉크). 없으면 None."""
    if ch not in _CACHE:
        from PIL import Image, ImageOps
        p = os.path.join(ATLAS, f"{ord(ch)}.png")
        _CACHE[ch] = (ImageOps.invert(Image.open(p).convert("L"))
                      if os.path.isfile(p) else None)
    return _CACHE[ch]


if __name__ == "__main__":
    extract(*(sys.argv[1:3] or []))
