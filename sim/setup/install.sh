#!/usr/bin/env bash
#
# 주차 단속 시뮬레이션 환경 설치 — Isaac Sim + WebRTC 스트리밍.
#
#   ./sim/setup/install.sh              # driver 를 뺀 전부 (system → isaac → django → env → check)
#   ./sim/setup/install.sh check        # 지금 상태만 점검, 아무것도 안 고침
#   ./sim/setup/install.sh isaac        # 단계만 골라서
#   ./sim/setup/install.sh driver       # ⚠ GPU 드라이버 교체 + 재부팅 필요 (EC2 g5 전용, 별도 실행)
#
# 단계는 전부 멱등이다 — 이미 돼 있으면 건너뛴다. 중간에 끊겨도 다시 돌리면 된다.
#
# 🚨 **`driver` 를 먼저 돌리지 않으면 Isaac Sim 은 첫 프레임에서 반드시 죽는다.**
#    AWS DLAMI 기본 드라이버(595 계열)는 연산용(datacenter)이라 nvidia-drm.ko 가
#    없다. /dev/dri 에 렌더 노드(renderD128)가 안 생기고 librtx.scenedb.plugin.so
#    가 세그폴트한다. headless·RayTracedLighting·텍스처스트리밍off 등 설정으로는
#    우회되지 않는다 (pipe_repair_robot_IsaacSim/docs/SETUP_EC2.md 실측 기록).
#    `check` 단계가 이걸 먼저 알려 준다.
#
# 이 구성 (2026-08, EC2 g5.2xlarge / A10G):
#   Ubuntu 22.04.5 / ROS 2 Humble desktop / python 3.10(ROS·Django) + 3.12(Isaac)
#   Isaac Sim 6.0.1.0 (pip) / NVIDIA GRID 580.65.06
#
# ⚠ **Isaac 쪽 파이썬은 버전이 강제된다.** pypi.nvidia.com 의 휠은 버전마다
#   파이썬이 하나로 못박혀 있다 — 골라 쓸 수 없다:
#       isaacsim 4.x     → cp310
#       isaacsim 5.0/5.1 → cp311
#       isaacsim 6.0.x   → cp312   ← 지금 쓰는 것
#   ISAAC_VER 을 바꾸면 PY_ISAAC 도 같이 바꿔야 한다.
#
# 🚨 **여기 적힌 회피책 상당수는 Isaac Sim 5.1 에서 실측된 것이다**
#   (pipe_repair_robot_IsaacSim/docs/SETUP_EC2.md). 6.0 에서도 같은지는
#   확장 이름·번들 rclpy·experience 파일명이 바뀌었을 수 있어 **설치 후 실제로
#   확인해야 한다.** `check` 단계가 그 세 가지를 찍어 준다.
#
set -euo pipefail

# 이 파일 위치에서 프로젝트 루트를 역산한다 — 클론 위치가 달라도 따라간다.
PRJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ISAACSIM_VENV="${ISAACSIM_VENV:-$HOME/isaacsim_venv}"
DJANGO_VENV="${DJANGO_VENV:-$PRJ/venv}"
ISAAC_VER="6.0.1.0"
PY_ISAAC="3.12"          # ISAAC_VER 과 짝이다 — 위 표 참고
GRID_DRIVER="NVIDIA-Linux-x86_64-580.65.06-grid-aws.run"

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "root 로 돌리지 말 것. 일반 사용자로 실행하면 필요할 때만 sudo 를 부른다."

# ============================================================
#  system — apt 로 들어가는 것 전부
# ============================================================
step_system() {
    say "시스템 패키지 (apt)"
    sudo apt-get update -qq

    sudo apt-get install -y -qq \
        build-essential cmake git curl wget gnupg lsb-release \
        python3-pip python3-dev python3-venv software-properties-common

    # --- ROS 2 Humble ---------------------------------------------------
    # 키가 한 번 회전한 적이 있어 공식 배포판인 ros2-apt-source .deb 로 등록한다
    # (예전 문서의 `apt-key add` 방식은 만료된 키를 넣는다).
    if [ ! -d /opt/ros/humble ]; then
        if [ ! -f /etc/apt/sources.list.d/ros2.sources ]; then
            local ver codename
            ver=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
                  | grep -F '"tag_name"' | awk -F'"' '{print $4}')
            codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
            curl -fsSL -o /tmp/ros2-apt-source.deb \
                "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ver}/ros2-apt-source_${ver}.${codename}_all.deb"
            sudo apt-get install -y -qq /tmp/ros2-apt-source.deb
            sudo apt-get update -qq
        fi
        sudo apt-get install -y -qq ros-humble-desktop
    fi
    # desktop 에 딸려 오지만 명시해 둔다 — bridge/ 가 직접 import 하는 것들이다.
    #   bridge_webcam.py  → cv_bridge, visualization_msgs, sensor_msgs
    #   bridge_amr1.py    → std_msgs
    sudo apt-get install -y -qq \
        ros-humble-cv-bridge ros-humble-vision-opencv ros-humble-image-transport \
        ros-humble-visualization-msgs ros-humble-rmw-fastrtps-cpp python3-opencv
    ok "ROS 2 Humble"

    # --- Isaac Sim 용 python (deadsnakes) --------------------------------
    # 22.04 의 기본 파이썬은 3.10 이다. Isaac Sim 6.0 은 3.12 전용이라 따로 받는다.
    if ! command -v "python$PY_ISAAC" >/dev/null; then
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update -qq
    fi
    sudo apt-get install -y -qq \
        "python$PY_ISAAC" "python$PY_ISAAC-venv" "python$PY_ISAAC-dev"
    ok "python$PY_ISAAC ($("python$PY_ISAAC" --version 2>&1))"

    # --- Isaac Sim 렌더링에 필요한 라이브러리 ---------------------------
    # 창을 안 띄워도(--no-window) Vulkan 으로 렌더한다 — libvulkan1 과 ICD 가 있어야 한다.
    sudo apt-get install -y -qq \
        libvulkan1 vulkan-tools mesa-vulkan-drivers \
        libgl1 libglu1-mesa libxrandr2 libxinerama1 libxcursor1 libxi6 xvfb
    ok "Vulkan / GL 라이브러리"

    # bridge/ 는 시스템 python 3.10 으로 돈다 (venv 사용 불가 — rclpy 가 시스템에만 있다).
    python3 -m pip install -q --user requests
    ok "bridge 용 requests (시스템 python 3.10)"
}

# ============================================================
#  isaac — python 3.11 venv + Isaac Sim 5.1 (pip)
# ============================================================
step_isaac() {
    say "Isaac Sim $ISAAC_VER  →  $ISAACSIM_VENV"

    # 디스크가 모자라면 15GB 를 받다가 중간에 죽는다 — 먼저 본다.
    local free_gb; free_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')
    [ "$free_gb" -ge 25 ] || warn "여유 디스크 ${free_gb}GB — Isaac Sim 은 설치 후 약 20GB 를 쓴다"

    # venv 가 다른 파이썬으로 만들어져 있으면 휠이 안 맞는다 (cp312 휠은
    # 3.11 venv 에 안 깔린다 — "no matching distribution" 으로 끝난다).
    # ISAAC_VER 을 바꾼 뒤 다시 돌릴 때 여기서 걸리므로 먼저 확인한다.
    if [ -x "$ISAACSIM_VENV/bin/python" ]; then
        local have; have=$("$ISAACSIM_VENV/bin/python" -c 'import sys; print("%d.%d"%sys.version_info[:2])')
        if [ "$have" != "$PY_ISAAC" ]; then
            die "$ISAACSIM_VENV 는 python $have 로 만들어져 있는데 Isaac $ISAAC_VER 은 $PY_ISAAC 를 쓴다.
  지우고 다시 만들 것:   rm -rf $ISAACSIM_VENV && ./sim/setup/install.sh isaac"
        fi
    fi

    [ -d "$ISAACSIM_VENV" ] || "python$PY_ISAAC" -m venv "$ISAACSIM_VENV"
    "$ISAACSIM_VENV/bin/python" -m pip install -q --upgrade pip setuptools

    if "$ISAACSIM_VENV/bin/pip" show isaacsim >/dev/null 2>&1; then
        ok "이미 설치됨 ($("$ISAACSIM_VENV/bin/pip" show isaacsim | awk '/^Version/{print $2}'))"
    else
        # ~15 GB 를 내려받는다. pypi.nvidia.com 에만 있는 휠이다.
        warn "약 15GB 를 내려받는다 — 회선에 따라 20~40분"
        # 🚨 `--no-cache-dir` 을 빼면 안 된다. pip 은 받은 휠을 ~/.cache/pip 에
        #    그대로 남기므로 **다운로드 15GB + 설치 20GB = 35GB** 를 먹는다.
        #    DLAMI 는 CUDA 등으로 이미 50GB 넘게 차 있어 그대로는 디스크가
        #    터진다 — 그러면 설치가 중간에 깨져 venv 를 지우고 다시 받아야 한다.
        "$ISAACSIM_VENV/bin/pip" install --no-cache-dir "isaacsim[all]==$ISAAC_VER" \
            --extra-index-url https://pypi.nvidia.com
        ok "Isaac Sim 설치 완료"
    fi

    # 🚨 **`isaacsim[all]` 만으로는 앱이 안 뜬다** (6.0.1.0 실측). 아래 넷이
    #    빠져 있고, 없으면 확장 의존성 해결에 실패해 **즉시 종료**한다:
    #        [Error] No versions of isaacsim.anim.robot.schema that satisfies:
    #                isaacsim.exp.base-6.0.1 depends on ... (none found)
    #        [Error] Exiting app because of dependency solver failure...
    #    로그만 보면 GPU/드라이버 문제로 착각하기 쉽다 — 렌더까지 가지도 못한다.
    #
    #    extscache-* 는 확장 캐시다(kit 하나가 5.9GB). 이게 있어야 레지스트리
    #    동기화 없이 로컬에서 의존성이 풀린다. `omni.kit.livestream.app`
    #    (WebRTC 백엔드)도 여기 들어 있다.
    local extras=(
        isaacsim-robot-schema
        isaacsim-extscache-kit
        isaacsim-extscache-kit-sdk
        isaacsim-extscache-physics
    )
    local missing=()
    local p
    for p in "${extras[@]}"; do
        "$ISAACSIM_VENV/bin/pip" show "$p" >/dev/null 2>&1 || missing+=("$p==$ISAAC_VER")
    done
    if [ ${#missing[@]} -eq 0 ]; then
        ok "확장 캐시 4종 이미 설치됨"
    else
        warn "확장 캐시를 받는다 (약 10GB) — 이게 없으면 앱이 안 뜬다"
        "$ISAACSIM_VENV/bin/pip" install --no-cache-dir "${missing[@]}" \
            --extra-index-url https://pypi.nvidia.com
        ok "확장 캐시 설치 완료"
    fi

    # 씬 스크립트가 서버로 프레임을 올릴 때 쓴다. Isaac 쪽 3.11 에 있어야 한다.
    # (opencv-headless 는 isaacsim 의존성으로 이미 들어온다)
    "$ISAACSIM_VENV/bin/pip" install -q requests
    ok "씬 스크립트용 requests (Isaac python 3.11)"
}

# ============================================================
#  django — 중앙 서버 venv (python 3.10)
# ============================================================
step_django() {
    say "Django 서버 venv  →  $DJANGO_VENV"

    [ -d "$DJANGO_VENV" ] || python3 -m venv "$DJANGO_VENV"
    "$DJANGO_VENV/bin/python" -m pip install -q --upgrade pip
    "$DJANGO_VENV/bin/pip" install -q -r "$PRJ/requirements.txt"
    ok "requirements.txt 설치 완료"

    if [ -f "$PRJ/.env" ]; then
        ok ".env 있음"
    else
        warn ".env 가 없다 — 서버가 Supabase 에 못 붙는다. SETUP.txt 3단계 참고"
        warn "  (.env 는 .gitignore 대상이라 클론만으로는 안 생긴다. 팀원에게 받을 것)"
    fi
}

# ============================================================
#  env — ~/.bashrc 연결
# ============================================================
step_env() {
    say "셸 환경"

    local marker="# Alley_Park_Patrol sim 환경 (sim/setup/install.sh 가 추가)"
    if grep -qF "$marker" "$HOME/.bashrc" 2>/dev/null; then
        ok "~/.bashrc 에 이미 연결돼 있다"
    else
        cp "$HOME/.bashrc" "$HOME/.bashrc.bak.$(date +%Y%m%d_%H%M%S)"
        {
            echo ""
            echo "$marker"
            echo "[ -f \"$PRJ/sim/setup/env.sh\" ] && source \"$PRJ/sim/setup/env.sh\""
        } >> "$HOME/.bashrc"
        ok "~/.bashrc 에 추가 (원본은 ~/.bashrc.bak.* 로 백업)"
    fi
}

# ============================================================
#  driver — NVIDIA GRID 드라이버 (EC2 g5 전용, 재부팅 필요)
# ============================================================
step_driver() {
    say "NVIDIA GRID 드라이버 교체"
    cat <<'EOF'
  왜 필요한가: AWS DLAMI 기본 드라이버(595 계열)는 연산용(datacenter)이라
  nvidia-drm.ko 가 없다. /dev/dri 에 NVIDIA 렌더 노드가 안 생기고,
  Isaac Sim 이 첫 프레임에서 librtx.scenedb.plugin.so 세그폴트로 **반드시** 죽는다.
  headless·RayTracedLighting·텍스처스트리밍off 등 설정으로는 우회되지 않는다.

  이 단계는 되돌리기 어렵다: 드라이버를 교체하고 재부팅해야 한다.
  부작용 — nvidia-fabricmanager / libnvidia-nscq / efa-nv-peermem / nvidia_fs /
  gdrdrv 는 기존 버전에 맞춰져 있어 더 이상 안 맞는다 (이 프로젝트는 쓰지 않는다).
EOF
    if [ -e /dev/dri/renderD128 ] && lsmod | grep -q '^nvidia_drm'; then
        ok "이미 nvidia_drm 로드 + /dev/dri/renderD128 있음 — 교체 불필요"
        return 0
    fi
    read -r -p $'\n  계속할까? (yes 입력) ' ans
    [ "$ans" = "yes" ] || { warn "건너뜀"; return 0; }

    # 교체 전 상태를 남긴다 — 되돌릴 때 필요하다.
    nvidia-smi --query-gpu=driver_version --format=csv,noheader \
        > "$HOME/driver_rollback_info.txt" 2>/dev/null || true

    # 버킷은 익명 접근이 된다 (IAM 자격증명 불필요).
    aws s3 cp --no-sign-request "s3://ec2-linux-nvidia-drivers/grid-19.0/$GRID_DRIVER" /tmp/
    sudo sh "/tmp/$GRID_DRIVER" --silent --dkms --no-questions --accept-license

    # 재부팅해도 유지되도록 못박는다.
    echo 'options nvidia-drm modeset=1' | sudo tee /etc/modprobe.d/nvidia-drm-modeset.conf >/dev/null
    printf 'nvidia\nnvidia-modeset\nnvidia-drm\nnvidia-uvm\n' | sudo tee /etc/modules-load.d/nvidia.conf >/dev/null
    # 렌더 노드 접근 권한 — 재로그인해야 반영된다.
    sudo usermod -aG render "$USER"

    warn "재부팅 필요:  sudo reboot   (그 뒤 /dev/dri/renderD128 이 생겼는지 확인)"
}

# ============================================================
#  check — 점검만 한다
# ============================================================
step_check() {
    say "점검"
    printf '  %-34s %s\n' "OS"        "$(lsb_release -ds 2>/dev/null || echo '?')"
    printf '  %-34s %s\n' "GPU"       "$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo '없음')"
    printf '  %-34s %s\n' "ROS 2"     "$([ -d /opt/ros/humble ] && echo humble || echo '없음')"
    printf '  %-34s %s\n' "python3 (ROS·Django)" "$(python3 --version 2>&1)"
    printf '  %-34s %s\n' "python$PY_ISAAC (Isaac)" "$("python$PY_ISAAC" --version 2>&1 || echo '없음')"
    printf '  %-34s %s\n' "Isaac Sim" "$("$ISAACSIM_VENV/bin/pip" show isaacsim 2>/dev/null | awk '/^Version/{print $2}' || echo '없음')"
    printf '  %-34s %s\n' "Django venv" "$([ -x "$DJANGO_VENV/bin/python" ] && echo 있음 || echo '없음 ← django 단계 필요')"
    printf '  %-34s %s\n' ".env"      "$([ -f "$PRJ/.env" ] && echo 있음 || echo '없음 ← 서버가 DB 에 못 붙는다')"

    # ── Isaac 6.0 에서 실제로 확인해야 하는 세 가지 ──────────────
    # 아래 이름들은 전부 5.1 기준 기록에서 온 것이다. 6.0 에서 바뀌었으면
    # 씬은 뜨는데 스트리밍이 안 되거나, rclpy import 가 실패한다.
    local root="$ISAACSIM_VENV/lib/python$PY_ISAAC/site-packages/isaacsim"
    if [ -d "$root" ]; then
        echo
        say "Isaac $ISAAC_VER 실측 (5.1 기록과 다를 수 있는 것들)"
        # ① 스트리밍용 experience — livestream.py 의 EXPERIENCE 가 이 이름을 쓴다
        printf '  %-34s %s\n' "apps/isaacsim.exp.base.kit" \
            "$([ -f "$root/apps/isaacsim.exp.base.kit" ] && echo 있음 || echo '❌ 없음 — 아래 목록에서 고를 것')"

        # ② 스트리밍 확장. 6.0 은 이름이 omni.kit.livestream.app 으로 바뀌었고,
        #    pip 패키지에 **들어 있지 않다** — 첫 실행 때 레지스트리에서 받아
        #    extscache/ 에 푼다. 그래서 "아직 안 받음" 이 정상 상태다.
        local ext_dir; ext_dir=$(ls -d "$root"/extscache/omni.kit.livestream.app* 2>/dev/null | head -1 || true)
        printf '  %-34s %s\n' "omni.kit.livestream.app" \
            "${ext_dir:-아직 안 받음 (첫 실행 때 레지스트리에서 받는다 — 정상)}"

        # ③ 번들 rclpy — 이게 있어야 Isaac 쪽에서 ROS 토픽을 직접 낼 수 있다.
        #    🚨 5.1 은 isaacsim.ros2.bridge/, 6.0 은 isaacsim.ros2.core/ 다.
        local d
        for d in "$root"/exts/isaacsim.ros2.core/*/rclpy; do
            [ -d "$d" ] || continue
            printf '  %-34s %s\n' "번들 rclpy ($(basename "$(dirname "$d")"))" "있음"
        done
        [ -d "$root/exts/isaacsim.ros2.core" ] || \
            printf '  %-34s %s\n' "번들 rclpy" "❌ 없음 — Isaac 쪽에서 rclpy 직접 발행 불가"

        echo
        echo "  사용 가능한 experience:"
        ls "$root/apps/" 2>/dev/null | grep -E '\.kit$' | sed 's/^/    /' || echo "    (못 읽음)"
    fi

    echo
    # ℹ️ 파이프 프로젝트(Isaac 5.1)는 이 둘이 없으면 **반드시 세그폴트**한다고
    #    기록하고 있다. 그런데 **6.0.1.0 에서는 둘 다 없어도 정상 렌더된다**
    #    (드라이버 595.91.07 / A10G 에서 20프레임 렌더 + 캡처까지 실측 확인).
    #    그래서 실패가 아니라 참고 정보로 찍는다. 혹시 다른 드라이버 조합에서
    #    세그폴트가 나면 그때 `driver` 단계를 쓴다.
    local drm_ok=1
    printf '  %-34s %s\n' "/dev/dri/renderD128" \
        "$([ -e /dev/dri/renderD128 ] && echo 있음 || { drm_ok=0; echo '없음'; })"
    printf '  %-34s %s\n' "nvidia_drm 모듈" \
        "$(lsmod | grep -q '^nvidia_drm' && echo 로드됨 || { drm_ok=0; echo '미로드'; })"
    if [ "$drm_ok" = "0" ]; then
        echo "     ↑ 6.0 은 이 상태로도 렌더된다 (실측). 만약 첫 프레임에서"
        echo "       librtx.scenedb 세그폴트가 나면 그때  install.sh driver  를 쓸 것"
    fi
}

# ============================================================
#  실행
# ============================================================
STEPS=("$@")
[ ${#STEPS[@]} -gt 0 ] || STEPS=(system isaac django env check)

for s in "${STEPS[@]}"; do
    case "$s" in
        system|isaac|django|env|driver|check) "step_$s" ;;
        *) die "모르는 단계: $s   (system isaac django env driver check)" ;;
    esac
done

say "끝. 새 터미널을 열거나  source ~/.bashrc  후:"
cat <<EOF
    patrol_ros     bridge/ 노드 터미널 (python 3.10)
    isaac_ros      Isaac Sim 터미널    (python $PY_ISAAC) — 여기서 patrol_ros 를 쓰면 안 된다
    pyver          지금 터미널이 어느 쪽인지 확인
    nvme_status    캐시가 로컬 NVMe 로 가 있는지 확인
EOF
