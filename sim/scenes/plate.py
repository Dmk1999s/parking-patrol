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
    형식  12가3456   (앞 두 자리 + 한글 한 자 + 뒤 네 자리)

글자 높이는 약 80 mm 다. 이 값이 OCR 가능 거리를 결정한다
(`lot.approach_pose` 주석의 픽셀 계산 참고).

## 🚨 재질을 금속·유리로 하면 안 된다

실제 번호판은 재귀반사라 정면에서 밝게 보이지만, 시뮬에서 metallic/specular
를 올리면 **하이라이트가 글자를 덮어** OCR 이 통째로 실패한다. 확산 반사
위주(roughness 0.6~0.8, metallic 0)로 둘 것. `lot.py` 가 그렇게 바인딩한다.
"""

import os

# 실제 번호판 비율 520:110 ≈ 4.73:1. 텍스처는 그 비율을 유지한다.
PLATE_W_M = 0.520
PLATE_H_M = 0.110

# 텍스처 해상도. 1024×217 이면 글자 높이가 약 158 px 라, 2 m 에서 화면에
# 37 px 로 찍혀도 원본이 뭉개지지 않는다. 더 키워도 OCR 결과는 안 변한다.
TEX_W = 1024
TEX_H = 217

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


# 🔑 전기차는 겉모습으로 구분할 수 없다. 실제 한국 규격이 **전기차 번호판을
#    파란 바탕에 흰 글자**로 구분하므로 시뮬도 그대로 따른다 — AMR 이 번호판
#    색만 보고 전기차 여부를 판별할 수 있다(별도 DB 조회가 필요 없다).
COLORS = {
    #        바탕                글자              테두리
    False: ((250, 250, 248), (15, 15, 15), (20, 20, 20)),      # 일반
    True:  ((20, 70, 160), (245, 245, 245), (235, 235, 235)),  # 전기차
}


def render(text, out_path, ev=False):
    """번호판 PNG 를 만든다. 이미 있으면 다시 만들지 않는다.

    Args:
        text: `12가3456` 같은 번호판 문자열
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

    # 글자 높이를 판 높이의 약 73% (80/110) 로 맞춘다.
    size = int(TEX_H * 0.62)
    font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()

    # 가운데 정렬. textbbox 로 실제 잉크 범위를 재서 맞춘다 — 폰트마다
    # 여백이 달라 앵커만으로는 위아래가 안 맞는다.
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((TEX_W - tw) / 2 - box[0], (TEX_H - th) / 2 - box[1]),
           text, font=font, fill=fg)

    img.save(out_path)
    return out_path


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
