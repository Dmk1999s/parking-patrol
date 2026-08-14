"""순찰 씬 — 물리·라이다·차동구동이 살아 있는 판. SLAM 부터 여기서 돈다.

`parking_lot.py` 는 **그림만** 확인하는 씬이라 물리를 안 켠다. 이 파일은 그
반대다 — 로봇이 바닥을 딛고, 라이다가 돌고, `/cmd_vel` 로 굴러간다.

    isaac_python sim/scenes/patrol.py                 # ROS 2 + WebRTC (기본)
    isaac_python sim/scenes/patrol.py --drive 0.15    # ROS 없이 물리만 자체 점검
    ISAAC_STREAM=0 isaac_python sim/scenes/patrol.py --steps 600 --shot out.png

## 나가는 것 / 들어오는 것

    /clock                          시뮬 시간
    /amr1/scan  /amr2/scan          LaserScan  ← SLAM 입력
    /amr1/odom  /amr2/odom          Odometry
    /tf                             amr{1,2}/odom → base_link → base_scan
    /amr1/cmd_vel  /amr2/cmd_vel    Twist      → 차동구동 (Nav2 가 여기로 낸다)

배선은 전부 `ros_bridge.py` 에 있다.

## 🚨 `ros2 topic list` 에 아무것도 안 보인다면

세 가지를 순서대로 본다 — **셋 다 오류를 안 낸다**:

1. `ROS_DOMAIN_ID` 가 **2** 인가 (`bridge/bridge_amr1.py` 가 2 로 박아 둔다)
2. 프로세스가 `LD_LIBRARY_PATH` 를 갖고 떴는가 — `pyver.ensure_ros2_libs()` 가
   자동으로 넣고 재실행하므로 보통은 알아서 된다. 로그에 그 줄이 있는지 본다.
3. **재생 중인가.** OmniGraph 의 `OnPlaybackTick` 은 타임라인이 재생 중일 때만
   깨어난다. 정지 상태면 그래프가 통째로 안 돌아 토픽이 하나도 안 나온다.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
import pyver  # noqa: E402

pyver.require_isaac("sim/scenes/patrol.py")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=None, help="배치 난수 씨앗")
    p.add_argument("--occupancy", type=float, default=0.65)
    p.add_argument("--illegal-bias", type=float, default=0.45)
    p.add_argument("--steps", type=int, default=0,
                   help="N 물리스텝 뒤 종료. 0 이면 무한 (기본)")
    p.add_argument("--no-ros", action="store_true",
                   help="ROS 2 배선을 건너뛴다 (물리만 볼 때)")
    p.add_argument("--robots", choices=("amr1", "amr2", "both"), default="both",
                   help="어느 로봇에 ROS 배선(라이다 포함)을 붙일지. RTX 라이다가 "
                        "GPU 를 많이 먹어서, SLAM 매핑처럼 한 대만 쓸 때는 "
                        "그 한 대만 붙이면 시뮬이 눈에 띄게 빨라진다")
    p.add_argument("--no-webcam", action="store_true",
                   help="오버헤드 웹캠 ROS 발행을 끈다 "
                        "(기본은 webcam_images/webcam1/detections 발행)")
    p.add_argument("--drive", type=float, metavar="V",
                   help="ROS 없이 AMR1 을 V m/s 로 전진시켜 물리를 자체 점검한다")
    p.add_argument("--turn", type=float, default=0.0, metavar="W",
                   help="--drive 와 함께 쓰는 각속도 (rad/s)")
    p.add_argument("--cam", metavar="PRIM", help="이 카메라로 본다")
    p.add_argument("--shot", metavar="PATH", help="끝나고 PNG 한 장")
    p.add_argument("--save", metavar="PATH", help=".usd 로 굽고 끝낸다")
    p.add_argument("--report", type=float, default=2.0,
                   help="상태를 몇 초마다 찍을지 (0 이면 조용히)")
    return p.parse_args()


ARGS = parse_args()

# 🚨 ROS 2 브리지가 쓰는 번들 C 라이브러리 경로는 **프로세스가 뜨기 전에**
#    잡혀 있어야 한다. 아래 함수가 필요하면 경로를 넣고 자기 자신을 재실행한다.
#    SimulationApp 을 만든 뒤에는 늦다 (동적 링커가 이미 읽었다).
if not ARGS.no_ros:
    pyver.ensure_ros2_libs("sim/scenes/patrol.py")

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({})

import carb.settings  # noqa: E402
import isaacsim.core.experimental.utils.app as app_utils  # noqa: E402
import omni.usd  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402
import lot  # noqa: E402

PHYSICS_HZ = 60.0
ROBOTS = (("/World/AMR1", "amr1"), ("/World/AMR2", "amr2"))


def _pose(art):
    """아티큘레이션의 (x, y, yaw°) — 눈으로 확인할 때 쓴다."""
    import numpy as np
    pos, quat = art.get_world_poses()
    p = np.asarray(pos).reshape(-1)[:3]
    q = np.asarray(quat).reshape(-1)[:4]        # (w, x, y, z)
    yaw = math.degrees(math.atan2(2.0 * (q[0] * q[3] + q[1] * q[2]),
                                  1.0 - 2.0 * (q[2] ** 2 + q[3] ** 2)))
    return float(p[0]), float(p[1]), float(p[2]), yaw


def main():
    ctx = omni.usd.get_context()
    ctx.new_stage()
    stage = ctx.get_stage()

    plan = layout.plan(ARGS.seed, ARGS.occupancy, ARGS.illegal_bias)
    lot.build(stage, plan)
    print()
    print(layout.summary(plan))
    print()

    if ARGS.save:
        path = os.path.abspath(ARGS.save)
        stage.Export(path)
        print(f"[씬] 저장 완료: {path}")
        pyver.hard_exit(simulation_app)

    settings = carb.settings.get_settings()
    settings.set("/app/viewport/grid/enabled", False)
    # 🔑 고정 스텝. 끄면 프레임이 늦을 때 물리 dt 가 같이 늘어나 같은 명령에도
    #    로봇이 매번 다른 거리를 간다 — 재현이 안 된다.
    settings.set("/app/player/useFixedTimeStepping", True)
    # 🚨 바퀴(실린더 콜라이더)를 **컨벡스 근사**로 돌린다. 기본값(커스텀
    #    지오메트리 실린더)은 접촉 생성이 위치에 따라 실패한다 — 실측:
    #    같은 로봇이 (3.2,-3)에서는 멀쩡한데 (1.2,-3)에서는 바퀴 접촉이
    #    안 생겨 4.4° 앞으로 기운 채 base_link 박스로 서 버리고, 바퀴가
    #    헛돌아 로봇이 못 움직인다. 오류·경고는 전혀 없다.
    #    근사로 바꾸면 두 자리 모두 정상 안착(pitch 0.2°)하고 굴러간다.
    #    ⚠ 물리 파싱 전(재생 걸기 전)에 넣어야 먹는다.
    settings.set("/physics/collisionApproximateCylinders", True)

    if not ARGS.no_ros:
        import ros_bridge
        wired = [r for r in ROBOTS if ARGS.robots in ("both", r[1])]
        ros_bridge.wire(stage, wired, webcam=not ARGS.no_webcam)
        print(f"[씬] ROS_DOMAIN_ID = {os.environ.get('ROS_DOMAIN_ID', '(미설정 — 0)')}")

    # ── 뷰포트 카메라 ──────────────────────────────────────────
    vp = None
    try:
        from omni.kit.viewport.utility import get_active_viewport
        vp = get_active_viewport()
        if vp is not None and ARGS.cam:
            if not stage.GetPrimAtPath(ARGS.cam):
                print(f"[씬] ❌ 카메라 프림이 없다: {ARGS.cam}")
                pyver.hard_exit(simulation_app)
            vp.camera_path = ARGS.cam
            print(f"[씬] 뷰포트 카메라 → {ARGS.cam}")
    except Exception as exc:
        print(f"[씬] ⚠ 뷰포트를 못 잡았다 ({exc.__class__.__name__}: {exc})")

    # ── 물리 시작 ──────────────────────────────────────────────
    # 🚨 재생을 걸어야 물리도 OmniGraph 도 돈다. 정지 상태에서는 update() 가
    #    렌더만 하고 로봇은 공중에 그대로 떠 있는다 — "물리가 안 붙었다" 로
    #    보이지만 실제로는 재생을 안 건 것이다.
    app_utils.play()
    simulation_app.update()

    from isaacsim.core.experimental.prims import Articulation
    arts = {ns: Articulation(path) for path, ns in ROBOTS}
    a1 = arts["amr1"]
    print(f"[씬] AMR1 관절: {a1.dof_names}")

    # ── 자체 점검용 직접 구동 ──────────────────────────────────
    # ROS 를 거치지 않고 바퀴에 직접 명령한다. 물리·구동이 되는지와 ROS 배선이
    # 되는지를 **따로** 확인할 수 있어야 한다 — 같이 보면 어느 쪽이 고장인지
    # 알 수 없다.
    wheel_idx = None
    if ARGS.drive is not None:
        names = list(a1.dof_names)
        try:
            wheel_idx = [names.index(j) for j in lot.TB3_WHEEL_JOINTS]
        except ValueError:
            print(f"[씬] ❌ 바퀴 관절을 못 찾았다. 있는 관절: {names}")
            pyver.hard_exit(simulation_app)
        v, w = ARGS.drive, ARGS.turn
        r, b = lot.TB3_WHEEL_RADIUS, lot.TB3_WHEEL_BASE
        targets = [(v - w * b / 2.0) / r, (v + w * b / 2.0) / r]
        print(f"[씬] 자체 점검 구동: v={v} m/s, w={w} rad/s "
              f"→ 바퀴 {targets[0]:.2f} / {targets[1]:.2f} rad/s")

    print("[씬] 시작 — 종료는 Ctrl+C")
    dt = 1.0 / PHYSICS_HZ
    report_every = int(ARGS.report * PHYSICS_HZ) if ARGS.report else 0
    i = 0
    try:
        while simulation_app.is_running():
            if wheel_idx is not None:
                # 매 스텝 다시 넣는다. 한 번만 넣으면 물리가 리셋될 때 조용히
                # 0 으로 돌아간다.
                import numpy as np
                a1.set_dof_velocity_targets(
                    np.array([targets], dtype=np.float32),
                    dof_indices=np.array(wheel_idx, dtype=np.int32))
            simulation_app.update()
            i += 1
            if report_every and i % report_every == 0:
                line = f"[씬] {i:>6} 스텝 ({i * dt:6.1f}초)"
                for ns, art in arts.items():
                    x, y, z, yaw = _pose(art)
                    line += f"   {ns} ({x:6.2f}, {y:6.2f}, z={z:5.3f}, yaw={yaw:7.1f}°)"
                print(line)
            if ARGS.steps and i >= ARGS.steps:
                print(f"[씬] --steps {ARGS.steps} 도달 — 종료")
                break
    except KeyboardInterrupt:
        print("\n[씬] Ctrl+C — 종료")

    if ARGS.shot and vp is not None:
        from omni.kit.viewport.utility import capture_viewport_to_file
        path = os.path.abspath(ARGS.shot)
        capture_viewport_to_file(vp, file_path=path)
        # 캡처는 비동기다 — 파일이 실제로 쓰일 때까지 프레임을 더 돌려 준다.
        for _ in range(60):
            simulation_app.update()
        print(f"[씬] 캡처 완료: {path}")

    pyver.hard_exit(simulation_app)


if __name__ == "__main__":
    main()
