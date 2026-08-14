"""isaac_python 으로 띄우면 WebRTC 스트리밍(GUI 포함)이 저절로 켜지게 한다.

    PYTHONUNBUFFERED=1 isaac_python <씬>      # --stream 없이도 화면이 나간다

`isaac_python` 함수(`sim/setup/env.sh`)가 PYTHONPATH 에 이 디렉터리를 넣는다.
파이썬은 본문을 실행하기 **전에** sys.path 에서 `sitecustomize` 를 찾아 읽으므로,
여기서 `isaacsim.SimulationApp` 을 가로채 두면 씬 스크립트를 하나도 안 고쳐도 된다.

가로채서 하는 일은 세 가지다.

    experience = isaacsim.exp.base.kit   기본 experience 엔 에디터 UI 가 없다
    hide_ui    = False                   headless 가 넣는 hideUi=1 을 되돌린다
    앱이 뜬 직후 livestream.start()      설정 → 확장 순서라야 포트가 맞는다

`headless=True` 는 **그대로 둔다.** 이 서버엔 디스플레이가 없어서 창을 만들려
하면 IWindowing 획득 실패로 즉시 죽는다. 창이 없는 것과 UI 가 없는 것은 다른
얘기다 — UI 는 오프스크린으로 그려져 WebRTC 로 실려 나간다.

## 끄는 법

    ISAAC_STREAM=0 isaac_python <씬>

배치로 돌려 산출물만 뽑을 때는 꺼 두는 게 낫다. 스트리밍은 매 프레임을 실제로
그리므로 그만큼 느리고, 49100 을 물고 있는다.

## 🚨 동시에 두 개를 띄우지 말 것

WebRTC 시그널링 소켓은 SO_REUSEPORT 로 열린다. 그래서 두 프로세스가 **오류 없이
동시에 49100 을 리슨**하고, 커널이 접속을 둘에 나눠 준다 — 클라이언트가 엉뚱한
프로세스에 붙어 "아무것도 안 뜨는" 증상이 된다. 포트 충돌 오류가 안 나서 양쪽 다
정상으로 보이는 게 고약한 점이다. 아래 `_port_busy()` 가 이걸 막는다.
"""

import os
import sys

PORT = 49100

_HERE = os.path.dirname(os.path.abspath(__file__))

# `livestream.py` 는 **이 파일 바로 옆**에 둔다. 둘은 한 몸이라 같이 움직인다.
# (파이프 프로젝트에서는 이 둘을 갈라 두었다가 한쪽이 지워져 스트리밍이 경고 한
#  줄만 남기고 조용히 꺼진 적이 있다 — 에러가 아니라서 진단이 오래 걸렸다.)
_SEARCH = [_HERE]


def _port_busy():
    """이미 누가 49100 을 리슨하고 있나. 판단이 안 서면 False(=진행)."""
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _load_livestream():
    """`livestream.py` 를 경로로 읽어 온다. 규칙은 거기 한 곳에만 둔다."""
    import importlib.util
    for d in _SEARCH:
        path = os.path.join(d, "livestream.py")
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location(
            "_autostream_livestream", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


def _install():
    import isaacsim

    livestream = _load_livestream()
    if livestream is None:
        print(f"[자동스트리밍] livestream.py 를 못 찾았다 — 그냥 뜬다\n"
              f"                찾은 곳: {_SEARCH}")
        return

    _orig = isaacsim.SimulationApp

    def SimulationApp(launch_config=None, experience=""):
        cfg, exp = livestream.app_config()
        # 씬이 준 값을 살리되, 스트리밍에 필요한 두 개는 우리가 정한다.
        merged = dict(launch_config or {})
        merged.update(cfg)
        app = _orig(merged, experience=experience or exp)

        # 스트리밍은 앱이 뜬 **뒤에** 켠다. 순서가 바뀌면 기본 포트로 열린다.
        if _port_busy():
            print("=" * 78)
            print(f"  [자동스트리밍] 건너뜀 — 이미 TCP {PORT} 를 쓰는 프로세스가 있다.")
            print("  두 개를 동시에 띄우면 접속이 둘로 나뉘어 화면이 안 뜬다.")
            print("  확인:  pgrep -af 'isaacsim_venv/bin/python'")
            print("=" * 78)
        else:
            livestream.start()
        return app

    SimulationApp.__doc__ = _orig.__doc__
    isaacsim.SimulationApp = SimulationApp


if os.environ.get("ISAAC_STREAM", "1") != "0":
    try:
        _install()
    except Exception as exc:                    # 여기서 죽으면 씬이 안 뜬다
        print(f"[자동스트리밍] 설치 실패({exc.__class__.__name__}: {exc}) — 그냥 뜬다",
              file=sys.stderr)
