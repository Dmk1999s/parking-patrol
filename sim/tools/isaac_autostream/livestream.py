"""WebRTC 스트리밍 규칙 한 곳 — `sitecustomize.py` 가 이 파일만 읽는다.

**Isaac Sim 6.0.1.0 기준이다.** 5.1 과 구조가 통째로 다르다(아래 표).

`isaac_python` 으로 씬을 띄우면 창 대신 **전용 클라이언트로 화면을 본다.**
이 서버에는 디스플레이가 없어서 창을 만들려 하면 IWindowing 획득 실패로 즉시
죽는다. 창이 없는 것과 UI 가 없는 것은 다른 얘기다 — UI 는 오프스크린으로
그려져 WebRTC 로 실려 나간다.

## 🚨 5.1 → 6.0 에서 바뀐 것 (실측: `apps/isaacsim.exp.full.streaming.kit`)

    확장 이름       omni.kit.livestream.webrtc   →  omni.kit.livestream.app
    시그널링 포트   /app/livestream/port         →  primaryStream/signalPort
    퍼블릭 IP       .../publicEndpointAddress    →  primaryStream/publicIp
    미디어 포트     minHostPort~maxHostPort      →  primaryStream/streamPort (하나)
    스트림 종류     (없음)                       →  primaryStream/streamType = "webrtc"
    자동 종료       omni.services.livestream.nvcf → omni.services.livestream.session

    설정 경로가 `/app/livestream/*` 에서
    `/exts/omni.kit.livestream.app/primaryStream/*` 로 옮겨 갔다.
    🚨 옛 경로에 써도 **오류가 안 난다** — carb 은 모르는 키도 그냥 받는다.
       그래서 "설정은 분명히 했는데 기본 포트로 열리는" 증상이 된다. 5.1 코드를
       그대로 가져오면 정확히 이 함정에 빠진다.

🚨 **브라우저로는 못 본다.** 49100 은 웹페이지가 아니라 **WebSocket 시그널링
   포트**라 브라우저로 열면 아무것도 안 나온다.

   → NVIDIA 가 따로 배포하는 **Isaac Sim WebRTC Streaming Client**(데스크톱
     앱)를 쓴다. 앱의 **서버 주소 칸에 IP 만** 넣는다 — 포트도 `http://` 도
     붙이지 않는다. 클라이언트 버전은 서버(6.0)와 맞춰야 한다.

    TCP 49100 (시그널링) / UDP 47998-48020 (미디어) 이 보안그룹에 열려 있어야 한다.

🚨 **이 파일이 없으면 스트리밍이 조용히 꺼진다.** `sitecustomize.py` 는 못
   찾으면 경고 한 줄만 찍고 그냥 뜬다 — 그래서 "WebRTC 에 아무것도 안 뜬다"
   가 된다. 그래서 **`sitecustomize.py` 바로 옆**에 둔다. 둘은 한 몸이다.

🚨 **`isaacsim.exp.full.streaming` 을 쓰지 않는다.** 그 experience 는
   `omni.services.livestream.session` 의 `quitOnSessionEnded = true` 를 켜
   두어서 **클라이언트가 안 붙으면 스스로 종료한다**(5.1 의 nvcf 와 같은 함정이
   이름만 바뀐 채 그대로 있다). 우리는 `isaacsim.exp.base` 에
   `omni.kit.livestream.app` 만 직접 얹고, 그 설정을 명시적으로 꺼 둔다.

🚨 **publicIp 를 하드코딩하면 안 된다.** EIP 가 없는 인스턴스는 정지·시작할
   때마다 퍼블릭 IP 가 바뀐다. 옛 IP 가 박혀 있으면 시그널링(TCP 49100)은 붙는데
   ICE 후보가 옛 주소라 **영상이 영영 안 뜬다** (클라이언트는 검은 화면에서
   멈춘다). 그래서 실행 시점에 IMDS 에서 읽는다.
   다른 주소로 강제하려면  `ISAAC_PUB_IP=1.2.3.4 isaac_python ...`

끄는 법:  `ISAAC_STREAM=0 isaac_python <씬>`
"""

import os

SIGNAL_PORT = 49100        # TCP — WebSocket 시그널링
STREAM_PORT = 47998        # UDP — 미디어. 6.0 은 범위가 아니라 시작 포트 하나다
EXT_LIVESTREAM = "omni.kit.livestream.app"
EXT_SESSION = "omni.services.livestream.session"

# 🔑 `isaacsim.exp.base` 는 **에디터 UI 는 있고 ros2 bridge 는 없다.**
#    5.1 에서 `isaacsim.exp.full` 은 `isaacsim.ros2.bridge` 를 물고 오고, 그
#    확장이 rclpy 를 로드하는 순간 세그폴트했다. 6.0 에서 고쳐졌는지는 확인하지
#    않았다 — 우리는 rclpy 를 `isaac_ros`(PYTHONPATH)로 직접 잡으므로 브리지
#    확장이 애초에 필요 없다. 굳이 위험을 안을 이유가 없어 base 를 쓴다.
EXPERIENCE = os.environ.get("ISAAC_EXPERIENCE", "isaacsim.exp.base.kit")


def experience():
    """스트리밍용 experience 의 절대 경로.

    🔑 `isaacsim.exp.base.python.kit`(SimulationApp 기본값)에는 **에디터 UI 가
       없다.** 그걸로 스트리밍하면 뷰포트도 스테이지 트리도 없는 빈 화면이
       나온다. 그래서 UI 가 있는 `isaacsim.exp.base.kit` 으로 바꿔 준다.
    """
    import isaacsim
    return os.path.join(os.path.dirname(isaacsim.__file__), "apps", EXPERIENCE)


def app_config():
    """`SimulationApp(launch_config, experience=...)` 에 얹을 값.

    🚨 `headless` 는 **True 로 둔다.** 디스플레이가 없어 창을 만들려 하면
       죽는다. 대신 `hide_ui=False` 로 `--no-window` 가 자동으로 붙이는
       `--/app/window/hideUi=1` 을 되돌린다 — 이게 없으면 스트리밍은 되는데
       **UI 없이 검은 화면만** 나간다.
    """
    return {"headless": True, "hide_ui": False}, experience()


def public_ip():
    """퍼블릭 IP 를 실행 시점에 읽는다. 못 읽으면 None."""
    if os.environ.get("ISAAC_PUB_IP"):
        return os.environ["ISAAC_PUB_IP"]
    import urllib.request
    base = "http://169.254.169.254/latest"
    try:                                        # IMDSv2 (토큰 필요)
        req = urllib.request.Request(
            f"{base}/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        tok = urllib.request.urlopen(req, timeout=2).read().decode()
        req = urllib.request.Request(
            f"{base}/meta-data/public-ipv4",
            headers={"X-aws-ec2-metadata-token": tok})
        return urllib.request.urlopen(req, timeout=2).read().decode().strip()
    except Exception:
        pass
    try:                                        # IMDSv1
        return urllib.request.urlopen(
            f"{base}/meta-data/public-ipv4", timeout=2).read().decode().strip()
    except Exception:
        return None


def start():
    """앱이 뜬 **뒤에** 부른다. 설정 → 확장 순서라야 포트가 맞는다.

    🚨 순서를 뒤집으면(확장 먼저) 우리가 지정한 포트가 아니라 **기본 포트로
       열린다.** 그러면 보안그룹에 뚫어 둔 포트와 어긋나 접속이 안 된다.
    """
    import carb.settings
    s = carb.settings.get_settings()

    pfx = f"/exts/{EXT_LIVESTREAM}/primaryStream"
    ip = public_ip()
    if ip:
        s.set(f"{pfx}/publicIp", ip)
    s.set(f"{pfx}/signalPort", SIGNAL_PORT)
    s.set(f"{pfx}/streamPort", STREAM_PORT)
    s.set(f"{pfx}/streamType", "webrtc")
    s.set(f"{pfx}/allowDynamicResize", True)
    # 추적 로그(`NvStreamer-*.etli`)가 실행한 디렉터리에 쌓이는 것을 막는다.
    s.set(f"{pfx}/enableEventTracing", False)
    s.set(f"{pfx}/enableOpenTelemetry", False)

    # 🚨 클라이언트가 안 붙었다고 앱이 스스로 죽지 않게 한다. 이걸 안 끄면
    #    "띄웠는데 30초쯤 뒤 조용히 종료(exit 0)" 가 된다 — 오류가 아니라서
    #    원인이 안 보이는 게 고약하다.
    s.set(f"/exts/{EXT_SESSION}/quitOnSessionEnded", False)

    s.set("/app/window/drawMouse", False)
    s.set("/app/livestream/allowResize", True)

    import omni.kit.app
    mgr = omni.kit.app.get_app().get_extension_manager()
    # 6.0 은 스트리밍 확장을 pip 패키지에 **넣어 두지 않는다** — 레지스트리에서
    # 받아 `extscache/` 에 푼다. 그래서 첫 실행은 그만큼 느리고, 네트워크가
    # 막혀 있으면 실패한다(디스크를 아무리 뒤져도 확장이 안 보이는 이유다).
    ok = mgr.set_extension_enabled_immediate(EXT_LIVESTREAM, True)

    print("=" * 78)
    if ok is False:
        print(f"  [자동스트리밍] ❌ {EXT_LIVESTREAM} 를 못 켰다 — 화면이 안 뜬다")
        print(f"     6.0 은 이 확장을 레지스트리에서 받아 온다(pip 패키지에 없다).")
        print(f"     네트워크와 isaacsim/extscache/ 를 확인할 것")
    elif ip:
        print(f"  [자동스트리밍] WebRTC 엔드포인트: {ip}")
        print(f"                 **Isaac Sim WebRTC Streaming Client** 앱의 "
              f"주소 칸에 이 IP 만 넣는다")
        print(f"                 (브라우저로는 안 된다 — {SIGNAL_PORT} 은 웹페이지가 "
              f"아니라 WebSocket 시그널링이다)")
        print(f"                 TCP {SIGNAL_PORT} / UDP {STREAM_PORT}-48020 "
              f"가 보안그룹에 열려 있어야 한다")
    else:
        print("  [자동스트리밍] ⚠ 퍼블릭 IP 를 못 읽었다 — 시그널링은 붙어도 "
              "ICE 후보가 틀려 영상이 안 뜰 수 있다")
        print("                 ISAAC_PUB_IP=<주소> isaac_python ... 로 지정할 것")
    print("=" * 78)
