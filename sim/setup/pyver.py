"""[공용] 파이썬 버전 구분 — 어느 인터프리터에서 돌아야 하는 코드인지 못박는다.

## 왜 나뉘는가

**Isaac Sim 6.0 은 Python 3.12 전용**이다. ROS 2 Humble 은 시스템 파이썬 3.10 으로
빌드돼 있다. 둘은 확장 모듈 ABI 가 달라 서로의 라이브러리를 못 읽는다.

    sim/scenes/         Python 3.12    isaacsim / omni / pxr  ← isaac_python
    bridge/             Python 3.10    rclpy / cv_bridge      ← patrol_ros
    Django (app/ config/)  Python 3.10    venv/               ← patrol_run

**Isaac Sim 을 띄우는 터미널에서 `/opt/ros/humble/setup.bash` 를 source 하면
안 된다.** 3.10 라이브러리가 앞에 잡혀 심볼이 충돌한다. Isaac 쪽에서 rclpy 가
필요하면 `isaac_ros` 를 쓴다 — Isaac Sim 이 번들로 갖고 있는 3.12 용 rclpy
경로를 잡아 준다 (6.0 기준 `exts/isaacsim.ros2.core/humble/rclpy`).

## 그런데 통신은 왜 되는가

**DDS 가 파이썬 버전과 무관하게 데이터를 나르기 때문이다.** 3.12 쪽 씬이 발행한
`webcam_objects/map_detections` 를 3.10 쪽 `bridge/bridge_webcam.py` 가 그대로
받는다. 토픽 이름·메시지 타입·`ROS_DOMAIN_ID` 만 맞으면 된다.

🚨 이 프로젝트의 `ROS_DOMAIN_ID` 는 **2** 다 (`bridge/bridge_amr1.py:40` 이
   import 전에 직접 넣는다). 다르면 오류 없이 토픽이 안 보인다.
"""

import os
import sys

ISAAC_PY = (3, 12)
ROS_PY = (3, 10)

SKIP = os.environ.get("PATROL_SKIP_PYVER") == "1"


def _fail(msg):
    if SKIP:
        print(f"[pyver] 무시함(PATROL_SKIP_PYVER=1): {msg}", file=sys.stderr)
        return
    raise RuntimeError(msg)


def _here():
    return "%d.%d" % sys.version_info[:2]


def require_isaac(who="", needs_rclpy=False):
    """Isaac Sim 인터프리터에서만 돌아야 하는 파일이 맨 위에서 부른다.

    3.10 으로 잘못 띄우면 `from isaacsim import ...` 가 먼저 터지는데, 그
    메시지로는 원인을 알 수 없다. 그래서 그 전에 막는다.
    """
    if sys.version_info[:2] != ISAAC_PY:
        _fail(f"{who or '이 파일'} 은 Isaac Sim 전용(Python "
              f"{ISAAC_PY[0]}.{ISAAC_PY[1]})인데 {_here()} 로 실행됐다.\n"
              f"  isaac_python 으로 실행할 것.\n"
              f"  브리지 노드를 띄우려던 것이면 그 파일은 bridge/ 쪽이다.")
    if needs_rclpy:
        try:
            import rclpy  # noqa: F401
        except ImportError as e:
            _fail(f"{who or '이 파일'} 은 rclpy 로 직접 발행하는데 Isaac Sim "
                  f"3.12 환경에 rclpy 가 없다 ({e}).\n"
                  f"  같은 터미널에서 먼저:  isaac_ros\n"
                  f"  (Isaac Sim 6.0 이 번들로 가진 3.12 용 rclpy 경로를 잡는다 —\n"
                  f"   IsaacSim-ros_workspaces 도커 빌드는 필요 없다)")


def _bundle_ros2_lib():
    """Isaac 번들 ROS 2 C 라이브러리 디렉터리. 없으면 None."""
    import sysconfig
    root = os.environ.get("ISAACSIM_ROOT") or os.path.join(
        sysconfig.get_paths()["purelib"], "isaacsim")
    distro = os.environ.get("ISAAC_ROS_DISTRO", "humble")
    path = os.path.join(root, "exts", "isaacsim.ros2.core", distro, "lib")
    return path if os.path.isdir(path) else None


def ensure_ros2_libs(who=""):
    """ROS 2 브리지를 켤 파일이 **SimulationApp 을 만들기 전에** 부른다.

    ## 왜 필요한가 — 조용히 실패하는 지점이다

    `isaacsim.ros2.bridge` 는 번들 C 라이브러리(`librcutils.so` 등)를 dlopen
    하는데, `LD_LIBRARY_PATH` 에 그 디렉터리가 없으면 이렇게 된다:

        Could not load the dynamic library from librcutils.so
        [Error] [isaacsim.ros2.core.impl.extension] ROS2 Bridge startup failed

    🚨 **그런데 확장은 `enabled` 로 남고, 그래프도 오류 없이 만들어진다.**
       ROS2 노드들이 그냥 아무것도 발행하지 않는다 — `ros2 topic list` 가
       비어 있는 것 말고는 증상이 없어서 도메인 ID·방화벽·RMW 를 엉뚱하게
       뒤지게 된다. 그래서 여기서 못박는다.

    `LD_LIBRARY_PATH` 는 프로세스가 뜰 때 동적 링커가 읽으므로 **지금 고쳐도
    이미 늦다.** 그래서 경로를 넣고 같은 인자로 **자기 자신을 재실행한다**
    (`isaac_ros` 를 깜빡한 터미널에서도 그냥 돌게 하려는 것이다).
    """
    if SKIP:
        return
    lib = _bundle_ros2_lib()
    if lib is None:
        _fail(f"{who or '이 파일'} 은 ROS 2 브리지가 필요한데 번들 라이브러리를 "
              f"못 찾았다.\n  ISAACSIM_ROOT / ISAAC_ROS_DISTRO 를 확인할 것.")
        return
    if lib in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
        return
    if os.environ.get("PATROL_ROS2_LIBS_REEXEC") == "1":
        _fail(f"{who or '이 파일'}: LD_LIBRARY_PATH 를 넣고 재실행했는데도 "
              f"경로가 안 잡혔다.\n  수동으로:  isaac_ros\n  경로: {lib}")
        return
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"]
                                    if env.get("LD_LIBRARY_PATH") else "")
    env["PATROL_ROS2_LIBS_REEXEC"] = "1"
    env.setdefault("ROS_DISTRO", os.environ.get("ISAAC_ROS_DISTRO", "humble"))
    env.setdefault("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    print(f"[pyver] ROS 2 브리지용 LD_LIBRARY_PATH 를 넣고 재실행한다\n"
          f"        + {lib}", flush=True)
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def require_ros(who=""):
    """ROS 2 노드로 도는 파일이 맨 위에서 부른다."""
    if sys.version_info[:2] != ROS_PY:
        _fail(f"{who or '이 파일'} 은 ROS 2 Humble 노드(Python "
              f"{ROS_PY[0]}.{ROS_PY[1]})인데 {_here()} 로 실행됐다.\n"
              f"  patrol_ros 후 python3 로 실행할 것.")


def describe():
    """지금 인터프리터가 어느 쪽인지 한 줄로."""
    v = _here()
    side = ("Isaac Sim" if sys.version_info[:2] == ISAAC_PY else
            "ROS 2 / Django" if sys.version_info[:2] == ROS_PY else "알 수 없음")
    return f"Python {v} → {side} 쪽"


def hard_exit(app, timeout=5.0):
    """Isaac 종료 지연을 잘라낸다.

    `simulation_app.close()` 는 "Simulation App Shutting Down" 을 **찍은 뒤**
    내부에서 매달린다(실측: 계산 11초, 프로세스 5분+ 잔존). close() 뒤에
    os._exit 을 두어도 close() 가 반환하지 않으므로 도달하지 못한다.
    그래서 close() 를 데몬 스레드에 맡겨 timeout 만 기다리고 즉시 빠져나온다.

    산출물은 이 시점에 이미 디스크에 있으므로 정리를 건너뛰어도 안전하다.
    """
    import threading
    sys.stdout.flush()
    sys.stderr.flush()
    if app is not None:
        threading.Thread(target=app.close, daemon=True).start()
    threading.Event().wait(timeout)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    print(describe())
    print(f"  ROS_DOMAIN_ID = {os.environ.get('ROS_DOMAIN_ID', '(미설정 — 기본 0)')}")
    for mod, tag in (("pxr", "Isaac"), ("omni", "Isaac"), ("isaacsim", "Isaac"),
                     ("rclpy", "ROS"), ("cv_bridge", "ROS"),
                     ("numpy", "공용"), ("cv2", "공용"), ("requests", "공용")):
        try:
            __import__(mod)
            got = "있음"
        except ImportError:
            got = "없음"
        print(f"  {tag:>6}  {mod:<10} {got}")
