# 진행 기록 — Isaac Sim 주차 단속 시뮬 (2026-08-18 세션 4 — 종결 정책 + 앞 번호판)

> **이 저장소는 개인 작업이다.** 원본은 종이 판자 맵 + 실물 TurtleBot4 2대로
> 수행한 팀 프로젝트였고 그 기간은 끝났다. 지금은 혼자 Isaac Sim +
> TurtleBot3 로 다시 구현하는 중이다 — **"팀 논의 필요" 항목은 전부 내가
> 결정하면 되고, 팀 Supabase 스키마에 맞출 이유도 없다 (sqlite 유지).**

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
6. **AMR 카메라 → 대시보드** — 씬이 **두 로봇의** OcrCam 을
   `amr_images/<ns>/ocr` (시뮬 5 Hz) 로 발행(카메라는 `--robots` 배선과
   분리, 프림은 `base_link` 링크 밑 — 루트에 달면 로봇을 안 따라간다),
   `sim/vision/amr_cam_bridge.py --gate`(로봇당 1개) 가
   `POST /api/<robot>/frame/` 로 올려 `/monitor/` AMR 패널에 표시.
   게이트: `<ns>/on_duty` True(출동 중)에만 실화면, 아니면 STANDBY 판.
7. **실차 치수 반영** — 차량을 실측 규격으로 (SEDAN/EV 1.8×4.7×1.45,
   경차 1.6×3.6×1.45, 소방차 2.5×7.5×3.2). 지도 재작성 + 탐지 재검증 완료.
   주차면·번호판·TB3·주차선은 원래부터 실제 규격.
8. **AMR1 현장 판별 (구역/차종)** — `sim/vision/zone_classify.py` +
   `amr1_nav` 통합: 도착 → OcrCam+위치로 zone/vehicle 판별 →
   `PATCH /api/parking/<id>/zone/`. **seed 7 에서 11/11 시나리오 정답 일치**
   (일반 스킵 2, 경차 불법 2, EV 정상 1·불법 1, 소방 불법 1, 벽쪽 Not 1,
   접근 불가 2, 장애인 보류 1 — OCR 단계에서 판정). 상세는 WORKLOG.
9. **번호판 OCR** — `sim/vision/plate_ocr.py` (3중 로컬라이저 + tesseract
   다수결) + `amr1_nav` 통합: ILLEGAL → OCR → `POST /api/vehicle/`
   (plate, amr_vehicle_x/y=관측점, ocr_image_path) → **SCANNED**.
   DISABLED 는 `/api/disabled/<판>/` 조회로 최종 판정. 실패 시 DETECTED
   유지→재방문. 상세·함정은 WORKLOG.
10. **depth 채널 + 차폭 개선** — OcrCam render product 공유로
    `amr_images/<ns>/depth` (32FC1) 발행. 경차 차폭을 depth 로 측정
    (그림자 배제): 세단 실측 1.77 m (구방식 2.75). 실물 이관 시 depth
    카메라 장착 필요 ("되돌릴 것").
11. **통짜 리허설 통과** — 클린 DB 에서 **단일 --all 순회**로 시나리오
    완주: 재탐지 11/11 → 불법 6건 SCANNED(번호판 6/6 정답, 전 건 OCR
    1회 성공) + 정상 스킵 + 도달불가 즉시 생략.
12. **AMR2 (Police 2)** — `sim/nav2/amr2_nav.py` + amr2 용 Nav2 스택
    (`nav2_params_amr2.yaml`·`nav2_amr2.launch.py`, amr1 런치 위에 얹음).
    `GET /api/vehicle/next/` 루프 → 관측점 이동 → OCR 재확인 → verify.
    **seed 7: 6/6 매치 → WARNING_ISSUED, 복귀 완료** — 전체 status 흐름
    (DETECTED→SCANNED→WARNING_ISSUED) 시뮬 완주. 씬은 `--robots both`.
14. **앞 번호판 + 관측면 선택 (세션 4)** — 실물처럼 차량에 **앞판(+Y)** 을
    추가하고, 웹캠이 점유 마스크로 **남(뒤판)/북(앞판) 관측면을 자동 선택**
    한다. 방향은 좌표로 복원 불가라 `observation_yaw` 컬럼(0014)으로
    전달한다. SLAM 지도 북단을 15.41 → **17.03** 으로 재작성.
    **결과: 벽쪽 북단 차가 앞판으로 판독돼 `73카8353` 단속** (예전엔 접근
    불가). layout 의 원래 의도 `blocked=(i==1)`(가운데 1대만 불가) 복원.
    **AMR1 순회 11/11 정답 일치** — 상세는 WORKLOG 세션 4.
13. **이벤트 종결 정책 (세션 4)** — AMR1 단계에서 끝나는 이벤트가 DETECTED
    로 남아 `/api/parking/next/` 를 막던 문제 해결. status 에 `CLEARED`
    (정상 스킵) · `UNREACHABLE`(접근 불가) 추가 — 정상 판정은 zone PATCH 시
    **서버가 자동 전환**, 접근 불가는 `PATCH /api/parking/<id>/unreachable/`.
    OCR 실패는 지금처럼 DETECTED 유지(재방문). 실제 요청 14케이스 검증.

## ⚠ 알려진 공백

- 웹캠 탐지의 **차량 이탈 처리 없음**: DELETE API 호출 미구현이라
  차가 떠나도 이벤트가 남고, 같은 자리 재탐지도 안 된다 (노드 `confirmed`
  + 브리지 좌표 캐시). 고정 배치 시연에는 지장 없음.
- **벽쪽 세로주차 2·3번 차는 접근 불가**: 차간 0.5 m 라 "번호판 남쪽 2 m"
  관측점이 이웃 차 내부에 떨어진다 (남단 1대만 도달 가능). 지금은
  `amr1_nav` 가 지도 검증으로 출동을 생략하고 **UNREACHABLE 로 종결**해
  흐름은 안 막힌다. 벽쪽을 남단 1대만 단속으로 둘지, obs 정책을 바꿀지는
  선택 사항 (남은 것 4번).
- ~~팀 Supabase 스키마 분기~~ **— 해소(추적 종료).** 팀 프로젝트가 끝나
  맞출 대상이 없다. **이 저장소 스키마가 정답이고 sqlite 로 계속 간다**
  (Django 를 `DB_HOST=` 빈값으로 기동). ⚠ 이 저장소의 마이그레이션 번호
  0013 은 팀 DB 의 0013 과 무관한 별개다 — 팀 DB 에 붙이면 안 된다.
- **경차 차폭 마진이 얇다**: depth 방식으로 세단 실측 1.77 m (구방식
  2.76) 까지 좁혔지만 경차 임계 1.70 과 마진이 0.07 뿐이다. seed 7 엔
  경차구역에 진짜 경차가 없어 미검증 (남은 것 3번).

---

## ▶ 다음 세션 시작 절차

인스턴스 재시작 후엔 아무것도 안 떠 있다. 순서대로:

```bash
cd ~/dongmin_project/ros_ws/Alley_Park_Patrol_system-monitor

# 1. Django (⚠ DB_HOST= 빈값 — 팀 .env 가 있어도 sqlite 로. 공백란 참고) + RViz 웹
DB_HOST= venv/bin/python manage.py runserver 0.0.0.0:8000 --noreload &
./sim/slam/rviz_web.sh

# 2. 씬 — 스트리밍 끄고 (화면은 8000 웹캠 MJPEG 로 본다). 로딩 수 분.
#    AMR1 만 돌릴 땐 --robots amr1 이 빠르다 (라이다 1대).
ISAAC_STREAM=0 PATROL_PRJ="$PWD" ROS_DOMAIN_ID=2 RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  OMNI_KIT_ACCEPT_EULA=YES PYTHONUNBUFFERED=1 \
  ~/isaacsim_venv/bin/python sim/scenes/patrol.py --seed 7 --robots both --report 10 &

# 3. ROS 쪽 (source /opt/ros/humble/setup.bash, ROS_DOMAIN_ID=2)
PATROL_SERVER=http://127.0.0.1:8000 python3 bridge/bridge_webcam.py &
python3 sim/vision/webcam_detect.py &        # → DB 에 DETECTED 11건 자동 생성
PATROL_SERVER=http://127.0.0.1:8000 python3 sim/vision/amr_cam_bridge.py --gate &
PATROL_SERVER=http://127.0.0.1:8000 python3 sim/vision/amr_cam_bridge.py --robot amr2 --gate &
# ↑ AMR OcrCam → 대시보드 (출동 중에만 실화면, 대기 중 STANDBY — 사용자 확정)

# 4. Nav2 (씬이 뜬 다음 — /clock·/tf 필요). amr2 는 amr1 런치 위에 얹는다.
ros2 launch sim/nav2/nav2_amr1.launch.py &     # 지도 + amr1 스택
ros2 launch sim/nav2/nav2_amr2.launch.py &     # amr2 스택 (--robots both 일 때)
# ⚠ map_server 활성화가 응답 유실로 inactive 에 머물면:
#   ros2 lifecycle set /map_server activate

# 5. AMR1 출동 + 판별 + OCR (검증은 --all, 시나리오는 무옵션 = next 1건)
#    도착마다 구역/차종 판별→PATCH, 불법이면 OCR→vehicle POST(SCANNED).
PATROL_SERVER=http://127.0.0.1:8000 python3 sim/nav2/amr1_nav.py --all

# 6. AMR2 재확인 + 경보 (SCANNED 소진까지 돌고 시작 좌표로 복귀)
PATROL_SERVER=http://127.0.0.1:8000 python3 sim/nav2/amr2_nav.py
```

- 이전 세션 이벤트가 DB 에 남아 있으면 `/api/parking/list/` 로 id 확인 후
  `DELETE /api/parking/<id>/delete/` 로 비우고 시작한다 (탐지 노드가 다시
  채운다). 브리지·탐지 노드를 재시작해야 중복 캐시도 초기화된다.
  DETECTED · CLEARED · UNREACHABLE 은 지워지고, 단속이 끝난
  SCANNED · WARNING_ISSUED 는 400 이 난다 — 통짜 리허설을 처음부터 다시
  돌리려면 `db.sqlite3` 를 지우고 `mig` 로 다시 만드는 게 빠르다.
- slam_toolbox·map_snapshot 은 **지도를 다시 만들 때만** 필요하다.
  ⚠ 지도를 다시 만들면 ① `map_saver_cli` 가 `free_thresh` 를 0.25 로
  덮어쓰므로 **0.196 으로 되돌리고** ② AMR2 주차 자리의 유령 블롭(세션 4
  에서 197px)을 205 로 지운다. ③ `explore_amr1` 은 **장애물 회피가 없다** —
  웨이포인트 사이 직선이 차를 관통하지 않는지 반드시 확인할 것 (세션 4 에서
  로봇이 벽쪽 차에 박혔다).
- ⚠ 노드를 pkill 로 죽일 때 패턴이 자기 셸 명령줄과 매칭되지 않게 할 것
  (`pkill -f "amr1_nav[.]py"` 처럼 브래킷을 끼운다).

⚠ seed 7 고정 — 바꾸면 차량 배치·지도·DB 정답이 전부 갈린다.

---

## 📋 남은 것

1. **AMR2 앞판 재확인 미완** — 세션 4 마지막 리허설에서 AMR2 를 돌리다
   **1/7 에서 인스턴스 종료로 중단**했다 (id=104 매치 성공, id=112 =
   벽쪽 북단 앞판으로 이동 중이었다). AMR2 흐름 자체는 같은 세션 앞부분에
   5/5, 세션 3 에 6/6 검증됐으므로 **미검증인 것은 "AMR2 가 yaw 270°
   북쪽 관측점에 도달하는가" 한 가지뿐**이다. 다음 세션 1순위.
   (AMR1·AMR2 는 odom 오프셋이 달라 좌표 변환이 따로 돈다.)
2. **EV 파란판 오판 — 잠복 결함** 🚨 `zone_classify.has_blue_plate` 가
   보는 박스 `rows 260:500` 의 **하단이 4~6 m 앞 바닥**이다 (`ground_row`
   역산: 4 m→504, 6 m→488). 정작 번호판은 2 m 앞·높이 0.5 m 라 row≈319 —
   박스가 판 아래로 180행 더 뻗어 **먼 바닥의 파란 주차선·장애인 표지를
   번호판으로 셀 수 있다.** 실측: 같은 EV구역 세단이 리허설 1 에서
   7823px(오판→정상 처리), 리허설 2 에서 0px(정답). **자세에 따라 갈리는
   비결정적 결함**이라 임계값으로는 못 막는다. 박스를 판 높이로 좁힐 것.
3. **depth 차폭 측정 불안정** — 같은 세단이 1.74 m / 1.81 m / **2.64 m**
   로 흔들린다 (실제 1.8). 경차 임계 1.70 을 넘어 판정은 맞았지만 값 자체를
   못 믿는다. 진짜 경차(1.6)가 오면 오판 위험.
4. **웹캠 이탈 처리** — 점유 해제 시 확정 취소 + 브리지 DELETE 경로.
   고정 배치 시연엔 지장 없어 우선순위 낮음.

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
| 전역 코스트맵 반경 | 0.28 (차 사이 틈 차단) | 실물 주차장 기하에 맞게 재검토 |
| 구역색 HSV 임계값 | 렌더 실측 (zone_classify.py) | 실물 카메라로 재캘리브레이션 |
| depth 차폭 측정 | 렌더 depth AOV | **RealSense 급 장착** 필요 (없으면 구방식 폴백) |
