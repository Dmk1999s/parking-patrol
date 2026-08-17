# 진행 기록 — Isaac Sim 주차 단속 시뮬 (2026-08-17 세션 3 종료 시점)

다음 세션에서 이 파일부터 읽는다. 세션별 상세 기록은 `sim/WORKLOG.md`,
원리·함정은 `sim/README.md` 에 있다. 여기는 **무엇이 끝났고, 다음에
무엇을 어떻게 시작하는지**만 적는다.

---

## ✅ 끝난 것 (요약 — 상세는 WORKLOG)

1. **물리 + 라이다 + 차동구동** — 씬·ROS 배선 전부 검증 완료.
   odom = 월드 좌표 (시작좌표 오프셋만 더하면 됨).
2. **SLAM 지도 완성** — **`sim/slam/maps/parking.pgm/.yaml`** (Nav2 형식,
   seed 7). `expected_map.py --seed 7` 과 대조 검증 끝. 세션 3 에서 로봇
   유령 블롭 2개(AMR1 시작·AMR2 주차 위치)를 지웠다 — **지도를 다시 만들면
   같은 정리가 또 필요하다** (WORKLOG 세션 3).
3. **웹 모니터링** — RViz 웹(6080) · 웹캠 MJPEG(8000) · 대시보드(8000).
4. **웹캠 차량탐지 → DB** — `sim/vision/webcam_detect.py`.
   seed 7 에서 11/11 대 탐지·오탐 0, `parking_events` 11건(DETECTED) 검증.
5. **Nav2 + AMR1 자율 출동** — `sim/nav2/` (params · launch · `amr1_nav.py`).
   AMCL 없이 정적 TF `map→amr1/odom`(항등)로 정합 (map 프레임 = odom 프레임).
   `--all` 로 DB 11건 순방문 **9/11 도착 검증** — 나머지 2건은 벽쪽 세로주차
   기하 한계(아래 공백). 서버·브리지 코드는 안 고침.

## ⚠ 알려진 공백

- 웹캠 탐지의 **차량 이탈 처리 없음**: DELETE API 호출 미구현이라
  차가 떠나도 이벤트가 남고, 같은 자리 재탐지도 안 된다 (노드 `confirmed`
  + 브리지 좌표 캐시). 고정 배치 시연에는 지장 없음.
- **벽쪽 세로주차 2·3번 차는 접근 불가**: 차간 0.5 m 라 "번호판 남쪽 2 m"
  관측점이 이웃 차 내부에 떨어진다 (id 기준 남단 1대만 도달 가능).
  layout 은 가운데만 `blocked` 로 두지만 실제로는 3번도 안 된다 —
  벽쪽은 남단 1대만 단속하는 것으로 하든지 obs 정책을 바꾸든지 팀 결정 필요.

---

## ▶ 다음 세션 시작 절차

인스턴스 재시작 후엔 아무것도 안 떠 있다. 순서대로:

```bash
cd ~/dongmin_project/ros_ws/Alley_Park_Patrol_system-monitor

# 1. Django (sqlite 폴백) + RViz 웹
venv/bin/python manage.py runserver 0.0.0.0:8000 --noreload &
./sim/slam/rviz_web.sh

# 2. 씬 — 스트리밍 끄고 (화면은 8000 웹캠 MJPEG 로 본다). 로딩 수 분.
ISAAC_STREAM=0 PATROL_PRJ="$PWD" ROS_DOMAIN_ID=2 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  OMNI_KIT_ACCEPT_EULA=YES PYTHONUNBUFFERED=1 \
  ~/isaacsim_venv/bin/python sim/scenes/patrol.py --seed 7 --robots amr1 --report 10 &
# AMR2 시나리오까지 가면 --robots both

# 3. ROS 쪽 (source /opt/ros/humble/setup.bash, ROS_DOMAIN_ID=2)
PATROL_SERVER=http://127.0.0.1:8000 python3 bridge/bridge_webcam.py &
python3 sim/vision/webcam_detect.py &        # → DB 에 DETECTED 11건 자동 생성

# 4. Nav2 (씬이 뜬 다음 — /clock·/tf 필요)
ros2 launch sim/nav2/nav2_amr1.launch.py &

# 5. AMR1 출동 (검증은 --all, 시나리오는 무옵션 = next 1건)
PATROL_SERVER=http://127.0.0.1:8000 python3 sim/nav2/amr1_nav.py --all
```

- 이전 세션 이벤트가 DB 에 남아 있으면 `/api/parking/list/` 로 id 확인 후
  `DELETE /api/parking/<id>/delete/` 로 비우고 시작한다 (탐지 노드가 다시
  채운다). 브리지·탐지 노드를 재시작해야 중복 캐시도 초기화된다.
- slam_toolbox·map_snapshot 은 **지도를 다시 만들 때만** 필요하다.
- ⚠ 노드를 pkill 로 죽일 때 패턴이 자기 셸 명령줄과 매칭되지 않게 할 것
  (`pkill -f "amr1_nav[.]py"` 처럼 브래킷을 끼운다).

⚠ seed 7 고정 — 바꾸면 차량 배치·지도·DB 정답이 전부 갈린다.

---

## 📋 남은 것 (시나리오 순서)

1. **OpenCV 구역/차종 판별** — AMR1 도착 후 OcrCam 프레임으로 주차선 색
   판별 (HSV 실측 임계값은 README "구역 색" 절). 경차=차폭(1.55 vs 1.80),
   전기차=파란 번호판, 장애인=휠체어 표시+DB 조회.
   → `PATCH /api/parking/<id>/zone/`
2. **OCR 노드 통합** — tesseract 검증 완료(README). OcrCam 프레임 →
   번호판 텍스트 → `POST /api/vehicle/` (status→SCANNED, amr_vehicle_x/y 포함).
   1·2 가 붙으면 `amr1_nav.py` 의 무옵션 모드가 자연히 전 이벤트를 돈다
   (SCANNED 로 바뀌면 `/next/` 가 다음 건을 준다).
3. **AMR2 시나리오** — AMR1 복귀 후 출동, `GET /api/vehicle/next/` →
   번호판 재확인 → `POST /api/vehicle/verify/`. (씬은 `--robots both`,
   Nav2 는 amr2 용 파라미터 복제 필요 — 프레임·토픽 접두사만 다르다)
4. **웹캠 이탈 처리** — 점유 해제 시 확정 취소 + 브리지에 DELETE 경로 추가.
5. **벽쪽 세로주차 정책** — 남단 1대만 단속할지, obs 좌표 정책을 바꿀지
   (위 공백란). 팀과 논의.
6. **팀 `.env`** — 받으면 Supabase 로 자동 전환. 그 전까지는 sqlite.

## ⚠ 실물 이관 시 되돌릴 것 모음

| 항목 | 시뮬 값 | 실물 |
|---|---|---|
| slam_toolbox 스캔 매칭 | off | **on** + loop closing |
| 라이다 사거리 | 20 m | 3.5 m (LDS-01) — SLAM 파라미터 재조정 |
| 순찰/Nav2 속도 | 0.35 m/s | ≤ 0.2 m/s |
| DiffDrive 상한 | 0.6 | 0.22 |
| 웹캠 탐지 | 색 점유 검사 (webcam_detect.py) | YOLO 모델 |
| Nav2 국지화 | 정적 TF map→odom (항등) | **AMCL**(또는 slam_toolbox localization) |
| DWB 회전 | acc_lim_theta 8.0, min_speed 0.05/0.6 (데드존 회피) | 기본값 3.2, 0.0/0.0 |
| behavior spin | 0.6~0.8 rad/s | 기본값 |
