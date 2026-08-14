#!/usr/bin/env bash
# RViz 를 브라우저로 — 헤드리스 EC2 에서 진짜 RViz2 를 띄워 noVNC 로 내보낸다.
#
#     ./sim/slam/rviz_web.sh          # 띄우기
#     ./sim/slam/rviz_web.sh stop     # 전부 내리기
#
# 구조:   Xvfb(가상 디스플레이 :10) ← rviz2 가 여기에 그린다
#         x11vnc                     ← 그 화면을 VNC(5900, localhost만)로
#         websockify + noVNC(6080)   ← VNC 를 브라우저용 websocket 으로
#
# 접속:   http://<EC2 퍼블릭IP>:6080/vnc.html   → [Connect]
#         ⚠ 보안그룹에 TCP 6080 을 열어야 한다. 5900 은 localhost 전용이라
#           열 필요도, 열어서도 안 된다.
#
# 🚨 GPU 는 Isaac Sim 이 쓰고 있다. rviz2 는 소프트웨어 렌더링(llvmpipe)으로
#    돌린다 (LIBGL_ALWAYS_SOFTWARE=1). 지도+스캔 정도의 2D 표시는 CPU 로
#    충분하고, GPU 를 뺏어 시뮬을 느리게 만들지 않는다.
#
# 🚨 use_sim_time 필수 — 씬이 /clock 을 발행하므로 rviz 도 그 시계를 따라야
#    TF 보간이 맞는다. 빼먹으면 "Frame does not exist" 류가 계속 뜬다.
# set -u 를 쓰지 않는다 — /opt/ros/humble/setup.bash 가 미정의 변수를 만져
# "AMENT_TRACE_SETUP_FILES: unbound variable" 로 죽는다.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISP=:10
LOGDIR="${RVIZ_WEB_LOGDIR:-/tmp}"

stop_all() {
    pkill -f "Xvfb $DISP" 2>/dev/null
    pkill -f "x11vnc -display $DISP" 2>/dev/null
    pkill -f "websockify.*6080" 2>/dev/null
    pkill -f "rviz2 -d $HERE/patrol.rviz" 2>/dev/null
    echo "내렸다"
}

if [ "${1:-}" = "stop" ]; then stop_all; exit 0; fi

command -v rviz2 >/dev/null 2>&1 || source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-2}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

pgrep -f "Xvfb $DISP" >/dev/null || {
    Xvfb $DISP -screen 0 1600x900x24 > "$LOGDIR/xvfb.log" 2>&1 &
    sleep 1
}
DISPLAY=$DISP LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb \
    rviz2 -d "$HERE/patrol.rviz" --ros-args -p use_sim_time:=true \
    > "$LOGDIR/rviz.log" 2>&1 &
pgrep -f "x11vnc -display $DISP" >/dev/null || {
    # -localhost: VNC(5900)는 밖에 안 연다. 밖으로 나가는 건 noVNC(6080)뿐.
    x11vnc -display $DISP -forever -shared -nopw -localhost -quiet \
        > "$LOGDIR/x11vnc.log" 2>&1 &
    sleep 1
}
pgrep -f "websockify.*6080" >/dev/null || {
    websockify --web=/usr/share/novnc 6080 localhost:5900 \
        > "$LOGDIR/novnc.log" 2>&1 &
}
sleep 2
echo "RViz(웹) 준비 완료:  http://$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4 || echo '<EC2-IP>'):6080/vnc.html"
echo "보안그룹에 TCP 6080 이 열려 있어야 한다"
