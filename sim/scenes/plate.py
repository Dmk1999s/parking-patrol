"""번호판 텍스처를 만든다 — OCR 이 실제로 읽을 수 있는 그림이어야 한다.

씬의 차량은 단색 상자라 번호판이 없다. AMR1 이 OCR 로 번호를 읽는 단계
(`CLAUDE.md` 2단계)를 시뮬로 돌리려면, 번호판이 **글자가 그려진 텍스처**로
존재해야 한다. 이 파일이 그 PNG 를 만든다.

## 왜 파일로 안 만들고 코드로 굽는가

차량마다 번호가 달라야 하고, 그 번호가 Django `vehicle_info.plate_number` 와
같아야 한다. 이미지를 미리 만들어 두면 둘이 갈라진다 — 번호를 바꿀 때마다
포토샵을 열어야 한다. 여기서는 문자열 하나만 주면 텍스처가 나오므로,
**DB 에 넣을 값과 씬에 그리는 값이 같은 변수**가 된다.

## 한국 번호판 규격 (2019~ 페인트식 등록번호판, 승용차)

    바탕 520 × 110 mm, 흰 바탕에 검은 글자
    형식  123가4567  (앞 세 자리 + 한글 한 자 + 뒤 네 자리)

⚠ 아직 실물과 다른 것: **좌측 청색 띠(태극+KOR)** 가 없다. 넣기 전에
  `zone_classify.BLUE_RUN_MIN` 주석을 읽을 것 — EV 판별이 걸려 있다.

글자 높이는 약 80 mm 다. 이 값이 OCR 가능 거리를 결정한다
(`lot.approach_pose` 주석의 픽셀 계산 참고).

## 🚨 재질을 금속·유리로 하면 안 된다

실제 번호판은 재귀반사라 정면에서 밝게 보이지만, 시뮬에서 metallic/specular
를 올리면 **하이라이트가 글자를 덮어** OCR 이 통째로 실패한다. 확산 반사
위주(roughness 0.6~0.8, metallic 0)로 둘 것. `lot.py` 가 그렇게 바인딩한다.
"""

import os

import plate_glyphs

# 실제 번호판 비율 520:110 ≈ 4.73:1. 텍스처는 그 비율을 유지한다.
PLATE_W_M = 0.520
PLATE_H_M = 0.110

# 텍스처 해상도. 1024×217 이면 글자 높이가 약 158 px 라, 2 m 에서 화면에
# 37 px 로 찍혀도 원본이 뭉개지지 않는다. 더 키워도 OCR 결과는 안 변한다.
TEX_W = 1024
TEX_H = 217

# ── 고시 별표 2-2 규격 (비사업용 8자리 필름부착방식, 520×110 mm) ──
# 「자동차 등록번호판 등의 기준에 관한 고시」의 도면에서 그대로 옮긴 값이다.
# 좌→우 폭 배분이 정확히 520 이 된다:
#
#     띠 65.0 │ 숫자 50.0 ×3 │ 한글 85.0 │ 숫자 50.0 ×4 │ 우여백 20.0
#
# 🚨 한글 뒤에 **공백이 따로 있는 게 아니다.** 한글 셀이 85 mm 로 넓고 글자
#    자체는 47 mm 남짓이라 좌우에 여백이 남는 것뿐이다. 보도자료 사진만 보고
#    "공백 6.1%" 로 오해해 그렇게 구현했다가 고시 도면으로 바로잡았다.
# 🚨 문자 **셀** 높이는 85.0 이지만 **잉크** 높이는 74.8 이다 (숫자 '2' 도면).
#    셀 높이를 글자 높이로 읽으면 14% 크게 그린다.
PLATE_W_MM, PLATE_H_MM = 520.0, 110.0
STRIP_MM, RIGHT_MM = 65.0, 20.0
CELL_MM = (50.0, 50.0, 50.0, 85.0, 50.0, 50.0, 50.0, 50.0)
INK_H_MM = 74.8

# 이 값이 OCR 가능 거리를 결정한다 — `lot.approach_pose` 의 거리표와 짝이다.
INK_H_PX = round(TEX_H * INK_H_MM / PLATE_H_MM)      # 148 px

# 한글이 있는 폰트. 없으면 숫자만 나오고 한글은 두부(□)가 된다.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
]


def font_path():
    for p in _FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


# 🔑 전기차는 겉모습으로 구분할 수 없다. 실제 한국 규격이 전기차 번호판을
#    색으로 구분하므로 시뮬도 그대로 따른다 — AMR 이 번호판 색만 보고
#    전기차 여부를 판별할 수 있다(별도 DB 조회가 필요 없다).
#
# 🚨 EV 색은 [별표 18] 색상표 그대로다: 바탕 **PANTONE 290C = 연한 하늘색**,
#    글자는 "[별표 2]와 같음" = **검정**. 예전엔 진한 남색 + 흰 글자로 그렸는데
#    실물과 정반대였다. 하늘색은 채도가 낮아서(HSV S 약 54) `zone_classify`
#    의 `PLATE_BLUE` 채도 문턱을 같이 내려야 한다 — 거기 주석을 읽을 것.
COLORS = {
    #        바탕                글자              테두리
    False: ((250, 250, 248), (15, 15, 15), (20, 20, 20)),      # 일반
    True:  ((185, 217, 235), (15, 15, 15), (20, 20, 20)),      # 전기차 290C
}

# 좌측 국가상징 띠 — 태극 Ø36.5, KOR 원 Ø22.6 (고시 도면).
# 🚨 이 띠가 EV 파란 판 마스크에 걸린다 — `zone_classify.BLUE_RUN_MIN` 을
#    먼저 읽을 것. 띠 폭을 키우면 그 판별의 여유가 줄어든다.
STRIP_RGB = (40, 70, 140)
TAEGUK_MM, KOR_MM = 36.5, 22.6


def render(text, out_path, ev=False):
    """번호판 PNG 를 만든다. 이미 있으면 다시 만들지 않는다.

    Args:
        text: `123가4567` 같은 번호판 문자열
        out_path: 저장할 PNG 경로
        ev: True 면 전기차 번호판(파란 바탕 흰 글자)

    Returns:
        만들어진 경로. Pillow 나 폰트가 없으면 None.
    """
    if os.path.isfile(out_path):
        return out_path

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[plate] Pillow 가 없다 — 번호판 없이 간다")
        return None

    fp = font_path()
    if fp is None:
        print("[plate] 한글 폰트를 못 찾았다 — 한글이 □ 로 나온다.\n"
              "        sudo apt-get install -y fonts-nanum")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    bg, fg, edge = COLORS[bool(ev)]
    img = Image.new("RGB", (TEX_W, TEX_H), bg)
    d = ImageDraw.Draw(img)

    # 테두리 — 실제 번호판의 외곽선. OCR 이 판을 찾는 단서가 된다.
    d.rectangle([6, 6, TEX_W - 7, TEX_H - 7], outline=edge, width=5)

    _strip(d, bool(ev))
    _cells(img, d, text, fg)
    img.save(out_path)
    return out_path


def _mm(v):
    """mm → 텍스처 px."""
    return v * TEX_W / PLATE_W_MM


def _fit(d, ch, target):
    """글자 하나의 **잉크 높이**가 target px 이 되는 폰트와 bbox.

    폰트 크기 인자는 em 이라 잉크 높이보다 크고 그 비율은 폰트마다 다르다 —
    재서 비례로 되맞춘다. 래스터화 반올림 때문에 한 번으로는 1 px 모자라고
    두 번이면 고정점이다. 글자마다 따로 맞추는 건 고시가 모든 문자를 같은
    잉크 높이(74.8)로 그리기 때문이다 — 폰트의 자연 높이차를 지운다.
    """
    from PIL import ImageFont

    fp = font_path()
    size = target
    font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
    b = d.textbbox((0, 0), ch, font=font)
    for _ in range(2):
        h = b[3] - b[1]
        if not fp or h in (0, target):
            break
        size = max(1, round(size * target / h))
        font = ImageFont.truetype(fp, size)
        b = d.textbbox((0, 0), ch, font=font)
    return font, b


def _strip(d, ev):
    """좌측 국가상징 영역 (태극 + KOR).

    🚨 EV 는 **띠가 없다.** [별표 18] 의 전기차 판은 판 전체가 연한 하늘색
    바탕이고 그 위에 상징만 얹힌다 — 진한 청색 띠는 일반 판(별표 2-2)의 것이다.
    🚨 홀로그램(중앙)은 일부러 안 그린다 — 보도자료가 "정면에서는 잘 보이지
    않고 비스듬한 각도에서 식별 가능"이라고 못박았고, AMR 관측은 정면이다.
    태극도 두 색 반원으로 간략화했다 (2 m 에서 25 px 라 곡선이 안 보인다).
    """
    x1 = _mm(STRIP_MM)
    if not ev:
        d.rectangle([9, 9, x1, TEX_H - 10], fill=STRIP_RGB)
    mark = (235, 235, 240) if not ev else (40, 90, 150)

    cx = (9 + x1) / 2
    r = _mm(TAEGUK_MM) / 2                            # 태극 (상단)
    cy = TEX_H * 0.30
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=(200, 45, 55))
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 0, 180, fill=(25, 70, 165))

    r = _mm(KOR_MM) / 2                               # KOR 원 (하단)
    cy = TEX_H * 0.72
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mark, width=3)
    font, b = _fit(d, "KOR", int(r * 1.1))
    d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]),
           "KOR", font=font, fill=mark)


def _cells(img, d, text, fg):
    """문자를 고시의 셀 배분대로 하나씩 가운데 놓는다.

    글리프는 **고시 별표 도면에서 오려 온 것**을 쓴다 (`plate_glyphs`).
    아틀라스에 없는 글자만 폰트로 떨어진다 — 그 경우 나눔고딕Bold 는 실제
    번호판 서체보다 넓어서(고시 숫자 폭/높이 40.1/74.8 = **0.54**, 나눔은
    0.68) 50 mm 셀을 넘기므로 가로로 눌러 넣는다. 도면 글리프는 규격 폭이라
    누를 일이 없다. 세로는 어느 쪽이든 안 건드린다 — 그게 규격 74.8 mm 다.
    """
    from PIL import Image, ImageDraw

    cells = (CELL_MM if len(text) == len(CELL_MM) else
             ((PLATE_W_MM - STRIP_MM - RIGHT_MM) / len(text),) * len(text))
    x = _mm(STRIP_MM)
    for ch, cw in zip(text, cells):
        cwp = _mm(cw)
        layer = _glyph(d, ch, int(cwp) - 4)
        if layer is not None:
            img.paste(fg, (int(x + (cwp - layer.width) / 2),
                           (TEX_H - layer.height) // 2), layer)
        x += cwp


def _glyph(d, ch, lim):
    """글자 하나의 잉크 마스크 — 높이 INK_H_PX, 폭은 lim 이하."""
    from PIL import Image, ImageDraw

    art = plate_glyphs.load(ch)
    if art is not None:                               # 고시 도면
        w = max(1, round(art.width * INK_H_PX / art.height))
        return art.resize((min(w, lim), INK_H_PX), Image.LANCZOS)

    font, b = _fit(d, ch, INK_H_PX)                   # 폰트 대체
    w, h = b[2] - b[0], b[3] - b[1]
    if w <= 0 or h <= 0:
        return None
    layer = Image.new("L", (w, h), 0)
    ImageDraw.Draw(layer).text((-b[0], -b[1]), ch, font=font, fill=255)
    return layer.resize((lim, h), Image.LANCZOS) if w > lim else layer


def texture_dir():
    """번호판 텍스처를 두는 곳.

    다시 만들 수 있는 산출물이라 로컬 NVMe(`PATROL_SCRATCH`)에 둔다 — EBS 를
    안 먹고, 날아가도 다음 실행 때 다시 구워진다.
    """
    base = os.environ.get("PATROL_SCRATCH", "/tmp")
    return os.path.join(base, "plates")


def path_for(text, ev=False):
    """번호판 문자열에 대응하는 PNG 경로 (없으면 만든다)."""
    # 파일 이름에 한글이 들어가도 상관없지만, 경로 문제를 피하려고 코드포인트로 짓는다.
    safe = "_".join(str(ord(c)) for c in text)
    tag = "ev_" if ev else ""
    return render(text, os.path.join(texture_dir(), f"{tag}{safe}.png"), ev=ev)
