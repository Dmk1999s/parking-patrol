# 진행 기록 — Isaac Sim 주차 단속 시뮬 (2026-08-19 세션 7 — 고시 규격 번호판 + EasyOCR)

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
9. **번호판 OCR** — `sim/vision/plate_ocr.py` (3중 로컬라이저 + **EasyOCR
   2단계**) + `amr1_nav` 통합: ILLEGAL → OCR → `POST /api/vehicle/`
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
15. **EV 파란판 결함 수정 + 통짜 리허설 3 (세션 5)** — `has_blue_plate` 가
    보던 고정 박스 `rows 260:500` 의 아래 180 행이 4~6 m 앞 **바닥**이라
    먼 바닥의 파란 주차선을 번호판으로 세던 비결정 결함을 **기하로** 막았다:
    판 높이로 계산한 띠 **206:406** (바닥은 아무리 멀어도 지평선 457 아래라
    원천 배제). 클린 DB 통짜 리허설로 **AMR1 11/11 정답 일치
    (SCANNED 7 / CLEARED 3 / UNREACHABLE 1, OCR 7/7 1회 성공)** +
    **AMR2 7/7 매치 → WARNING_ISSUED + 복귀**. 🎯 세션 4 의 유일한 미검증
    항목이던 **AMR2 의 yaw 270° 북쪽 앞판 관측점 도달을 로그로 확인**했다.
16. **외곽 담장 + SLAM 재작성 + AMCL 전환 (세션 6)** — 국지화 우회를 걷어냈다.
    세션 5 까지 `map→odom` 은 정적 TF(항등)였다 — 시뮬 odom 이 참값이라
    가능했던 커닝이다. 전제로 🚨 **외곽에 벽이 아예 없어서** 담장 4면을
    둘렀다 (`FENCE_T 0.4` · `FENCE_H 1.5`, ⚠ `GROUND` 북단 17.0 → **17.4** —
    안쪽에 세우면 앞판 관측점 16.70 을 먹는다). 지도 재작성 후 AMCL 투입:
    런치의 정적 TF 제거 → `amcl` 노드 + 라이프사이클 맨 앞 등록,
    `set_initial_pose` amr1 map (0,0) · amr2 (2.0, 0.0).
    **통짜 리허설 4 에서 정적 TF 와 완전히 같은 결과** — AMR1
    SCANNED 7 / CLEARED 3 / UNREACHABLE 1 (OCR 7/7 1회), AMR2 7/7 매치 →
    WARNING_ISSUED → 복귀. **AMCL 보정량 0.24~0.27 m** (예전엔 항상 0)
    가 걸린 조건에서 판별·OCR·검증이 전부 정답을 유지했다.
17. **고시 별표 규격 번호판 + OCR EasyOCR 전환 (세션 7)** — 번호판이
    "대충 그린 그림"에서 **실물 규격**이 됐다. 국토부 고시 별표 원문
    (`sim/고시별표/`)에서 셀 배분 `띠65│50×3│85│50×4│20`, 잉크 높이
    **74.8 mm**(셀 85.0 과 다르다), 8자리 `123가4567`, 좌측 청색 띠를 반영하고,
    글리프 45자를 **도면에서 직접 오려** 썼다 (`scenes/plate_glyphs.py` —
    폰트 파일 불필요). EV 판은 [별표 18] 대로 **연한 하늘색 + 검은 글자**로
    바로잡았다 (진한 남색 + 흰 글자는 실물과 정반대였다).
    실제 서체가 들어가자 tesseract 가 43/70 으로 무너져 **EasyOCR 2단계**
    (통짜 읽기 → 셀 비율로 한글 칸만 재독)로 교체 — **70/70**, 장당 35 ms.
    리허설이 EV 판별 결함을 잡아내 `PLATE_BLUE` 채도 35→**24**,
    `BLUE_COL_MIN` 3→**10** 으로 고쳤다 (문턱을 **내려야** 갈렸다).
    **통짜 리허설 5 완주**: 탐지 11/11 → AMR1 11/11 정답 → OCR 7/7 (전부
    1회) → AMR2 7/7 매치 → 복귀. 녹화 `rehearsal5_20260819.mp4`.

## ⚠ 알려진 공백

- 웹캠 탐지의 **차량 이탈 처리 없음**: DELETE API 호출 미구현이라
  차가 떠나도 이벤트가 남고, 같은 자리 재탐지도 안 된다 (노드 `confirmed`
  + 브리지 좌표 캐시). 고정 배치 시연에는 지장 없음.
- **벽쪽 세로주차 가운데 1대만 접근 불가** (세션 4 에서 축소): 실제 차 간격이
  0.1 m 라 남·북 관측점이 둘 다 이웃 차 몸통에 떨어지는 차가 있다. 앞판
  도입으로 남단(뒤판 yaw 90°)·북단(앞판 yaw 270°)은 단속되고, **가운데
  illegal_1 만** 남는다 — `layout.py` 가 원래 선언한 `blocked=(i == 1)` 이
  그대로다. `amr1_nav` 가 지도 검증으로 출동을 생략하고 **UNREACHABLE 로
  종결**해 흐름은 안 막힌다 (이벤트는 남겨 기록은 유지).
- ~~팀 Supabase 스키마 분기~~ **— 해소(추적 종료).** 팀 프로젝트가 끝나
  맞출 대상이 없다. **이 저장소 스키마가 정답이고 sqlite 로 계속 간다**
  (Django 를 `DB_HOST=` 빈값으로 기동). ⚠ 이 저장소의 마이그레이션 번호
  0013 은 팀 DB 의 0013 과 무관한 별개다 — 팀 DB 에 붙이면 안 된다.
- 🚨 **경차 차폭 마진이 3.3 mm 다 (세션 7 에서 악화 확인)**: stall 5 세단이
  **1.7033 m** 로 나왔다 — 임계 1.70 과 3.3 mm 차이로 간신히 불법 판정됐다.
  같은 차가 회차마다 흔들린다 (세션 5·6 은 1.77~1.82, 세션 7 은 1.70~2.31).
  **방향이 위험하다** — 과소 측정되면 세단이 경차로 넘어가 단속을 놓친다.
  원인 후보는 도착 거리다: `car_width_depth` 가 "판에서 2 m" 를 전제로
  픽셀→미터를 환산하는데 실제로는 더 가까이 선다 (판 폭 292 px vs 기대 241).
  **depth 로 실제 거리를 읽어 환산하면 상쇄될 것이다.** 미해결 (남은 것 2번).
  그리고 seed 7 엔 진짜 경차가 없어 임계 아래쪽은 여전히 미검증이다.

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
# ⚠ 세션 6 부터 국지화는 AMCL 이다 (정적 TF 없음). 확인:
#   ros2 lifecycle get /amr1/amcl        → active
#   ros2 run tf2_ros tf2_echo map amr1/odom   → 보정량 (예전엔 항상 0)

# 5. AMR1 출동 + 판별 + OCR (검증은 --all, 시나리오는 무옵션 = next 1건)
#    도착마다 구역/차종 판별→PATCH, 불법이면 OCR→vehicle POST(SCANNED).
#    🚨 OCR 이 easyocr 이라 **ocr_venv 인터프리터**로 돌린다 (아래 OCR 환경).
PATROL_SERVER=http://127.0.0.1:8000 $OCRPY sim/nav2/amr1_nav.py --all

# 6. AMR2 재확인 + 경보 (SCANNED 소진까지 돌고 시작 좌표로 복귀)
PATROL_SERVER=http://127.0.0.1:8000 $OCRPY sim/nav2/amr2_nav.py
```

### OCR 환경 (`$OCRPY`)

`plate_ocr` 가 EasyOCR 을 쓰는데 그건 `~/ocr_venv` 에만 있다. 같은 3.10.12 라
ROS 패키지를 PYTHONPATH 로 얹으면 한 프로세스에서 다 돈다:

```bash
export OCRPY="env PYTHONPATH=/opt/ros/humble/lib/python3.10/site-packages:\
/opt/ros/humble/local/lib/python3.10/dist-packages:$PYTHONPATH \
  $HOME/ocr_venv/bin/python"
```

🚨 **핀 두 개를 같은 명령으로 걸어야 한다** — 따로 걸면 뒤엣것이 numpy 2 를
도로 끌어온다 (둘 다 밟았다):

| 패키지 | 핀 | 어기면 |
|---|---|---|
| `numpy` | **<2** (1.26.4) | `cv_bridge` 가 numpy 1.x 로 빌드된 C 확장이라 `AttributeError: _ARRAY_API not found` |
| `opencv-python-headless` | **<5** (4.10.0.84) | Humble `cv_bridge` 가 타입 상수를 못 찾아 `KeyError: 16` |

```bash
~/ocr_venv/bin/pip install "numpy<2" "opencv-python-headless==4.10.0.84"
```

🚨 **`isaacsim_venv` 에는 easyocr 을 설치하지 않는다** — 거기 torch 2.11 을
건드리면 Isaac Sim 이 깨진다. 씬은 지금처럼 따로 띄운다 (씬은 OCR 을 안 쓴다).

- 이전 세션 이벤트가 DB 에 남아 있으면 `/api/parking/list/` 로 id 확인 후
  `DELETE /api/parking/<id>/delete/` 로 비우고 시작한다 (탐지 노드가 다시
  채운다). 브리지·탐지 노드를 재시작해야 중복 캐시도 초기화된다.
  DETECTED · CLEARED · UNREACHABLE 은 지워지고, 단속이 끝난
  SCANNED · WARNING_ISSUED 는 400 이 난다 — 통짜 리허설을 처음부터 다시
  돌리려면 `db.sqlite3` 를 지우고 `mig` 로 다시 만드는 게 빠르다.
- slam_toolbox·map_snapshot 은 **지도를 다시 만들 때만** 필요하다.
  ⚠ 지도를 다시 만들면 ① `map_saver_cli` 가 `free_thresh` 를 0.25 로
  덮어쓰므로 **0.196 으로 되돌리고** ② AMR2 주차 자리의 유령 블롭(세션 4
  197px, 세션 6 은 8px)을 205 로 지운다. ③ `explore_amr1` 은 **장애물 회피가
  없다** — 웨이포인트 사이 직선이 차를 관통하지 않는지 반드시 확인할 것
  (세션 4 에서 로봇이 벽쪽 차에 박혔다).
  🚨 지도를 픽셀로 검증할 때 두 가지를 헛짚기 쉽다 (세션 6):
  **로봇은 자기 라이다에 안 잡힌다** — 자기 정지 자리의 점유는 유령이 아니라
  옆 구조물(북쪽 담장)이다. 그리고 **두께 있는 벽은 표면만 그려지므로**
  중심선 한 열을 읽으면 0 에 가깝다 — 밴드(예: x 4.3~4.7)로 셀 것.
- 🚨 **kill 은 단독 명령으로.** 패턴에 브래킷을 끼우는 것(`amr1_nav[.]py`)
  만으로는 부족하다 — **같은 명령줄 어디에든** 대상 문자열의 원문이 있으면
  (뒤이은 재기동 명령, 확인용 grep 패턴, 힙독 안의 파일 경로) 자기 셸이 죽는다.
  누적 6회 밟았다. 기동·확인·grep 을 kill 과 같은 줄에 절대 두지 말 것.

⚠ seed 7 고정 — 바꾸면 차량 배치·지도·DB 정답이 전부 갈린다.

---

## 📋 남은 것

1. **URDF 도입** — 지금은 링크 TF 트리가 없어 footprint·센서 위치를
   `nav2_params_*.yaml` 에 손으로 박아 뒀다 (`robot_radius 0.28` 등).
   실물 bringup 은 `robot_state_publisher` 가 URDF 를 읽어 발행하는 쪽이다.
   ⚠ **단속 파이프라인 로직은 URDF 유무와 무관하다** — 배선 문제라
   우선순위는 AMCL 아래였다 (세션 6 에서 AMCL 을 먼저 끝냈다).
2. 🔴 **depth 차폭 — 거리 전제를 걷어내야 한다 (세션 7 에서 우선순위 상승)**
   마진이 3.3 mm 까지 좁혀졌다 (위 공백란). 할 일은 `car_width_depth` 가
   고정 2 m 대신 **depth 프레임에서 실제 거리를 읽어** 환산하도록 바꾸는 것.
   depth 는 이미 받고 있으므로 차폭을 재는 그 자리에서 같이 뽑으면 된다.
   검증: 같은 차를 여러 자세에서 재서 값이 모이는지 본다.
   ~~**depth 차폭 — 진짜 경차 미검증**~~ 세션 6 **1.80 · 1.82**, 세션 5
   1.82 · 1.78 m (실제 1.80) 로 안정적이다 (세션 4 의 1.74/1.81/**2.64**
   같은 튐 없음 — AMCL 보정 0.27 m 가 걸린 조건에서도 그렇다). 하지만
   **seed 7 경차구역에 진짜 경차(1.6)가 없어** 임계 1.70 을 가르는 능력은
   여전히 미검증이다. 값이 안정된 건 좋은 신호지 증명이 아니다.
3. **웹캠 이탈 처리** — 점유가 풀려도 `confirmed` 에서 안 지워져(`hits` 만
   0 으로 리셋) 이벤트가 남고 같은 자리 재탐지도 막힌다. 확정 취소 +
   브리지 DELETE 경로가 세트로 필요하다. 고정 배치 시연엔 지장 없어 우선순위
   낮음. 시뮬 재현 방법: 차량은 `_collide()` 로 **CollisionAPI 만** 붙은
   정적 콜라이더라 물리로는 안 움직인다 — 탐지가 렌더 색 점유 검사이므로
   **Xform 가시성을 끄는 것**(`MakeInvisible`)이 제일 단순하다. `patrol.py`
   에 그런 훅은 아직 없다.
4. **다른 seed 에서는 차체 색이 파란판을 오염시킬 수 있다** — `PLATE_BLUE`
   마스크에 남색 세단(H114 S182 V89)·하늘색 EV(H98 S187 V191) **차체가
   실제로 걸린다**. seed 7 EV 구역은 은색·흰색이라 안 걸렸을 뿐이다.
   띠를 좁혀 바닥은 막았지만 차체는 여전히 띠 안에 있다.

## ⚠ 실물 이관 시 되돌릴 것 모음

| 항목 | 시뮬 값 | 실물 |
|---|---|---|
| slam_toolbox 스캔 매칭 | off | **on** + loop closing |
| 라이다 사거리 | 20 m | 3.5 m (LDS-01) — SLAM + **amcl.laser_max_range** 같이 |
| 순찰/Nav2 속도 | 0.35 m/s | ≤ 0.2 m/s |
| DiffDrive 상한 | 0.6 | 0.22 |
| 웹캠 탐지 | 색 점유 검사 (webcam_detect.py) | YOLO 모델 |
| 번호판 OCR | EasyOCR 2단계 (`~/ocr_venv`, GPU 21 ms / CPU 51 ms) | 그대로 가능. **원근 보정(4점 warp) 추가 필요** |
| ~~Nav2 국지화~~ | ~~정적 TF map→odom~~ | **해소(세션 6) — AMCL 로 전환 완료** |
| DWB 회전 | acc_lim_theta 8.0, min_speed 0.05/0.6 (데드존 회피) | 기본값 3.2, 0.0/0.0 |
| behavior spin | 0.6~0.8 rad/s | 기본값 |
| 전역 코스트맵 반경 | 0.28 (차 사이 틈 차단) | 실물 주차장 기하에 맞게 재검토 |
| 구역색 HSV 임계값 | 렌더 실측 (zone_classify.py) | 실물 카메라로 재캘리브레이션 |
| depth 차폭 측정 | 렌더 depth AOV | **RealSense 급 장착** 필요 (없으면 구방식 폴백) |
| 로봇 모델 | URDF 없음 — footprint·센서 위치를 `nav2_params_*.yaml` 에 손으로 박음 | **URDF + robot_state_publisher** (실물 bringup 표준). 단속 로직은 안 바뀐다 |
