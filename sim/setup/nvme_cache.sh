#!/usr/bin/env bash
# 캐시·로그를 로컬 NVMe(인스턴스 스토어)로 빼서 EBS 를 아낀다.
#
#   source sim/setup/nvme_cache.sh    # 함수만 불러온다 (env.sh 가 이렇게 쓴다)
#   ./sim/setup/nvme_cache.sh         # 직접 실행하면 설정 + 상태 출력
#   ./sim/setup/nvme_cache.sh status  # 상태만
#
# ## 무엇을 어디에 두는가
#
#     EBS (150 GiB, 영구)      OS · Isaac Sim 본체 · 프로젝트 · Django venv
#     NVMe (419 GiB, 휘발)     셰이더 캐시 · Kit 로그 · 크래시덤프 · export
#
# g5.2xlarge 에 딸려 오는 인스턴스 스토어는 **공짜고 gp3 보다 빠르다.** 셰이더
# 캐시는 읽고 쓰는 양이 많아 오히려 여기가 낫다.
#
# 🚨 **stop → start 하면 NVMe 는 통째로 비워진다** (reboot 은 살아남는다).
#    그러면 여기서 건 심볼릭 링크가 전부 **깨진 링크**가 된다 — "없음"이 아니라
#    "가리키는 곳이 없는 링크"라서, Kit 이 로그를 못 써서 이상한 데서 실패한다.
#    그래서 `repair` 를 멱등하게 만들어 두고 `env.sh` 가 새 셸마다 조용히
#    부른다. 캐시는 어차피 다시 만들어지므로 비어 있어도 아무 문제 없다.

PATROL_NVME="${PATROL_NVME:-/opt/dlami/nvme}"
PATROL_CACHE="$PATROL_NVME/patrol_cache"

# 옮길 것들 —  "홈 기준 경로|NVMe 안 이름"
# ⚠ Isaac Sim 본체(~/isaacsim_venv)는 **여기 넣지 않는다.** stop/start 마다
#   20~30분 재설치가 되기 때문이다. 날아가도 되는 것만 넣는다.
_PATROL_CACHE_MAP=(
    ".cache/ov|ov"                      # Omniverse 캐시 (셰이더·자산)
    ".cache/nvidia|glcache"             # GL 셰이더 캐시
    ".nv|nv"                            # CUDA ComputeCache
    ".nvidia-omniverse|nvidia-omniverse" # Omniverse 로그
    ".local/share/ov|ov-data"           # Kit 데이터·크래시덤프
)

_pc_nvme_ok() {
    [ -d "$PATROL_NVME" ] && mountpoint -q "$PATROL_NVME" 2>/dev/null && [ -w "$PATROL_NVME" ]
}

# 링크 하나를 맞춘다. 이미 맞으면 아무것도 안 한다.
_pc_link() {
    local home_rel="$1" nvme_name="$2" verbose="${3:-0}"
    local link="$HOME/$home_rel"
    local target="$PATROL_CACHE/$nvme_name"

    mkdir -p "$target" 2>/dev/null || return 1
    mkdir -p "$(dirname "$link")" 2>/dev/null || return 1

    if [ -L "$link" ]; then
        # 이미 링크다. 목적지만 맞으면 끝 — 깨져 있어도 위 mkdir 이 살려 놨다.
        [ "$(readlink "$link")" = "$target" ] && return 0
        rm -f "$link"
    elif [ -d "$link" ]; then
        # 진짜 디렉터리가 있다. 비어 있으면 그냥 치우고, 내용이 있으면 옮긴다.
        if [ -z "$(ls -A "$link" 2>/dev/null)" ]; then
            rmdir "$link" 2>/dev/null || return 1
        else
            [ "$verbose" = "1" ] && echo "  · $home_rel 내용을 NVMe 로 옮기는 중 (캐시라 시간이 좀 걸릴 수 있다)"
            cp -a "$link/." "$target/" 2>/dev/null || return 1
            rm -rf "$link" || return 1
        fi
    elif [ -e "$link" ]; then
        return 1                        # 파일이 있다 — 건드리지 않는다
    fi

    ln -s "$target" "$link" 2>/dev/null || return 1
    [ "$verbose" = "1" ] && echo "  ✓ ~/$home_rel → $target"
    return 0
}

# 조용히 맞춘다. env.sh 가 새 셸마다 부른다 — 빨라야 한다.
patrol_cache_repair() {
    _pc_nvme_ok || return 0
    local e
    for e in "${_PATROL_CACHE_MAP[@]}"; do
        _pc_link "${e%%|*}" "${e##*|}" 0 || true
    done
}

patrol_cache_setup() {
    if ! _pc_nvme_ok; then
        echo "  ! 로컬 NVMe 를 못 찾았다: $PATROL_NVME"
        echo "    (g5 계열이 아니거나 마운트가 안 됐다. 그냥 EBS 를 쓴다 — 동작에는 지장 없다)"
        return 1
    fi
    echo "▶ 캐시를 로컬 NVMe 로 (EBS 절약)"
    local e
    for e in "${_PATROL_CACHE_MAP[@]}"; do
        _pc_link "${e%%|*}" "${e##*|}" 1 || echo "  ! ${e%%|*} 는 건너뜀"
    done
    # 산출물 둘 곳도 만들어 둔다 — USD export·녹화·데이터셋처럼 다시 만들 수
    # 있는 큰 파일은 EBS 가 아니라 여기 두는 게 맞다.
    mkdir -p "$PATROL_CACHE/exports" 2>/dev/null
    echo "  ✓ 산출물 두는 곳: $PATROL_CACHE/exports  (\$PATROL_SCRATCH)"
}

patrol_cache_status() {
    echo "NVMe        : $PATROL_NVME  $(_pc_nvme_ok && echo '(마운트됨)' || echo '❌ 없음')"
    if _pc_nvme_ok; then
        df -h "$PATROL_NVME" | tail -1 | awk '{printf "              %s 중 %s 사용, %s 여유\n", $2, $3, $4}'
    fi
    echo "EBS (루트)  : $(df -h / | tail -1 | awk '{printf "%s 중 %s 사용, %s 여유", $2, $3, $4}')"
    echo
    local e link
    for e in "${_PATROL_CACHE_MAP[@]}"; do
        link="$HOME/${e%%|*}"
        if [ -L "$link" ] && [ -d "$link" ]; then
            printf '  ✓ %-22s → %s\n' "~/${e%%|*}" "$(readlink "$link")"
        elif [ -L "$link" ]; then
            printf '  ❌ %-22s 깨진 링크 (stop/start 로 NVMe 가 비워졌다 — patrol_cache_repair)\n' "~/${e%%|*}"
        elif [ -d "$link" ]; then
            printf '  · %-22s EBS 에 그대로 있음\n' "~/${e%%|*}"
        else
            printf '  · %-22s 아직 없음\n' "~/${e%%|*}"
        fi
    done
}

# 산출물 두는 곳 — 씬 스크립트의 --save 기본값 등으로 쓴다.
export PATROL_SCRATCH="$PATROL_CACHE/exports"

# 직접 실행했을 때만 동작한다 (source 하면 함수만 올라간다).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-setup}" in
        setup) patrol_cache_setup; echo; patrol_cache_status ;;
        status) patrol_cache_status ;;
        repair) patrol_cache_repair; patrol_cache_status ;;
        *) echo "사용법: $0 [setup|status|repair]" >&2; exit 1 ;;
    esac
fi
