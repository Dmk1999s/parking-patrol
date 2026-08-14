"""주차장 확인용 씬 — WebRTC 로 화면이 실제로 나가는지 보는 것이 목적이다.

    isaac_ros                                       # rclpy 경로 (지금은 안 쓰지만 습관)
    PYTHONUNBUFFERED=1 isaac_python sim/scenes/parking_lot.py

띄우면 `sim/tools/isaac_autostream/sitecustomize.py` 가 `SimulationApp` 을
가로채 WebRTC 스트리밍을 자동으로 켠다 — 이 파일에는 스트리밍 코드가 한 줄도
없다. 화면은 **Isaac Sim WebRTC Streaming Client**(데스크톱 앱)로 본다.
브라우저로는 안 된다 (`sim/tools/isaac_autostream/livestream.py` 머리말 참고).

## 왜 카메라가 도는가

정지 화면은 **스트리밍이 살아 있는지 죽었는지 구분이 안 된다.** WebRTC 는
붙어 있는데 렌더가 멈춰도 마지막 프레임이 그대로 남아 정상처럼 보인다. 그래서
뷰 카메라를 천천히 공전시킨다 — 화면이 움직이면 렌더·인코딩·전송이 전부
살아 있다는 뜻이다.

## 옵션

    --no-orbit      공전을 끈다 (성능 측정 등)
    --steps N       N 프레임 뒤 종료. 기본은 무한 (클라이언트에서 계속 본다)
    --save PATH     .usd 로 굽고 끝낸다. 스트리밍 없이 쓸 것:
                      ISAAC_STREAM=0 isaac_python ... --save out.usd
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
import pyver  # noqa: E402

pyver.require_isaac("sim/scenes/parking_lot.py")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--steps", type=int, default=0,
                   help="N 프레임 뒤 종료. 0 이면 무한 (기본)")
    p.add_argument("--no-orbit", action="store_true", help="뷰 카메라 공전을 끈다")
    p.add_argument("--save", metavar="PATH", help=".usd 로 굽고 끝낸다")
    p.add_argument("--shot", metavar="PATH",
                   help="뷰포트를 PNG 로 찍고 끝낸다. WebRTC 클라이언트 없이 "
                        "씬이 제대로 그려지는지 확인할 때 쓴다")
    p.add_argument("--radius", type=float, default=34.0, help="공전 반지름 (m)")
    p.add_argument("--height", type=float, default=18.0, help="공전 높이 (m)")
    p.add_argument("--grid", action="store_true",
                   help="뷰포트 기준 그리드를 켠다 (기본은 끔 — 바닥을 덮어 버린다)")
    p.add_argument("--cam", metavar="PRIM",
                   help="이 카메라로 본다. 예: /World/Webcam1 (오버헤드 웹캠), "
                        "/World/AMR1/OcrCam (AMR1 이 보는 화면). "
                        "기본은 공전하는 /World/ViewCam")
    p.add_argument("--amr1-stall", type=int, metavar="N",
                   help="AMR1 을 N번 주차면 앞 촬영 위치에 세운다")
    p.add_argument("--seed", type=int, default=None,
                   help="배치 난수 씨앗. 같은 값이면 같은 배치가 나온다")
    p.add_argument("--occupancy", type=float, default=0.65,
                   help="주차면이 차 있을 확률 (기본 0.65)")
    p.add_argument("--illegal-bias", type=float, default=0.45,
                   help="차가 있을 때 일부러 불법으로 놓을 확률 (기본 0.45)")
    p.add_argument("--period", type=float, default=45.0, help="한 바퀴 도는 데 걸리는 초")
    return p.parse_args()


ARGS = parse_args()

# 🚨 `SimulationApp` 은 **다른 무엇보다 먼저** 만들어야 한다. omni/pxr 확장은
#    Kit 이 뜬 뒤에야 import 가 된다 — 위에서 미리 import 하면 ModuleNotFound 로
#    죽거나, 더 나쁘게는 반쯤 초기화된 모듈을 잡아 나중에 세그폴트한다.
#    launch_config 는 비워 둔다: headless/hide_ui/experience 는 autostream 이 정한다.
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({})

import omni.usd  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402
import lot  # noqa: E402


def look_at(eye, target, up=Gf.Vec3d(0.0, 0.0, 1.0)):
    """`eye` 에서 `target` 을 보는 카메라 변환 행렬.

    USD 카메라는 자기 좌표계에서 **-Z 를 본다** (+X 오른쪽, +Y 위). 그래서
    행렬의 세 행에 각각 right / up / **-forward** 를 넣는다. -forward 를
    forward 로 잘못 넣으면 카메라가 정확히 반대편(주차장 바깥)을 본다.
    """
    fwd = (target - eye).GetNormalized()
    right = Gf.Cross(fwd, up).GetNormalized()
    upn = Gf.Cross(right, fwd)
    m = Gf.Matrix4d(1.0)
    m.SetRow3(0, right)
    m.SetRow3(1, upn)
    m.SetRow3(2, -fwd)
    m.SetTranslateOnly(eye)
    return m


def main():
    ctx = omni.usd.get_context()
    ctx.new_stage()
    stage = ctx.get_stage()

    plan = layout.plan(ARGS.seed, ARGS.occupancy, ARGS.illegal_bias)
    lot.build(stage, plan)
    print()
    print(layout.summary(plan))
    print()

    # --amr1-stall 을 주면 그 자리 촬영 위치로 AMR1 을 옮긴다. 씬을 다시 짓지
    # 않고 Xform 만 고쳐 쓴다 — 자리 계산이 lot.approach_pose 한 곳에만 있다.
    if ARGS.amr1_stall is not None:
        match = [s for s in plan["stalls"] if s["id"] == ARGS.amr1_stall]
        if not match:
            print(f"[씬] ❌ {ARGS.amr1_stall}번 주차면이 없다 "
                  f"(0~{len(plan['stalls']) - 1})")
            pyver.hard_exit(simulation_app)
        x, y, yaw = lot.approach_pose(match[0])
        prim = stage.GetPrimAtPath("/World/AMR1")
        # 🚨 op 를 **새로 붙이지 말고 값만 갈아끼운다.** AddRotateZOp 을 다시
        #    부르면 회전이 하나 더 쌓여 두 번 돌아간다 (`lot._amr` 가 이미
        #    translate·rotateZ 를 순서대로 만들어 둔다).
        ops = UsdGeom.Xformable(prim).GetOrderedXformOps()
        ops[0].Set(Gf.Vec3d(x, y, lot.AMR_SPAWN_Z))
        ops[1].Set(yaw)
        v = match[0]["vehicle"]
        print(f"[씬] AMR1 → {ARGS.amr1_stall}번({match[0]['zone']}) 촬영 위치 "
              f"({x:.2f}, {y:.2f}, yaw={yaw:.0f}) "
              f"대상: {v['plate'] if v else '빈 칸'}")

    if ARGS.save:
        path = os.path.abspath(ARGS.save)
        stage.Export(path)
        print(f"[씬] 저장 완료: {path}")
        pyver.hard_exit(simulation_app)

    # 뷰포트 기준 그리드는 z=0 에 그려져 **주차장 바닥과 겹친다.** 아스팔트와
    # 주차선이 격자에 묻혀 "바닥이 안 그려진 것처럼" 보인다. 씬의 일부가 아니라
    # 에디터 오버레이이므로 기본으로 끈다.
    if not ARGS.grid:
        import carb.settings
        carb.settings.get_settings().set("/app/viewport/grid/enabled", False)

    # ── 공전용 뷰 카메라 ────────────────────────────────────────
    cam = UsdGeom.Camera.Define(stage, "/World/ViewCam")
    # 초점거리를 키우면 화각이 좁아진다. 주차장이 32×23 m 로 넓어서 22 쯤이
    # 반지름 34 에서 전체가 들어온다.
    cam.CreateFocalLengthAttr(22.0)
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 500.0))
    # 매 프레임 통째로 갈아끼울 행렬 op 하나만 둔다. Translate/Rotate 를 따로
    # 쌓으면 프레임마다 op 가 늘어나 순서가 꼬인다.
    cam_op = UsdGeom.Xformable(cam).AddTransformOp()

    # 주차장 전체의 가운데를 겨눈다 (통로 한복판).
    gx0, gx1, gy0, gy1 = lot.GROUND
    target = Gf.Vec3d((gx0 + gx1) / 2.0, (gy0 + gy1) / 2.0 + 1.0, 0.8)

    def place(t):
        # 🚨 목표 지점을 **중심으로** 돌아야 한다. 원점 기준으로 돌리면 주차장이
        #    x=14 에 있으므로 한 바퀴 도는 동안 화면 밖으로 나갔다 들어온다.
        a = 2.0 * math.pi * (t / ARGS.period) if ARGS.period else 0.0
        eye = Gf.Vec3d(target[0] + math.sin(a) * ARGS.radius,
                       target[1] - math.cos(a) * ARGS.radius,
                       ARGS.height)
        cam_op.Set(look_at(eye, target))

    place(0.0)

    # 뷰포트를 이 카메라로 돌린다. 이게 없으면 기본 퍼스펙티브 카메라가 잡혀
    # 공전이 화면에 안 나타난다 — "스트리밍이 멈춘 것처럼" 보이는 원인이다.
    # --cam 을 주면 그 카메라로 본다. 그러면 공전은 의미가 없다 (ViewCam 만
    # 움직이므로 화면이 멈춘 것처럼 보인다) — 그래서 같이 꺼 둔다.
    cam_path = ARGS.cam or "/World/ViewCam"
    if ARGS.cam:
        if not stage.GetPrimAtPath(ARGS.cam):
            print(f"[씬] ❌ 카메라 프림이 없다: {ARGS.cam}")
            pyver.hard_exit(simulation_app)
        ARGS.no_orbit = True

    vp = None
    try:
        from omni.kit.viewport.utility import get_active_viewport
        vp = get_active_viewport()
        if vp is not None:
            vp.camera_path = cam_path
            print(f"[씬] 뷰포트 카메라 → {cam_path}")
    except Exception as exc:
        print(f"[씬] ⚠ 뷰포트 카메라를 못 바꿨다 ({exc.__class__.__name__}: {exc}) — "
              f"클라이언트에서 직접 고를 것")

    # ── 한 장 찍고 끝내기 ──────────────────────────────────────
    if ARGS.shot:
        if vp is None:
            print("[씬] ❌ 뷰포트를 못 잡아 캡처할 수 없다")
            pyver.hard_exit(simulation_app)
        path = os.path.abspath(ARGS.shot)
        # 🚨 캡처 전에 여러 프레임을 돌려야 한다. RTX 는 점진적으로 수렴하는
        #    렌더러라 첫 프레임은 텍스처·머티리얼·가속구조가 아직 안 올라와
        #    **검거나 얼룩진 그림**이 나온다. 60프레임이면 이 씬에는 충분하다.
        for _ in range(60):
            simulation_app.update()
        from omni.kit.viewport.utility import capture_viewport_to_file
        capture_viewport_to_file(vp, file_path=path)
        # capture 는 비동기다 — 요청만 걸고 반환하므로, 파일이 실제로 쓰일
        # 때까지 프레임을 더 돌려 준다. 안 그러면 0바이트 파일이 남는다.
        for _ in range(60):
            simulation_app.update()
        print(f"[씬] 캡처 완료: {path}")
        pyver.hard_exit(simulation_app)

    # ── 렌더 루프 ──────────────────────────────────────────────
    # `simulation_app.update()` 한 번이 한 프레임이다. 물리는 안 쓰므로
    # SimulationContext 없이 update() 만 돈다.
    print("[씬] 렌더 시작 — WebRTC 클라이언트로 접속할 것. 종료는 Ctrl+C")
    dt = 1.0 / 60.0
    i = 0
    try:
        while simulation_app.is_running():
            if not ARGS.no_orbit:
                place(i * dt)
            simulation_app.update()
            i += 1
            if i % 600 == 0:
                print(f"[씬] {i} 프레임 ({i * dt:.0f}초)")
            if ARGS.steps and i >= ARGS.steps:
                print(f"[씬] --steps {ARGS.steps} 도달 — 종료")
                break
    except KeyboardInterrupt:
        print("\n[씬] Ctrl+C — 종료")

    pyver.hard_exit(simulation_app)


if __name__ == "__main__":
    main()
