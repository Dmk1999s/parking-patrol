# 진행 기록 — Isaac Sim 주차 단속 시뮬 (2026-08-14)

다음 세션에서 이 파일부터 읽는다. 상세 원리·함정은 `sim/README.md` 에 있고,
여기는 **무엇이 끝났고 무엇이 남았는지**만 적는다.

---

## ✅ 오늘 끝낸 것

### 1. 물리 + 라이다 + 차동구동 (검증 완료)

- `sim/scenes/patrol.py` — 물리가 도는 순찰 씬 (`parking_lot.py` 는 그림 전용)
- `sim/scenes/ros_bridge.py` — ROS 2 배선 전부:
  `/clock` · `/amr{1,2}/scan`(3600점·20 m) · `/amr{1,2}/odom` · `/tf` ·
  `/amr{1,2}/cmd_vel`(구독) · 웹캠 Image 발행
- Humble(3.10) 쪽에서 전 토픽 수신 + `/amr1/cmd_vel` 로 실주행 확인
- odom 은 실측으로 **월드 좌표와 정확히 일치** (odom + AMR 시작좌표 = 월드)

자동으로 처리되지만 알아야 하는 함정 3개 (상세: README "물리 + 라이다" 절):

| 함정 | 처리 위치 |
|---|---|
| ROS 브리지가 LD_LIBRARY_PATH 없으면 **조용히** 죽음 | `pyver.ensure_ros2_libs()` — 자동 재실행 |
| TB3 자산 캐스터가 바닥 4 mm 관통 → 바퀴 헛돎 | `lot._fix_tb3_physics()` |
| 실린더 콜라이더 접촉이 위치 따라 실패 | `patrol.py` 의 `collisionApproximateCylinders` |

### 2. SLAM 파이프라인 (구성 완료, **지도는 다시 만들어야 함**)

- `sim/slam/slam_params.yaml` — slam_toolbox 설정.
  🚨 **스캔 매칭 꺼 둠** — RTX 라이다가 회전 중 스캔이 왜곡돼(각속도×0.1 s
  만큼 밀림) 매칭이 지도를 오염시킨다. 시뮬 odom 이 참값이라 끄는 게 정답.
  **실물 이관 시 반드시 되돌릴 것** (yaml 주석 참고).
- `sim/slam/explore_amr1.py` — odom 폐루프 웨이포인트 순찰 (Nav2 전 단계).
  `--wp "x,y;x,y"` 로 임시 경로, `--speed` 로 속도, `--exit-on-done`.
- `sim/slam/map_snapshot.py` — `/map` → PNG (20초마다)
- `sim/slam/expected_map.py` — **정답 지도** 생성 (Isaac 불필요).
  SLAM 결과가 이걸 닮아야 한다. 주차선은 라이다에 안 잡히므로 지도에 없는
  게 정상이고, 주차장 가장자리는 벽이 없어 경계선도 없는 게 정상.
- `sim/slam/rviz_web.sh` — **RViz 를 브라우저로** (Xvfb + noVNC, 포트 6080)

### 3. 웹 모니터링 (전부 동작 확인)

| 화면 | 주소 | 보안그룹 |
|---|---|---|
| RViz (지도·스캔·TF) | `http://<IP>:6080/vnc.html` → Connect | TCP 6080 |
| 웹캠 영상 (MJPEG) | `http://<IP>:8000/api/webcam1/stream/` | TCP 8000 |
| 팀 대시보드 | `http://<IP>:8000/monitor/` (user/password) | TCP 8000 |
| Isaac 씬 3D | WebRTC 클라이언트에 IP만 | 49100/47998-48020 |

- 씬 웹캠 → `webcam_images/webcam1/detections` → `bridge_webcam.py` →
  Django. **서버 코드는 안 고침** (기존 규약에 토픽만 맞춤).
- Django 는 팀 `.env` 없이도 뜨게 **sqlite 폴백** 추가 (`config/settings.py`).
  팀 Supabase `.env` 받으면 자동 전환.
- `bridge/*.py` 서버 주소는 `PATROL_SERVER` 환경변수로 덮어씀 (기본은 팀 IP).

---

## ⏸ 중단 지점 — 왜 지도를 다시 만들어야 하나

순찰 노드를 SIGTERM 으로 껐을 때 정지 명령이 안 나가는 버그가 있었다.
PhysX 는 마지막 속도 명령을 유지하므로 로봇이 **무인 주행**으로 주차 블록 안
차량 사이에 끼었고, 그 상태의 스캔이 지도에 섞였다. 버그는 고쳤고
(SIGTERM/SIGINT/finally 모두에서 정지 발행) 로봇은 후진으로 구출해 통로에
세워 뒀다. **지도는 오염됐으니 다음 세션에서 처음부터 다시 만든다.**

속도 개선도 반영해 뒀다:
- 순찰 기본 속도 0.2 → **0.35 m/s** (`--speed` 로 조절. 실물은 0.2 이하)
- DiffDrive 상한 0.22 → 0.6 (상한일 뿐, 실제 속도는 명령하는 쪽이 정함)
- 회전은 0.5 rad/s 유지 — 빠르면 라이다 스캔이 왜곡돼 지도가 망가진다
- 🔑 시뮬 자체가 느린 주범은 **WebRTC 스트리밍**(rtf ~0.3). 다음 매핑은
  `ISAAC_STREAM=0` 로 띄우고 웹캠 브라우저(8000)로 보는 걸 권장 — 웹캠
  발행은 스트리밍과 무관하게 나간다.

---

## ▶ 다음 세션 시작 절차 (SLAM 지도 처음부터)

```bash
# 0. 지금 떠 있는 것: Django(8000) · RViz웹(6080). 죽었으면:
#    (Django)  cd ~/dongmin_project/ros_ws/Alley_Park_Patrol_system-monitor
#              venv/bin/python manage.py runserver 0.0.0.0:8000 --noreload &
#    (RViz웹)  ./sim/slam/rviz_web.sh

# 1. 씬 — 스트리밍 끄고 빠르게 (화면은 8000 웹캠으로 본다)
ISAAC_STREAM=0 PATROL_PRJ="$PWD" ROS_DOMAIN_ID=2 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  OMNI_KIT_ACCEPT_EULA=YES PYTHONUNBUFFERED=1 \
  ~/isaacsim_venv/bin/python sim/scenes/patrol.py --seed 7 --robots amr1 --report 10 &

# 2~5. ROS 쪽 (patrol_ros 소싱된 터미널, ROS_DOMAIN_ID=2)
python3 bridge/bridge_webcam.py &          # PATROL_SERVER=http://127.0.0.1:8000
ros2 run slam_toolbox async_slam_toolbox_node \
    --ros-args --params-file sim/slam/slam_params.yaml &
python3 sim/slam/map_snapshot.py --out /tmp/parking_map &
python3 sim/slam/explore_amr1.py           # 완주 후:

# 6. 지도 저장 (Nav2 형식 pgm+yaml)
ros2 run nav2_map_server map_saver_cli -f sim/slam/maps/parking \
    --ros-args -p use_sim_time:=true

# 7. 검증 — 정답과 눈으로 대조
python3 sim/slam/expected_map.py --seed 7 --out /tmp/expected.png
```

⚠ seed 를 바꾸면 차량 배치가 바뀌어 지도도 새로 떠야 한다. 지도·시연·DB
정답을 맞추려면 **seed 7 고정**을 권장.

---

## 📋 남은 것 (시나리오 순서)

1. **SLAM 지도 완성** — 위 절차 그대로. 순찰 ~5분(0.35 m/s) + 저장
2. **웹캠 차량탐지 → 좌표 발행** — 오버헤드 프레임에서 차량 픽셀 → 월드
   좌표 변환 후 `webcam_objects/map_detections`(MarkerArray) 발행.
   `bridge_webcam.py` 가 받아서 `POST /api/parking/` (이미 구현돼 있음).
   웹캠은 수직 정사영이라 변환은 선형 (카메라 위치 (14, 5.5, 28), 화각 69°).
3. **Nav2** — 저장한 지도 + `/amr1/odom`·`/tf` 위에서 기동. AMR1 이
   `webtoamr_xy`(bridge_amr1.py 발행)를 받아 목표로 이동.
   `lot.approach_pose()` 가 주는 관측 자세가 곧 목표 pose.
4. **OpenCV 구역/차종 판별** — HSV 실측 임계값은 README "구역 색" 절.
   경차=차폭(1.55 vs 1.80), 전기차=파란 번호판, 장애인=휠체어 표시+DB 조회.
5. **OCR 노드 통합** — tesseract 검증 완료(README). OcrCam 프레임 →
   번호판 텍스트 → `POST /api/vehicle/`.
6. **AMR2 시나리오** — AMR1 복귀 후 출동, `GET /api/vehicle/next/` →
   번호판 재확인 → `POST /api/vehicle/verify/`.
   (씬 쪽은 `--robots both` 로 AMR2 배선을 켠다)
7. **팀 `.env`** — 받으면 Supabase 로 자동 전환. 그 전까지는 sqlite.

## ⚠ 실물 이관 시 되돌릴 것 모음

| 항목 | 시뮬 값 | 실물 |
|---|---|---|
| slam_toolbox 스캔 매칭 | off | **on** + loop closing |
| 라이다 사거리 | 20 m | 3.5 m (LDS-01) — SLAM 파라미터 재조정 |
| 순찰/Nav2 속도 | 0.35 m/s | ≤ 0.2 m/s |
| DiffDrive 상한 | 0.6 | 0.22 |
