"""주차장 형상 — `layout.py` 가 정한 배치를 USD 로 세운다.

배치(숫자)와 형상(USD)을 갈라 두었다. 배치는 Isaac 없이도 뽑아 볼 수 있고
(`python3 sim/scenes/layout.py`), 그게 곧 시뮬의 정답이다.

🔑 **외부 자산은 TurtleBot3 하나뿐이다.** 나머지 — 바닥·주차선·벽·차량·번호판 —
   는 전부 여기서 `UsdGeom` 기본 도형과 그때그때 구운 텍스처로 만든다. Isaac 의
   기본 소품은 NVIDIA CDN 에서 받아 오는데, 그 경로가 느리거나 막히면 씬이
   자산을 기다리다 멈춘 것처럼 보인다.

## 좌표계

스테이지는 Z-up / 1 unit = 1 m 로 못박는다. Isaac 기본값과 같지만, `.usd` 를
다른 도구에서 열었을 때 Y-up 으로 해석돼 주차장이 옆으로 눕는 일이 있다.
+X 오른쪽, +Y 북 — Django 의 `observation_x/y` 와 같은 축이다.
"""

import os

from pxr import Gf, PhysxSchema, Sdf, UsdGeom, UsdLux, UsdPhysics, UsdShade

import layout
import markings
import plate

# ── 그리기 상수 ─────────────────────────────────────────────────
LINE_W = 0.12            # 주차선 두께
LINE_H = 0.006           # 바닥에서 띄우는 높이 (Z-fighting 방지)
PLATE_Z = 0.42           # 번호판 높이 — 실제 승용차 후면 번호판 위치
WHEEL_R = 0.33

# 차체 아래 사이드실(rocker) — 바닥에서 이 높이까지 차체를 이어 붙인다.
#
# 🚨 **라이다 때문에 필요하다.** TB3 Burger 의 LDS 라이다는 z=0.18 m 에 있는데
#    차체 박스는 z=0.2475 m(=WHEEL_R·0.75) 에서 시작한다. 그리고 RTX 라이다는
#    **콜라이더가 아니라 보이는 형상**에 광선을 쏜다 — 안 보이는 콜라이더 박스를
#    깔아 봐야 라이다에는 안 잡힌다. 그대로 두면 스캔 평면이 차 밑을 지나가
#    **차가 지도에 아예 안 찍히고**(바퀴 4개만 점으로 찍힌다) AMR 이 차 밑으로
#    들어가려 든다. 실제 차도 범퍼·사이드실이 낮게 내려와 있으므로, 바닥 가까이
#    까지 차체를 이어 준다.
ROCKER_Z0 = 0.10         # 사이드실 아래 끝 (지면 간격)

GROUND = layout.GROUND                 # (x0, x1, y0, y1) — 숫자는 layout.py 에

# 오버헤드 웹캠. 주차장 전체(약 32×23 m)가 한 프레임에 들어와야 한다.
# 화각 69° 에서 가로 32 m 를 담으려면 높이 = 16/tan(34.5°) ≈ 23 m.
# 🚨 세로 조리개를 같이 정해야 한다. 기본값은 가로 20.955 / 세로 15.2955 인
#    4:3 비율인데 렌더는 1280×720(16:9) 이라, 안 맞추면 위아래가 잘린다.
#    세로 = 가로 × 9/16 = 11.787.
# 숫자는 layout.py 에 있다 — webcam_detect.py 가 역변환에 같은 값을 쓴다.
WEBCAM = layout.WEBCAM


def _mat(stage, path, rgb, rough=0.6, metal=0.0):
    """UsdPreviewSurface 머티리얼 하나. 경로가 이미 있으면 그걸 쓴다."""
    if stage.GetPrimAtPath(path):
        return UsdShade.Material.Get(stage, path)
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metal)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def _tex_mat(stage, path, tex_file):
    """텍스처를 입힌 머티리얼 (UsdPreviewSurface + UsdUVTexture).

    🚨 metallic·specular 를 올리면 안 된다. 실제 번호판은 재귀반사라 밝게
       보이지만, 시뮬에서 반사를 키우면 **하이라이트가 글자를 덮어** OCR 이
       통째로 실패한다. 확산 반사 위주로 둔다.
    """
    if stage.GetPrimAtPath(path):
        return UsdShade.Material.Get(stage, path)
    mat = UsdShade.Material.Define(stage, path)

    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.7)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)

    # 메시의 `st` primvar 를 읽어 텍스처 좌표로 넘긴다. 이 리더가 없으면
    # 텍스처가 통째로 한 색으로 나온다 (좌표가 없으니 0,0 만 샘플링한다).
    reader = UsdShade.Shader.Define(stage, f"{path}/stReader")
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    tex = UsdShade.Shader.Define(stage, f"{path}/Tex")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(tex_file)
    tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
        reader.ConnectableAPI(), "result")
    tex.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)

    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        tex.ConnectableAPI(), "rgb")
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def _collide(prim_or_geom):
    """이 프림을 **정적 콜라이더**로 만든다 (RigidBodyAPI 를 안 붙인다).

    🔑 정적이라는 게 중요하다. RigidBodyAPI 를 같이 붙이면 주차된 차가 물체가
       되어 AMR 이 밀고 다닌다. 콜라이션만 붙이면 PhysX 가 **움직이지 않는
       벽**으로 취급한다 — 주차장 구조물과 주차된 차는 전부 이쪽이다.

    ⚠ 라이다와는 무관하다. RTX 라이다는 콜라이더가 아니라 **보이는 형상**에
      광선을 쏜다. 물리(충돌)와 센서(가시성)는 여기서 완전히 갈린다.
    """
    prim = prim_or_geom.GetPrim() if hasattr(prim_or_geom, "GetPrim") else prim_or_geom
    UsdPhysics.CollisionAPI.Apply(prim)
    return prim


def _box(stage, path, size, center, mat=None, collide=False):
    """축 정렬 직육면체. `size`·`center` 는 (x, y, z) 미터.

    UsdGeom.Cube 는 한 변 2 인 정육면체라 scale 로 늘린다. xformOp 는
    **translate 를 먼저** 넣어야 중심이 의도한 곳에 온다 (USD 는 리스트 순서대로
    왼쪽부터 적용한다).
    """
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(2.0)
    x = UsdGeom.Xformable(cube)
    x.AddTranslateOp().Set(Gf.Vec3d(*center))
    x.AddScaleOp().Set(Gf.Vec3f(size[0] / 2.0, size[1] / 2.0, size[2] / 2.0))
    cube.CreateExtentAttr([Gf.Vec3f(-1, -1, -1), Gf.Vec3f(1, 1, 1)])
    if mat:
        UsdShade.MaterialBindingAPI(cube).Bind(mat)
    if collide:
        _collide(cube)
    return cube


def _cyl(stage, path, radius, height, center, axis="X", mat=None, collide=False):
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr(radius)
    cyl.CreateHeightAttr(height)
    cyl.CreateAxisAttr(axis)
    UsdGeom.Xformable(cyl).AddTranslateOp().Set(Gf.Vec3d(*center))
    r = max(radius, height / 2.0)
    cyl.CreateExtentAttr([Gf.Vec3f(-r, -r, -r), Gf.Vec3f(r, r, r)])
    if mat:
        UsdShade.MaterialBindingAPI(cyl).Bind(mat)
    if collide:
        _collide(cyl)
    return cyl


def _quad(stage, path, pts, uvs, mat):
    """텍스처를 붙일 사각형 하나.

    🔑 `doubleSided = True` 로 둔다. 면의 앞뒤를 winding 으로 맞추려다 틀리면
       **아무것도 안 보이는데 오류도 안 난다** — 뒤통수만 보이는 셈이라 원인을
       찾기 어렵다.
    """
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(pts)
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateDoubleSidedAttr(True)
    mesh.CreateExtentAttr(UsdGeom.PointBased(mesh).ComputeExtent(pts))
    st = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.varying)
    st.Set(uvs)
    UsdShade.MaterialBindingAPI(mesh).Bind(mat)
    return mesh


def _floor_quad(stage, path, center, size, mat):
    """바닥에 눕힌 텍스처 사각형 (휠체어 표시 등). 위(+Z)에서 본다."""
    cx, cy = center
    w, h = size
    pts = [Gf.Vec3f(cx - w / 2, cy - h / 2, LINE_H),
           Gf.Vec3f(cx + w / 2, cy - h / 2, LINE_H),
           Gf.Vec3f(cx + w / 2, cy + h / 2, LINE_H),
           Gf.Vec3f(cx - w / 2, cy + h / 2, LINE_H)]
    uvs = [Gf.Vec2f(0, 0), Gf.Vec2f(1, 0), Gf.Vec2f(1, 1), Gf.Vec2f(0, 1)]
    return _quad(stage, path, pts, uvs, mat)


def _plate_quad(stage, path, center, size, mat, facing=-1):
    """번호판 사각형. 차 로컬 좌표에서 만든다 (코 = +Y, 뒤 = -Y).

    facing=-1 이면 뒤판(-Y 를 봄), +1 이면 앞판(+Y 를 봄).

    🚨 UV 를 반대로 잡으면 글자가 **거울상**으로 나온다. 오류가 안 나고 판도
       멀쩡히 보여서 렌더를 눈으로 보기 전엔 모른다 (실제로 한 번 뒤집혔다).
       -Y 에서 +Y 를 보는 관측자(뒤판을 보는 쪽)에게는 월드 +X 가 **오른쪽**에
       오므로 이미지 오른쪽(u=1)을 +X 쪽에 붙인다. 앞판을 보는 관측자는 +Y
       에서 -Y 를 보므로 좌우가 뒤집힌다 — x 부호를 반대로 준다.
    """
    cx, cy, cz = center
    w, h = size
    sx = (w / 2) * (-facing)      # 뒤판: +w/2 가 u=1 / 앞판: -w/2 가 u=1
    pts = [Gf.Vec3f(cx + sx, cy, cz - h / 2),   # u=1, v=0
           Gf.Vec3f(cx - sx, cy, cz - h / 2),   # u=0, v=0
           Gf.Vec3f(cx - sx, cy, cz + h / 2),   # u=0, v=1
           Gf.Vec3f(cx + sx, cy, cz + h / 2)]   # u=1, v=1
    uvs = [Gf.Vec2f(1, 0), Gf.Vec2f(0, 0), Gf.Vec2f(0, 1), Gf.Vec2f(1, 1)]
    return _quad(stage, path, pts, uvs, mat)


# ── 차량 ────────────────────────────────────────────────────────
def _car(stage, path, center_xy, yaw, veh, mat_glass, mat_tire):
    """차 한 대. 로컬 좌표에서 **코가 +Y**, 번호판은 뒤(-Y)에 붙는다.

    자리마다 방향이 다르므로 몸통은 로컬에서 만들고 Xform 을 yaw 로 돌린다.
    이렇게 해야 번호판·바퀴 위치를 자리마다 다시 계산하지 않아도 된다.
    """
    spec = layout.VEHICLES[veh["kind"]]
    bw, bl, bh = spec["body"]
    cw, cl, ch = spec["cabin"]

    car = UsdGeom.Xform.Define(stage, path)
    x = UsdGeom.Xformable(car)
    x.AddTranslateOp().Set(Gf.Vec3d(center_xy[0], center_xy[1], 0.0))
    if yaw:
        x.AddRotateZOp().Set(yaw)

    mat_body = _mat(stage, f"{path}/Mat_Body", veh["rgb"], rough=0.35, metal=0.5)
    z0 = WHEEL_R * 0.75                       # 차체 바닥 높이
    _box(stage, f"{path}/Body", (bw, bl, bh), (0, 0, z0 + bh / 2), mat_body,
         collide=True)
    _box(stage, f"{path}/Cabin", (cw, cl, ch),
         (0, -bl * 0.04, z0 + bh + ch / 2), mat_glass, collide=True)

    # 사이드실 — 차체와 바닥 사이를 메운다. 라이다 스캔 평면(z=0.18)이 여기를
    # 지나야 차가 지도에 **면**으로 찍힌다 (파일 머리말 ROCKER_Z0 참고).
    _box(stage, f"{path}/Rocker", (bw * 0.96, bl * 0.98, z0 - ROCKER_Z0),
         (0, 0, (z0 + ROCKER_Z0) / 2), mat_body, collide=True)

    wx, wy = bw / 2 - 0.05, bl * 0.31
    for i, (dx, dy) in enumerate(((-wx, wy), (wx, wy), (-wx, -wy), (wx, -wy))):
        _cyl(stage, f"{path}/Wheel_{i}", WHEEL_R, 0.22,
             (dx, dy, WHEEL_R), axis="X", mat=mat_tire, collide=True)

    tex = plate.path_for(veh["plate"], ev=spec["ev"])
    if tex:
        m = _tex_mat(stage, f"{path}/Mat_Plate", tex)
        # 차체 뒷면에서 1 cm 띄운다. 딱 붙이면 Z-fighting 으로 번호판과 차체가
        # 프레임마다 번갈아 보인다.
        # 한국은 승용차 앞·뒤 번호판이 둘 다 의무다. 앞판이 있어야 앞뒤로
        # 낀 차가 아닌 이상 어느 한쪽에서는 판독할 수 있다 (벽쪽 세로주차).
        _plate_quad(stage, f"{path}/Plate", (0, -bl / 2 - 0.01, PLATE_Z),
                    (plate.PLATE_W_M, plate.PLATE_H_M), m, facing=-1)
        _plate_quad(stage, f"{path}/PlateFront", (0, bl / 2 + 0.01, PLATE_Z),
                    (plate.PLATE_W_M, plate.PLATE_H_M), m, facing=+1)
    return car


# ── 순찰 로봇 = TurtleBot3 Burger ───────────────────────────────
# 실측 치수 (Isaac 번들 자산): 0.138 × 0.178 × 0.191 m, 바퀴 반지름 0.033 m.
# 관절은 wheel_left_joint / wheel_right_joint (RevoluteJoint) 두 개 —
# 차동구동을 그대로 붙일 수 있다.
TB3_REL = "Isaac/Robots/Turtlebot/Turtlebot3/turtlebot3_burger.usd"

TB3_TOP = 0.191
AMR_SPAWN_Z = 0.02       # 스폰 높이 — 바닥과 파고들지 않게 살짝 띄운다

# 차동구동에 넣을 값 (자산 실측 — `sim/README.md` 의 "차동구동" 절 참고)
TB3_WHEEL_RADIUS = 0.033      # 바퀴 반지름
TB3_WHEEL_BASE = 0.160        # 좌우 바퀴 중심 간격
TB3_WHEEL_JOINTS = ("wheel_left_joint", "wheel_right_joint")
# TB3 Burger 정격. Nav2 속도 상한도 여기 맞춘다.
TB3_MAX_LIN = 0.22            # m/s
TB3_MAX_ANG = 2.84            # rad/s

# LDS 라이다가 달린 링크. RTX 라이다 프림을 이 아래에 만든다 — 링크에 붙여야
# 로봇이 움직일 때 스캔 원점이 같이 따라간다.
TB3_SCAN_LINK = "base_scan"

OCR_CAM_Z = 0.20
OCR_CAM_PITCH = 6.0
OCR_CAM_APERTURE = 20.955
OCR_CAM_FOCAL = 15.2     # 화각 69° = 2·atan(20.955 / 2·15.2)


def tb3_url():
    """TurtleBot3 Burger USD 경로. 못 찾으면 None (그러면 대용품을 쓴다).

    🚨 이 자산은 **원격에 있다** — NVIDIA CDN 에서 받아 온다. 네트워크가 막힌
       곳에서 돌릴 일이 있으면 파일을 받아 두고 경로를 직접 준다:

           PATROL_TB3_USD=/path/to/turtlebot3_burger.usd isaac_python ...

       (한 번 받으면 ~/.cache/ov 에 캐시된다 — nvme_cache.sh 가 그 디렉터리를
        로컬 NVMe 로 빼 두었다.)
    """
    if os.environ.get("PATROL_TB3_USD"):
        return os.environ["PATROL_TB3_USD"]
    try:
        from isaacsim.storage.native import get_assets_root_path
        root = get_assets_root_path()
        if root:
            return root.rstrip("/") + "/" + TB3_REL
    except Exception as exc:
        print(f"[lot] 자산 루트를 못 읽었다 ({exc.__class__.__name__}: {exc})")
    return None


def _phys_mat(stage, path, static, dynamic, combine=None):
    """물리 머티리얼 (마찰). 시각 머티리얼과 별개다 — purpose="physics" 로 바인딩한다."""
    if stage.GetPrimAtPath(path):
        return UsdShade.Material.Get(stage, path)
    mat = UsdShade.Material.Define(stage, path)
    pm = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
    pm.CreateStaticFrictionAttr(static)
    pm.CreateDynamicFrictionAttr(dynamic)
    pm.CreateRestitutionAttr(0.0)
    if combine:
        # 마찰 결합 방식. 기본은 average 라 "마찰 0" 머티리얼도 상대가 0.8 이면
        # 0.4 가 되어 버린다 — min 으로 바꿔야 진짜 0 이 된다.
        px = PhysxSchema.PhysxMaterialAPI.Apply(mat.GetPrim())
        px.CreateFrictionCombineModeAttr(combine)
    return mat


def _bind_phys(prim, mat):
    UsdShade.MaterialBindingAPI.Apply(prim.GetPrim() if hasattr(prim, "GetPrim")
                                      else prim).Bind(mat, materialPurpose="physics")


def _fix_tb3_physics(stage, path):
    """TB3 번들 자산의 물리 결함 보정 — **이게 없으면 로봇이 굴러가지 않는다.**

    ## 증상 (실측)

    바퀴는 명령대로 4.55 rad/s 로 도는데 로봇이 1 mm 도 안 나갔다. 오류 없음.
    PhysX 접촉 리포트를 찍어 보니 바닥을 딛는 게 바퀴가 아니었다:

        caster_back box  ↔ Ground   141건      ← 하중이 여기
        base_link box    ↔ Ground   140건      ← 그리고 여기
        wheel cylinders  ↔ Ground   2~3건      ← 바퀴는 스치기만 한다

    ## 원인 — 캐스터 콜라이더가 저작 자세에서 이미 바닥을 뚫는다

    자산 실측 (링크 로컬 z + 콜라이더 오프셋):

        바퀴     중심 0.033, 반지름 0.033  → 바닥에 정확히 접함  ✓
        캐스터   중심 0.006, 반높이 0.010  → **바닥 아래 -0.004 까지 내려감** ✗

    시작하자마자 캐스터가 4 mm 관통 상태라 PhysX 가 뒤를 밀어 올리고, 로봇이
    앞으로 ~4° 기울며 base_link 박스 앞모서리가 닿는다. 하중이 박스와 캐스터에
    실리니 바퀴는 수직항력이 없어 마찰을 못 만든다 — 헛돈다.

    ## 보정

    1. 캐스터 박스를 4 mm 올려 밑면이 정확히 z=0 (바퀴 밑면과 같은 평면).
    2. 캐스터는 마찰 0 (combine=min) — 실물의 볼캐스터처럼 미끄러져야 한다.
       차동구동 로봇에서 캐스터에 마찰이 있으면 회전할 때 끌린다.
    3. 바퀴는 고무 (마찰 1.0) — 추진력은 전부 여기서 나온다.

    🚨 콜라이더들이 instanceable 아래라 그대로는 못 고친다. 해당 스코프만
       인스턴스를 풀고(override) 수정한다 — 자산 파일은 건드리지 않는다.
    """
    caster = stage.GetPrimAtPath(f"{path}/caster_back_link/collisions")
    if not caster:
        print(f"[lot] ⚠ {path}: 캐스터 콜라이더가 없다 — 자산 구조가 바뀌었나? "
              f"물리 보정을 건너뛴다 (로봇이 안 굴러갈 수 있다)")
        return
    caster.SetInstanceable(False)
    box = UsdGeom.Xformable(stage.GetPrimAtPath(f"{path}/caster_back_link/collisions/mesh_0"))
    for op in box.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            t = op.Get()
            op.Set(Gf.Vec3d(t[0], t[1], t[2] + 0.004))
            break

    slick = _phys_mat(stage, "/World/PhysMats/Caster", 0.0, 0.0, combine="min")
    _bind_phys(stage.GetPrimAtPath(f"{path}/caster_back_link/collisions/mesh_0/box"), slick)

    rubber = _phys_mat(stage, "/World/PhysMats/Tire", 1.0, 1.0)
    for side in ("left", "right"):
        col = stage.GetPrimAtPath(f"{path}/wheel_{side}_link/collisions")
        col.SetInstanceable(False)
        _bind_phys(stage.GetPrimAtPath(f"{path}/wheel_{side}_link/collisions/mesh_0/cylinder"),
                   rubber)


def _amr(stage, path, center_xy, lamp_rgb, url=None, yaw=0.0):
    """순찰 AMR 한 대 — TurtleBot3 + 경광등 + 번호판 촬영 카메라.

    ## 경광등을 왜 다는가

    TB3 두 대는 겉모습이 똑같아서 화면에서 AMR1/AMR2 를 구분할 수 없다.
    라이다 위에 색만 다른 작은 원통을 얹어 눈으로 구분한다.
    """
    amr = UsdGeom.Xform.Define(stage, path)
    x = UsdGeom.Xformable(amr)
    # 🔑 2 cm 띄워 놓는다. 자산은 바퀴가 z=0 에 닿게 저작돼 있는데, 딱 0 에
    #    놓으면 첫 스텝에 바닥과 파고들어 PhysX 가 밀어내면서 로봇이 튄다.
    #    떨어뜨리면 물리가 알아서 내려놓는다.
    x.AddTranslateOp().Set(Gf.Vec3d(center_xy[0], center_xy[1], AMR_SPAWN_Z))
    # 🚨 회전 op 를 **항상** 만든다. yaw=0 일 때 건너뛰면 나중에 자세를 고치려는
    #    코드가 op 를 새로 붙이게 되고, translate·rotate 순서가 프림마다 달라져
    #    `--amr1-stall` 같은 자리 이동이 조용히 엉뚱하게 적용된다.
    x.AddRotateZOp().Set(yaw)

    if url:
        # defaultPrim(`/turtlebot3_burger`)만 딸려 온다. 이 자산에는
        # `GroundPlane` 도 들어 있지만 defaultPrim 밖이라 안 따라온다 —
        # 프림 경로를 지정해서 참조하면 바닥이 두 겹이 되니 주의.
        amr.GetPrim().GetReferences().AddReference(url)
        _fix_tb3_physics(stage, path)
    else:
        m = _mat(stage, f"{path}/Mat_Body", (0.85, 0.85, 0.88), rough=0.4)
        _cyl(stage, f"{path}/Base", 0.09, 0.19, (0, 0, 0.095), axis="Z", mat=m)

    # 🚨 경광등·카메라는 로봇 **루트가 아니라 base_link 링크** 밑에 단다.
    #    물리는 아티큘레이션 링크만 움직이고 루트 Xform 은 저작 자세에
    #    남는다 — 루트에 달면 로봇이 굴러가도 장구가 시작 위치에 붙박이가
    #    된다 (실측: 주행 중 OcrCam 이 계속 시작 지점 장면만 찍었고, 프레임에
    #    자기 자신이 지나가는 게 보였다). 라이다를 base_scan 링크에 다는
    #    것과 같은 이유다 (ros_bridge.add_lidar 머리말).
    #    base_link 원점은 지면 위 ~0.01 m — 로컬 z 에서 그만큼 뺀다.
    mount = f"{path}/base_link" if url else path
    z0 = 0.01 if url else 0.0
    _cyl(stage, f"{mount}/Lamp", 0.035, 0.04, (0, 0, TB3_TOP + 0.02 - z0),
         axis="Z", mat=_mat(stage, f"{path}/Mat_Lamp", lamp_rgb, rough=0.2))

    # ── 번호판 촬영 카메라 ──────────────────────────────────────
    # 🔑 TB3 Burger 에는 카메라가 없다 (LDS-01 라이다만. 카메라는 Waffle Pi
    #    쪽인데 Isaac 번들에는 Burger 만 있다). 그래서 직접 단다.
    #
    # 위로 기울이는 이유: 카메라는 z=0.20 인데 승용차 번호판은 z=0.42 다.
    # 2 m 앞에서 보면 올려다보는 각이 atan(0.22/2.0) ≈ 6° 다.
    #
    # 🚨 **카메라는 로봇 진행 방향(로컬 +X)을 본다.** TB3 는 바퀴가 ±Y 에 달려
    #    있어 차동구동으로 **+X 로 전진**한다 (자산 실측: 캐스터가 x=-0.081,
    #    라이다가 x=-0.032 로 둘 다 뒤쪽). ROS 의 yaw 도 +X 축의 방향이다.
    #    물리를 붙이기 전에는 카메라가 로컬 +Y 를 봤는데, 그러면 로봇이 굴러가는
    #    방향과 카메라가 보는 방향이 **90° 어긋난다** — Nav2 로 목표 pose 에
    #    세우면 카메라가 옆을 보게 된다.
    #
    # 🚨 USD 카메라는 자기 좌표계에서 -Z 를 본다. RotateXYZ 는 X→Y→Z 순으로
    #    적용되므로 (90, 0, -90) 이 "-Z 를 +X 로" 돌린다. X 각을 **더 키우면
    #    위를** 본다 (96° = 위로 6°). 84° 로 하면 반대로 바닥을 본다.
    cam = UsdGeom.Camera.Define(stage, f"{mount}/OcrCam")
    cam.CreateHorizontalApertureAttr(OCR_CAM_APERTURE)
    cam.CreateFocalLengthAttr(OCR_CAM_FOCAL)
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.02, 50.0))
    cx = UsdGeom.Xformable(cam)
    cx.AddTranslateOp().Set(Gf.Vec3d(0.06, 0.0, OCR_CAM_Z - z0))
    cx.AddRotateXYZOp().Set(Gf.Vec3f(90.0 + OCR_CAM_PITCH, 0.0, -90.0))


# ── 촬영 위치 ───────────────────────────────────────────────────
def approach_pose(st, dist=2.0):
    """주차면 `st` 의 차량 번호판을 찍으려고 AMR 이 서는 자리 — (x, y, yaw).

    이 값이 곧 Django `parking_events.observation_x / observation_y` 다
    (`CLAUDE.md` 의 "Nav2 안전 접근 보정 좌표").

    ## dist 를 왜 2.0 으로 두는가

    한국 번호판은 520×110 mm, 글자 높이 약 80 mm 다. AMR 카메라(1280×720,
    화각 69°) 기준으로:

        1 m → 글자 74 px  여유     2 m → 37 px  안정적  ← 기본값
        3 m → 25 px  경계          5 m → 15 px  못 읽음

    🚨 `dist` 는 **번호판까지의 거리**다. 주차면 입구까지가 아니다.
       차는 주차면 **한가운데**에 놓이므로(`_car` 가 `st["center"]` 에 세운다)
       번호판은 주차면 중심에서 차 길이의 절반만큼 나와 있다. 주차면 깊이로
       계산하면 안 된다 — 처음에 그렇게 했다가 AMR 이 차에서 0.19 m 앞에 서서
       **차 밑바닥만** 찍었다.
    """
    cx, cy = st["center"]
    veh = st.get("vehicle")
    bl = layout.VEHICLES[veh["kind"]]["body"][1] if veh else 4.3
    back = bl / 2.0 + 0.01          # 차 중심 → 번호판 (0.01 은 판을 띄운 두께)
    # 🚨 yaw 는 **AMR 의 진행 방향(로컬 +X)** 이다 — ROS/Nav2 의 yaw 와 같은
    #    뜻이고, OcrCam 도 그 방향을 본다. "차가 어느 쪽을 보는가" 가 아니라
    #    "AMR 이 어느 쪽을 봐야 하는가" 로 생각해야 한다.
    #    rotateZ(θ) 는 +X 를 (cosθ, sinθ) 로 보낸다:
    #        -X 를 보려면 θ = 180,   +X 를 보려면 θ = 0,   +Y 를 보려면 θ = 90
    #
    #    ⚠ 물리 이전에는 카메라가 로컬 +Y 를 봐서 이 값들이 전부 90° 작았다
    #      (90 / -90 / 0). 카메라를 진행 방향으로 돌린 만큼 여기도 +90 했다.
    #      옛 값을 그대로 쓰면 AMR 이 **통로 건너편** 차를 찍는다 — 번호판이
    #      또렷하게 나와서 오히려 정상처럼 보인다(엉뚱한 차의 번호판이다).
    if st["yaw"] == 90.0:                 # 블록 A — 차 뒤가 +X, AMR 은 -X 를 본다
        return cx + back + dist, cy, 180.0
    if st["yaw"] == -90.0:                # 블록 B — 차 뒤가 -X, AMR 은 +X 를 본다
        return cx - back - dist, cy, 0.0
    return cx, cy - back - dist, 90.0     # 소방차 구역 — 차 뒤가 -Y, AMR 은 +Y


# ── 씬 조립 ─────────────────────────────────────────────────────
def build(stage, plan):
    """`layout.plan()` 결과를 받아 주차장을 세운다. 루트 프림 경로를 돌려준다."""
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    root = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(root.GetPrim())

    # ── 물리 씬 ────────────────────────────────────────────────
    # 🔑 명시적으로 만든다. SimulationContext 가 없으면 대신 만들어 주지만,
    #    `--save` 로 구운 .usd 를 다른 데서 열었을 때도 물리가 살아 있어야 한다.
    # 🚨 중력 방향을 (0,0,-1) 로 못박는다. Z-up 스테이지의 기본값과 같지만,
    #    Y-up 으로 해석되면 로봇이 옆으로 떨어진다.
    scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
    scene.CreateGravityMagnitudeAttr(9.81)
    # CCD 는 끈다. 최고 속도가 0.22 m/s(TB3 정격)라 한 스텝에 통과할 물체가
    # 없고, 켜면 스텝마다 비용만 든다.
    physx = PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim())
    physx.CreateEnableCCDAttr(False)
    physx.CreateTimeStepsPerSecondAttr(60)

    mat_asphalt = _mat(stage, "/World/Looks/Asphalt", (0.17, 0.17, 0.18), rough=0.9)
    mat_glass = _mat(stage, "/World/Looks/Glass", (0.05, 0.07, 0.09), rough=0.1)
    mat_tire = _mat(stage, "/World/Looks/Tire", (0.04, 0.04, 0.04), rough=0.95)
    mat_wall = _mat(stage, "/World/Looks/Wall", (0.22, 0.22, 0.24), rough=0.85)

    # ── 바닥 ───────────────────────────────────────────────────
    # 얇은 상자로 만든다. UsdGeom.Plane 은 뷰어에 따라 한쪽 면만 그려져 위에서
    # 내려다보는 카메라에서 바닥이 통째로 사라져 보이는 일이 있다.
    # 🔑 바닥에도 콜라이션을 준다. 없으면 로봇이 바닥을 **통과해 무한히 떨어진다**
    #    (오류는 안 나고 그냥 사라진다 — 원인을 찾기 어렵다).
    gx0, gx1, gy0, gy1 = GROUND
    ground = _box(stage, "/World/Ground", (gx1 - gx0, gy1 - gy0, 0.1),
                  ((gx0 + gx1) / 2, (gy0 + gy1) / 2, -0.05), mat_asphalt,
                  collide=True)
    # 아스팔트 마찰. 물리 머티리얼이 없으면 PhysX 기본값에 기대게 되는데,
    # 그 값은 버전 따라 바뀔 수 있다 — 주행 특성은 명시해 둔다.
    _bind_phys(ground, _phys_mat(stage, "/World/PhysMats/Asphalt", 0.9, 0.8))

    # ── 벽 2개 ─────────────────────────────────────────────────
    for name, (wx0, wx1) in (("A", layout.WALL_A_X), ("B", layout.WALL_B_X)):
        wy0, wy1 = layout.WALL_Y
        _box(stage, f"/World/Wall_{name}", (wx1 - wx0, wy1 - wy0, layout.WALL_H),
             ((wx0 + wx1) / 2, (wy0 + wy1) / 2, layout.WALL_H / 2), mat_wall,
             collide=True)

    # ── 주차면 ─────────────────────────────────────────────────
    wc_tex = markings.path_for_wheelchair()
    for st in plan["stalls"]:
        zone = st["zone"]
        cx, cy = st["center"]
        w, depth = st["size"]
        grp = f"/World/Stall_{st['id']:02d}_{zone}"
        UsdGeom.Xform.Define(stage, grp)
        mat_line = _mat(stage, f"/World/Looks/Line_{zone}",
                        layout.ZONES[zone]["rgb"], rough=0.5)

        if zone == "FIRE":
            # 소방차 구역은 칸이 아니라 넓은 영역이라 테두리만 굵게 두른다.
            # 🚨 프림 이름에 좌표값을 그대로 쓰면 안 된다. `-4.0` 처럼 점과
            #    빼기가 들어가는데 USD 프림 이름에는 못 쓴다 — "Path must be an
            #    absolute path: <>" 라는, 원인이 안 보이는 오류가 난다.
            for k, (dx, dy, sw, sh) in enumerate((
                    (0, depth / 2, w, LINE_W * 2),
                    (0, -depth / 2, w, LINE_W * 2),
                    (-w / 2, 0, LINE_W * 2, depth),
                    (w / 2, 0, LINE_W * 2, depth))):
                _box(stage, f"{grp}/Edge_{k}", (sw, sh, LINE_H),
                     (cx + dx, cy + dy, LINE_H / 2), mat_line)
        else:
            # 블록 A·B 는 주차면이 가로로 길다 — 폭이 Y, 깊이가 X 다.
            for dy in (-w / 2, w / 2):
                _box(stage, f"{grp}/Line_{'L' if dy < 0 else 'R'}",
                     (depth, LINE_W, LINE_H), (cx, cy + dy, LINE_H / 2), mat_line)
            # 안쪽 끝선 (벽 쪽). 블록에 따라 반대편이다.
            end = -depth / 2 if st["yaw"] == 90.0 else depth / 2
            _box(stage, f"{grp}/Line_End", (LINE_W, w, LINE_H),
                 (cx + end, cy, LINE_H / 2), mat_line)

            # 🔑 경차와 장애인이 **둘 다 파란 선**이다. 휠체어 표시로만 갈린다.
            if zone == "DISABLED" and wc_tex:
                m = _tex_mat(stage, "/World/Looks/Wheelchair", wc_tex)
                _floor_quad(stage, f"{grp}/Wheelchair", (cx, cy),
                            (min(w, depth) * 0.7,) * 2, m)

        if st["vehicle"]:
            _car(stage, f"{grp}/Car", (cx, cy), st["yaw"], st["vehicle"],
                 mat_glass, mat_tire)

    # ── 벽에 붙여 세로 주차한 불법 차량 (고정) ──────────────────
    for f in plan["illegal_fixed"]:
        grp = f"/World/{f['id'].capitalize()}"
        UsdGeom.Xform.Define(stage, grp)
        _car(stage, f"{grp}/Car", f["center"], f["yaw"], f["vehicle"],
             mat_glass, mat_tire)

    # ── 순찰 AMR 2대 ───────────────────────────────────────────
    url = tb3_url()
    print(f"[lot] TurtleBot3 자산: {url or '없음 — 대용품 원통을 쓴다'}")
    (a1, a2) = layout.AMR_START
    _amr(stage, "/World/AMR1", a1, (0.10, 0.40, 0.95), url)
    _amr(stage, "/World/AMR2", a2, (0.10, 0.80, 0.35), url)

    # ── 조명 ───────────────────────────────────────────────────
    # DomeLight 하나로는 그림자가 없어 형상이 납작해 보인다. 방향광을 같이 둔다.
    # 🚨 세게 비추면 주차선 색이 **포화되어 색상(H)이 밀린다** — 주황이 노랑이
    #    된다. AMR 이 색으로 구역을 판별하므로 밝기를 눌러 둔다.
    dome = UsdLux.DomeLight.Define(stage, "/World/Lights/Dome")
    dome.CreateIntensityAttr(450.0)
    dome.CreateColorAttr(Gf.Vec3f(0.75, 0.80, 0.90))

    sun = UsdLux.DistantLight.Define(stage, "/World/Lights/Sun")
    sun.CreateIntensityAttr(1400.0)
    sun.CreateAngleAttr(0.7)
    UsdGeom.Xformable(sun).AddRotateXYZOp().Set(Gf.Vec3f(-55.0, 0.0, 35.0))

    # ── 오버헤드 웹캠 ──────────────────────────────────────────
    # `bridge/bridge_webcam.py` 가 받을 화면이 여기서 나온다.
    # 🔑 회전을 주지 않는다. USD 카메라는 자기 -Z 를 보므로, 안 돌리면 그대로
    #    **수직 아래**를 본다 — 위에서 내려다보는 웹캠이 딱 이 방향이다.
    cam = UsdGeom.Camera.Define(stage, "/World/Webcam1")
    cam.CreateHorizontalApertureAttr(WEBCAM["aperture"])
    cam.CreateVerticalApertureAttr(WEBCAM["v_aperture"])
    cam.CreateFocalLengthAttr(WEBCAM["focal"])
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 200.0))
    UsdGeom.Xformable(cam).AddTranslateOp().Set(Gf.Vec3d(*WEBCAM["pos"]))

    return root.GetPrim().GetPath()
