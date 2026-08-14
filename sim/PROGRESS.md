# 진행 기록 — Isaac Sim 주차 단속 시뮬 (2026-08-14 세션 2 종료 시점)

다음 세션에서 이 파일부터 읽는다. 세션별 상세 기록은 `sim/WORKLOG.md`,
원리·함정은 `sim/README.md` 에 있다. 여기는 **무엇이 끝났고, 다음에
무엇을 어떻게 시작하는지**만 적는다.

---

## ✅ 끝난 것 (요약 — 상세는 WORKLOG)

1. **물리 + 라이다 + 차동구동** — 씬·ROS 배선 전부 검증 완료.
   odom = 월드 좌표 (시작좌표 오프셋만 더하면 됨).
2. **SLAM 지도 완성** — **`sim/slam/maps/parking.pgm/.yaml`** (Nav2 형식,
   seed 7). `expected_map.py --seed 7` 과 대조 검증 끝. 지도는 다시 뜰
   필요 없다 — seed 를 바꾸지 않는 한 그대로 쓴다.
3. **웹 모니터링** — RViz 웹(6080) · 웹캠 MJPEG(8000) · 대시보드(8000).
4. **웹캠 차량탐지 → DB** — `sim/vision/webcam_detect.py` (신규).
   seed 7 에서 11/11 대 탐지·오탐 0, `parking_events` 11건(DETECTED) 검증.
   서버·브리지 코드는 안 고침.

## ⚠ 알려진 공백

- 웹캠 탐지의 **차량 이탈 처리 없음**: DELETE API 호출 미구현이라
  차가 떠나도 이벤트가 남고, 같은 자리 재탐지도 안 된다 (노드 `confirmed`
  + 브리지 좌표 캐시). 고정 배치 시연에는 지장 없음.

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
```

- 이전 세션 이벤트가 DB 에 남아 있으면 `/api/parking/list/` 로 id 확인 후
  `DELETE /api/parking/<id>/delete/` 로 비우고 시작한다 (탐지 노드가 다시
  채운다). 브리지·탐지 노드를 재시작해야 중복 캐시도 초기화된다.
- slam_toolbox·map_snapshot 은 **지도를 다시 만들 때만** 필요하다.

⚠ seed 7 고정 — 바꾸면 차량 배치·지도·DB 정답이 전부 갈린다.

---

## 📋 남은 것 (시나리오 순서)

1. **Nav2** — 저장한 지도(`sim/slam/maps/parking`) + `/amr1/odom`·`/tf`
   위에서 기동. AMR1 이 `GET /api/parking/next/` 좌표(= DB 의 observation,
   전부 통로 위라 그대로 목표 pose)로 자율 이동. yaw 는 탐지 노드가 마커
   orientation 에 넣어 둠 (블록A 180°, 블록B 0°, 벽쪽·소방 90°).
2. **OpenCV 구역/차종 판별** — HSV 실측 임계값은 README "구역 색" 절.
   경차=차폭(1.55 vs 1.80), 전기차=파란 번호판, 장애인=휠체어 표시+DB 조회.
3. **OCR 노드 통합** — tesseract 검증 완료(README). OcrCam 프레임 →
   번호판 텍스트 → `POST /api/vehicle/`.
4. **AMR2 시나리오** — AMR1 복귀 후 출동, `GET /api/vehicle/next/` →
   번호판 재확인 → `POST /api/vehicle/verify/`. (씬은 `--robots both`)
5. **웹캠 이탈 처리** — 점유 해제 시 확정 취소 + 브리지에 DELETE 경로 추가.
6. **팀 `.env`** — 받으면 Supabase 로 자동 전환. 그 전까지는 sqlite.

## ⚠ 실물 이관 시 되돌릴 것 모음

| 항목 | 시뮬 값 | 실물 |
|---|---|---|
| slam_toolbox 스캔 매칭 | off | **on** + loop closing |
| 라이다 사거리 | 20 m | 3.5 m (LDS-01) — SLAM 파라미터 재조정 |
| 순찰/Nav2 속도 | 0.35 m/s | ≤ 0.2 m/s |
| DiffDrive 상한 | 0.6 | 0.22 |
| 웹캠 탐지 | 색 점유 검사 (webcam_detect.py) | YOLO 모델 |
