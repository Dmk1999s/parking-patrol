"""바닥 표시 텍스처 — 지금은 장애인 구역 휠체어 표시 하나뿐이다.

## 왜 도형이 아니라 텍스처인가

휠체어 표시는 AMR1 이 **구역을 판별하는 단서**다. 지도에서 경차 구역과 장애인
구역이 **둘 다 파란 선**이라, 색만으로는 갈리지 않고 이 표시로만 구분된다
(`layout.py` 머리말 참고). 그래서 카메라에 또렷하게 잡히는 그림이어야 하고,
바닥에 붙는 납작한 그림은 텍스처가 도형보다 훨씬 싸고 선명하다.
"""

import os

TEX = 512


def wheelchair(out_path):
    """파란 바탕에 흰 휠체어 표시 PNG. 이미 있으면 다시 만들지 않는다."""
    if os.path.isfile(out_path):
        return out_path
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img = Image.new("RGB", (TEX, TEX), (38, 115, 242))
    d = ImageDraw.Draw(img)
    w = (255, 255, 255)

    # 실제 픽토그램을 그대로 옮기지 않는다. 위에서 내려다볼 때 "휠체어구나" 로
    # 읽히면 충분하다 — 바퀴 큰 원 + 사람 머리·몸통·발판.
    d.ellipse([150, 175, 400, 425], outline=w, width=22)      # 바퀴
    d.ellipse([196, 66, 266, 136], fill=w)                     # 머리
    d.line([238, 145, 238, 290], fill=w, width=30)             # 몸통
    d.line([238, 185, 340, 225], fill=w, width=26)             # 팔
    d.line([238, 290, 330, 300], fill=w, width=26)             # 허벅지
    d.line([330, 300, 350, 380], fill=w, width=24)             # 종아리
    d.line([330, 385, 395, 385], fill=w, width=24)             # 발판

    img.save(out_path)
    return out_path


def path_for_wheelchair():
    base = os.environ.get("PATROL_SCRATCH", "/tmp")
    return wheelchair(os.path.join(base, "markings", "wheelchair.png"))
