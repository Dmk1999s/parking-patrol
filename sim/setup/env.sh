#!/usr/bin/env bash
# 주차 단속 시뮬레이션 셸 환경 — `~/.bashrc` 에서 source 한다
# (sim/setup/install.sh env 가 그 줄을 넣는다).
#
# 🚨 **파이썬이 두 개다.** Isaac Sim 6.0 은 3.12 전용이고 ROS 2 Humble 은 시스템
#    3.10 으로 빌드돼 있다. 확장 모듈 ABI 가 달라 서로의 라이브러리를 못 읽는다.
#    그래서 자동으로 소싱하지 않고, 터미널마다 별칭으로 고른다.
#
#        bridge/ 노드 터미널   patrol_ros   (python 3.10)
#        Isaac Sim 터미널      isaac_ros    (python 3.12)  ← patrol_ros 를 쓰면 안 된다
#        Django 서버 터미널    patrol_run   (venv, python 3.10)
#
#    지금 터미널이 어느 쪽인지는 `pyver` 로 확인한다.

# 이 파일 위치에서 프로젝트 루트를 역산한다 — 클론 위치가 달라도 따라간다.
export PATROL_PRJ="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
export ISAACSIM_VENV="${ISAACSIM_VENV:-$HOME/isaacsim_venv}"
# 🔑 파이썬 버전을 박아 두지 않는다. Isaac 버전을 올리면 3.11→3.12 처럼 같이
#    바뀌는데, 박아 두면 이 경로만 조용히 틀려져 `isaac_ros` 가 아무 효과 없는
#    경로를 잡는다(오류는 안 난다). venv 에게 직접 물어본다.
export ISAACSIM_ROOT="$(echo "$ISAACSIM_VENV"/lib/python3.*/site-packages/isaacsim)"

# ------------------------------------------------------------
#  ROS 2 통신 설정
# ------------------------------------------------------------
export ROS_DISTRO=humble
# 🔑 2 로 못박는다 — `bridge/bridge_amr1.py:40` 이 import 전에
#    os.environ['ROS_DOMAIN_ID']='2' 로 직접 넣는다. 여기서 다른 값을 쓰면
#    브리지만 2번 도메인에 있고 Isaac 씬은 다른 도메인에 있어
#    `ros2 topic list` 에 **아무것도 안 보인다** (오류는 안 난다).
export ROS_DOMAIN_ID=2
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# NVIDIA Omniverse EULA 동의 — 없으면 Isaac Sim 이 대화형으로 물어보다 헤드리스에서 멈춘다.
# https://docs.omniverse.nvidia.com/platform/latest/common/NVIDIA_Omniverse_License_Agreement.html
export OMNI_KIT_ACCEPT_EULA=YES

# 중앙 서버 주소. 씬 스크립트가 프레임·좌표를 올릴 곳이다.
# 전부 한 대에서 도는 지금 구성에서는 localhost 로 둔다. 서버가 다른 PC 면
# bridge/*.py 의 SERVER 상수와 **같은 값**으로 바꿀 것.
export PATROL_SERVER="${PATROL_SERVER:-http://127.0.0.1:8000}"

# ------------------------------------------------------------
#  bridge/ 노드용 순수 ROS 소싱  (python 3.10)
# ------------------------------------------------------------
# 이 레포에는 colcon 패키지가 없다 — bridge/*.py 는 그냥 스크립트로 돈다.
# 그래서 오버레이 소싱 없이 /opt/ros/humble 만 잡으면 된다.
alias patrol_ros="source /opt/ros/humble/setup.bash; echo 'ROS 2 humble sourced (python 3.10) — ROS_DOMAIN_ID='\$ROS_DOMAIN_ID"

# ------------------------------------------------------------
#  아이작심용 ROS 소싱  (python 3.11 / ROS 를 소싱하지 말 것)
# ------------------------------------------------------------
# Isaac Sim 6.0 은 **python 3.12 용 humble rclpy 를 번들로 갖고 있다**
# (`.../humble/rclpy/*-py3.12.egg-info` 로 확인). 아래 두 경로만 잡으면
# rclpy / sensor_msgs / std_msgs / geometry_msgs / visualization_msgs 가 전부
# import 된다 — IsaacSim-ros_workspaces 도커 빌드는 필요 없다.
#
# 🚨 **5.1 에서 경로가 바뀌었다** (실측):
#       5.1   exts/isaacsim.ros2.bridge/humble/{lib,rclpy}
#       6.0   exts/isaacsim.ros2.core/humble/{lib,rclpy}
#    옛 경로를 그대로 쓰면 PYTHONPATH 에 **없는 디렉터리**가 들어가고, 오류
#    없이 그냥 무시된다 — 나중에 `import rclpy` 가 실패할 때까지 안 드러난다.
#
# 🔑 6.0 은 humble 과 jazzy 를 **둘 다** 번들로 갖고 있다. 우리는 팀 로봇
#    (bridge/*.py, AMR1/AMR2)이 Humble 이라 humble 을 쓴다. 바꾸려면:
#        ISAAC_ROS_DISTRO=jazzy isaac_ros
#    ⚠ 그래도 팀 로봇이 Humble 인 한 섞어 쓰면 안 된다 — 공식 지원 조합이 아니다.
export ISAAC_ROS_DISTRO="${ISAAC_ROS_DISTRO:-humble}"

# 🚨 LD_LIBRARY_PATH 는 **앞에 붙인다.** 뒤에 붙이면 셸에 이미 들어 있는
#    /opt/ros/humble/lib 이 먼저 잡혀, 3.12 rclpy 가 3.10 용
#    librcl_logging_spdlog.so 를 물고 `undefined symbol: ...spdlog...` 로 죽는다.
#    그러면 씬이 SystemExit 하고 Kit 이 세그폴트로 끝나 원인이 안 보인다.
#
# ⚠ cv_bridge 는 번들에 없다. Isaac 쪽에서 이미지를 낼 때는 cv2 로 직접
#   sensor_msgs/Image 를 채운다.
isaac_ros() {
    local base="$ISAACSIM_ROOT/exts/isaacsim.ros2.core/$ISAAC_ROS_DISTRO"
    if [ ! -d "$base/rclpy" ]; then
        echo "번들 rclpy 를 못 찾았다: $base/rclpy" >&2
        echo "  Isaac Sim 이 설치돼 있는지, 버전에 따라 경로가 또 바뀌지 않았는지 확인할 것" >&2
        return 1
    fi
    export LD_LIBRARY_PATH="$base/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export PYTHONPATH="$base/rclpy${PYTHONPATH:+:$PYTHONPATH}"
    echo "Isaac 번들 rclpy 경로 설정 완료 ($ISAAC_ROS_DISTRO / python 3.12)"
}

# 아이작심 실행 — headless 서버이므로 --no-window 가 필수다.
#   빼면 X 디스플레이가 없어 IWindowing 획득 실패로 즉시 죽는다.
#   오디오 장치가 없어 carb.audio 가 죽으므로 audio/enabled=false 도 필수다.
alias isaac="\$ISAACSIM_VENV/bin/isaacsim isaacsim.exp.base --no-window --/app/audio/enabled=false"

# 지금 터미널이 어느 쪽인지 확인
alias pyver="python3 \$PATROL_PRJ/sim/setup/pyver.py"

# Django 서버
alias patrol_run="\$PATROL_PRJ/venv/bin/python \$PATROL_PRJ/manage.py runserver 0.0.0.0:8000"

# ------------------------------------------------------------
#  WebRTC 스트리밍
# ------------------------------------------------------------
# TCP 49100 시그널링 / UDP 47998-48020 미디어 — 보안그룹에서 열어야 한다.
#
# 🚨 **Isaac Sim 6.0 은 5.1 과 설정 경로가 다르다** (실측:
#    apps/isaacsim.exp.full.streaming.kit):
#        확장       omni.kit.livestream.webrtc  →  omni.kit.livestream.app
#        포트       /app/livestream/port        →  .../primaryStream/signalPort
#        퍼블릭IP   .../publicEndpointAddress   →  .../primaryStream/publicIp
#    옛 경로에 써도 **오류가 안 난다** — carb 은 모르는 키도 그냥 받는다. 그래서
#    "설정은 했는데 기본 포트로 열리는" 증상이 된다.
#
#   isaacsim.exp.full.streaming 은 쓰지 말 것 — omni.services.livestream.session 의
#   quitOnSessionEnded=true 때문에 클라이언트가 안 붙으면 스스로 종료한다.
# ⚠ publicIp 를 하드코딩하면 안 된다. EIP 가 없으면 정지·시작마다 퍼블릭 IP 가
#   바뀌고, 옛 IP 가 박혀 있으면 시그널링은 붙는데 ICE 후보가 옛 주소라
#   **영상이 영영 안 뜬다**(검은 화면). 그래서 실행 시점에 IMDS 에서 읽는다.
#   EC2 가 아니거나 다른 주소로 강제하려면  ISAAC_PUB_IP=1.2.3.4 isaac_stream
isaac_pubip() {
    if [ -n "${ISAAC_PUB_IP:-}" ]; then echo "$ISAAC_PUB_IP"; return 0; fi
    local tok
    tok=$(curl -s -X PUT --max-time 2 "http://169.254.169.254/latest/api/token" \
              -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null)
    if [ -n "$tok" ]; then
        curl -s --max-time 2 -H "X-aws-ec2-metadata-token: $tok" \
             http://169.254.169.254/latest/meta-data/public-ipv4
    else
        curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4
    fi
}

# 빈 Isaac Sim 앱을 스트리밍으로 띄운다. 우리 씬을 보려면 isaac_python 을 쓸 것.
isaac_stream() {
    local ip; ip=$(isaac_pubip)
    if [ -z "$ip" ]; then
        echo "퍼블릭 IP 를 못 읽었다.  ISAAC_PUB_IP=<주소> isaac_stream  으로 지정할 것" >&2
        return 1
    fi
    echo "WebRTC 엔드포인트: $ip   (클라이언트 주소창에 이 IP 만 넣는다)"
    local pfx="/exts/omni.kit.livestream.app/primaryStream"
    "$ISAACSIM_VENV/bin/isaacsim" isaacsim.exp.base --no-window \
        --enable omni.kit.livestream.app \
        --/app/audio/enabled=false \
        --"$pfx"/publicIp="$ip" \
        --"$pfx"/signalPort=49100 \
        --"$pfx"/streamPort=47998 \
        --"$pfx"/streamType=webrtc \
        --/exts/omni.services.livestream.session/quitOnSessionEnded=false "$@"
}

# 아이작심용 Python 3.11
#
# PYTHONPATH 앞에 sim/tools/isaac_autostream 을 끼워, 파이썬이 본문을 실행하기
# 전에 거기 있는 sitecustomize.py 를 읽게 한다. 그 파일이 SimulationApp 을
# 가로채 WebRTC 스트리밍(GUI 포함)을 자동으로 켠다 — 씬 스크립트에 --stream 을
# 안 붙여도 된다.
#
#   isaac_python foo.py                  스트리밍 켜짐 (기본)
#   ISAAC_STREAM=0 isaac_python foo.py   끔. 배치로 산출물만 뽑을 때
#
# 별칭이 아니라 함수인 이유: PYTHONPATH 가 비어 있을 때 별칭으로 이어붙이면
# 끝에 ':' 이 남아 빈 항목(=현재 디렉터리)이 sys.path 에 들어간다.
# isaac_ros 가 세운 rclpy 경로도 이 방식이라야 안 지워진다.
# 옛 별칭이 살아 있는 터미널에서는 별칭이 함수보다 먼저 잡히므로 먼저 지운다.
unalias isaac_python 2>/dev/null

isaac_python() {
    PYTHONPATH="$PATROL_PRJ/sim/tools/isaac_autostream${PYTHONPATH:+:$PYTHONPATH}" \
        "$ISAACSIM_VENV/bin/python" "$@"
}

# ------------------------------------------------------------
#  로컬 NVMe 캐시
# ------------------------------------------------------------
# 셰이더 캐시·Kit 로그·크래시덤프를 인스턴스 스토어로 빼서 EBS(150GiB)를 아낀다.
#
# 🚨 stop → start 하면 NVMe 가 통째로 비워져 링크가 **깨진 링크**가 된다.
#    그래서 새 셸마다 조용히 고쳐 둔다 (비어 있어도 캐시라 아무 문제 없다).
#    reboot 은 살아남으므로 대개 아무 일도 안 일어난다.
if [ -f "$PATROL_PRJ/sim/setup/nvme_cache.sh" ]; then
    source "$PATROL_PRJ/sim/setup/nvme_cache.sh"
    patrol_cache_repair
    alias nvme_status="\$PATROL_PRJ/sim/setup/nvme_cache.sh status"
fi
