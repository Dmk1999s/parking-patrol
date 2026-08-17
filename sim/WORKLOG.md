# 작업 기록 — Isaac Sim 주차 단속 시뮬

세션별 상세 기록이다. **다음에 뭘 할지**는 `PROGRESS.md`, 원리·함정은
`README.md` 를 본다.

---

## 세션 1 (2026-08-14 주간) — 시뮬 기반 구축

### 물리 + 라이다 + 차동구동
- `scenes/patrol.py` — 물리가 도는 순찰 씬 (`parking_lot.py` 는 그림 전용)
- `scenes/ros_bridge.py` — ROS 2 배선 전부:
  `/clock` · `/amr{1,2}/scan`(3600점·20 m) · `/amr{1,2}/odom` · `/tf` ·
  `/amr{1,2}/cmd_vel`(구독) · 웹캠 Image 발행 (1280×720, 10 Hz)
- Humble(3.10) 쪽에서 전 토픽 수신 + `/amr1/cmd_vel` 실주행 확인
- odom 은 실측으로 월드 좌표와 정확히 일치 (odom + AMR 시작좌표 = 월드)
- 자동 처리되는 함정 3개: ROS 브리지 LD_LIBRARY_PATH(조용히 죽음),
  TB3 캐스터 바닥 관통, 실린더 콜라이더 — 상세는 README

### SLAM 파이프라인 구성
- `slam/slam_params.yaml` — 스캔 매칭 꺼 둠 (RTX 라이다 회전 왜곡 때문.
  시뮬 odom 이 참값이라 끄는 게 정답. **실물 이관 시 되돌릴 것**)
- `slam/explore_amr1.py` — odom 폐루프 웨이포인트 순찰
- `slam/map_snapshot.py` / `slam/expected_map.py` / `slam/rviz_web.sh`

### 웹 모니터링 (전부 동작)
- RViz 웹(noVNC 6080) · 웹캠 MJPEG(8000) · 팀 대시보드(8000/monitor)
- Django sqlite 폴백 추가 — 팀 `.env` 없이 뜬다 (`config/settings.py`)

### 사고와 수습
- 순찰 노드 SIGTERM 시 정지 명령이 안 나가 로봇이 무인 주행으로 차량
  사이에 낌 → 오염된 스캔이 지도에 섞임. 버그 수정(SIGTERM/SIGINT/finally
  전부에서 정지 발행) + 로봇 구출. **지도는 폐기, 세션 2 에서 재작성.**
- 속도 개선: 순찰 0.2→0.35 m/s, DiffDrive 상한 0.6.
  시뮬이 느린 주범은 WebRTC 스트리밍(rtf ~0.3)임을 실측.

---

## 세션 2 (2026-08-14 야간) — SLAM 지도 완성 + 웹캠 차량탐지

### SLAM 지도 완성 ✅
- 전체 스택 재기동. 씬은 `ISAAC_STREAM=0` 으로 띄워 rtf 확보
  (화면은 8000 웹캠 MJPEG + 6080 RViz 웹으로 봄).
- `explore_amr1.py` 완주(0.35 m/s, 웨이포인트 7개) →
  **`slam/maps/parking.pgm/.yaml`** (Nav2 형식) 저장.
- `expected_map.py --seed 7` 과 대조: 차량 11대·벽 2개·소방차 전부 일치,
  오염 없음. 차량 내부 회색(미탐사)·주차선 없음은 라이다 특성상 정상.
- 순찰 후 복귀 절차 확립: `explore_amr1.py --wp "0.8,15.2;1.2,-3.0"
  --exit-on-done` → 시작 위치 (1.2, -3.0) 복귀.
- `slam/patrol.rviz` TF `Show Names: false` — 로봇 위 프레임 이름 겹침 제거.

### 웹캠 차량탐지 → DB ✅ (`vision/webcam_detect.py` 신규)
실제 시스템의 "웹캠 + YOLO" 자리를 채우는 노드. 프레임에서 차량을 찾아
관측 좌표(observation)를 `webcam_objects/map_detections`(MarkerArray)로
발행 → 기존 `bridge/bridge_webcam.py` 가 `POST /api/parking/`.
**서버·브리지 코드는 한 줄도 안 고침.**

- 픽셀→월드는 선형 (웹캠이 무회전 수직 하방): 0.0302 m/px.
  상수는 `layout.WEBCAM` 단일 출처 (`WEBCAM`·`GROUND` 를 lot.py 에서 이동).
- **1차 시도(윤곽→자리 스냅)는 실패** — 그림자가 차·벽을 한 블롭으로
  이어붙여 11대 중 3대만 잡혔다 (블록 A 전체가 117k px 윤곽 하나).
- **2차(자리별 점유 검사)로 전환** — 자리 기하는 사전에 아니까 블롭을
  나눌 필요가 없다:
  - A/B 주차면: 그림자(남·동쪽 ~1.6 m) 없는 **남쪽 띠** 박스
  - 장애인 칸: 중심의 표지(2.31 m 파란 □)를 피해 **좌우 플랭크 패치**
  - 번호판 위치는 밴드 안 비바닥 픽셀의 통로 쪽 2/98 퍼센타일 경계
- 렌더 색 함정 실측 (조명 때문에 칠한 값과 다르다):
  - 장애인 표지: (B228, G174, R104) — 파랑 필터로 못 거른다 → 패치로 해결
  - 소방 경계선: 주황이 노랑 (B36, G177, R225) 으로 뜬다 → R>180 ∧
    120<G<0.9R ∧ B<80 을 바닥 취급 (소방차 빨강·경차 노랑은 안 걸림)
- **검증: seed 7 에서 11/11 대 탐지, 빈 칸 4개 오탐 0, DB
  `parking_events` 11건(status=DETECTED) 확인.** 관측 좌표는 전부 통로 위
  (블록A 앞 x≈11.9, 블록B 앞 x≈14.2, 벽쪽·소방은 남쪽 y−2 지점).

### 알려진 공백 (다음에)
- 차량 **이탈 시 DELETE** (`/api/parking/<id>/delete/`) 미구현 — 노드의
  `confirmed` 와 브리지 좌표 캐시 때문에 같은 자리 재탐지도 안 된다.
  고정 배치 시연에는 문제 없음. 구현하려면 브리지에 삭제 경로 추가 필요.

### 중복 방지 구조 (질문 받았던 것)
1. 자리당 3프레임 연속 점유라야 확정 (노이즈 디바운스)
2. 노드 `confirmed` — 자리당 확정 1회
3. 브리지 `_sent_coords` — 반올림 좌표당 POST 1회 → DB 자리당 1건

---

## 세션 3 (2026-08-17) — Nav2 기동 + AMR1 자율 출동 ✅

### Nav2 구성 (`sim/nav2/` 신규)
- `apt` 로 navigation2 + nav2-bringup 설치.
- `nav2_params_amr1.yaml` + `nav2_amr1.launch.py` — map_server(공용 /map) ·
  planner · controller(DWB) · behaviors · bt_navigator 를 `/amr1` 네임스페이스로.
  nav2_bringup 런치를 안 쓴 이유는 launch 파일 머리말 참고.
- **AMCL 없음** — 지도를 스캔 매칭 없이 만들어 map 프레임 = amr1/odom 프레임.
  정적 TF `map→amr1/odom`(항등) 하나로 끝. 월드↔map 변환은
  `map = world − AMR_START[0]` (params yaml 머리말에 근거 정리).
- `amr1_nav.py` — `GET /api/parking/next/` 좌표 1회 수신 → NavigateToPose.
  DB 에 yaw 가 없어 좌표에서 복원 (통로 서쪽 절반 180° / 동쪽 절반 0° /
  통로 밖 90° — webcam_detect 와 같은 규칙). `--all`(전 이벤트 순방문),
  `--goal`(수동 목표) 지원. 종료 시그널에서 목표 취소 (무인 주행 방지).

### 🚨 함정 1 — 지도에 로봇 유령이 박혀 출발부터 막혔다
NavFn 은 lethal(254)뿐 아니라 **inscribed(253)도 통과 불가**로 본다. 그런데
저장된 지도에 **AMR1 시작 위치 자체에 2px, AMR2 주차 위치에 26px** 점유
블롭이 있었다(매핑 중 라이다에 찍힌 것). 시작 셀 주변이 전부 inscribed 라
로봇이 자기 유령에 갇혀 "GridBased: failed to create plan" 만 반복 —
코스트맵을 ASCII 덤프해서야 보였다. → 두 블롭만 205(미탐사)로 지움
(원본은 git). **지도를 다시 만들면 같은 정리가 또 필요하다.**

### 🚨 함정 2 — 제자리 회전 데드존 × DWB 폐루프 = 영구 정지
실측 (정지 상태에서 cmd_vel 직접 발행, 벽시계 8초):

    wz 0.37 → Δyaw 0.1° (전혀 안 돎)   wz 0.5 → 실효 0.049 rad/s
    wz 0.7 → 실효 0.109 rad/s

컨벡스 근사 바퀴의 정지 마찰 특성으로 저속 회전 명령은 그냥 씹힌다.
문제는 DWB 와의 결합: 샘플은 odom 속도 ± acc_lim×dt 라 정지에서 최대
3.2×0.1s=**0.32** — 데드존 안이다. 로봇이 안 도니 odom 이 0 그대로고 다음
샘플도 0.32 → **오류 없이 영원히 제자리**. "Failed to make progress" 로만
드러난다. → `acc_lim_theta 8.0`(한 주기에 0.8 도달) +
`min_speed_xy 0.05` / `min_speed_theta 0.6`(데드존 샘플 제거) +
behavior spin 0.6~0.8. **⚠ 실물 TB3 는 데드존이 없다 — 기본값으로 되돌릴 것.**

### 검증 — DB 11건 전체 방문 (`amr1_nav.py --all`)
**9/11 도착 ✅.** 블록A 앞 4건 · 블록B 앞 3건 · 소방 1건 · 벽쪽 남단 1건
전부 성공, yaw 복원 규칙(180/0/90°)도 도착 자세로 확인.

실패 2건(id31·id30)은 **벽쪽 세로주차 2·3번 차** — 차간 간격이 0.5 m 라
"번호판(-Y) 남쪽 2 m" 관측점이 **이웃 차 내부**에 떨어진다. 기하적으로
남단 차만 접근 가능하다. layout.py 는 가운데 차만 `blocked` 로 표시하지만
실제로는 3번 차도 번호판 접근이 안 된다 — 시나리오에서 벽쪽은 남단 1대만
단속 가능한 것으로 정리하든지, webcam_detect 의 벽쪽 obs 정책을 바꾸든지
**팀 결정 필요** (PROGRESS 공백란에 올림).

### AMR 카메라 → 모니터 대시보드 ✅ (요청: 관리자가 웹에서 AMR 화면을 본다)
서버에 이미 있던 `POST /api/<robot>/frame/` · 대시보드 "AMR (Police) 카메라"
패널을 그대로 쓴다 — **서버 코드 무수정**. 최종 구조 (사용자 확정:
**AMR1·AMR2 둘 다 OcrCam 상시 연결**, 추적 카메라는 넣었다가 뺐다):
- 씬: `ros_bridge.wire(cam_robots=...)` — 두 로봇의 OcrCam 을
  `amr_images/<ns>/ocr` (Image, 1280×720, 시뮬 10 Hz) 로 발행.
  **카메라 발행은 `--robots` 라이다 배선과 분리** — `--robots amr1` 이어도
  AMR2 화면이 나온다 (patrol.py 가 cam_robots=전체를 준다).
  `webcam_graph` 는 frame_id·label 인자로 일반화해 재사용.
- `sim/vision/amr_cam_bridge.py` (신규) — 토픽을 받아 JPEG(q60)·base64 로
  `POST /api/<robot>/frame/`, 벽시계 4 Hz 타이머 (시뮬 속도와 무관하게
  대시보드 갱신률 일정). 로봇당 하나씩 띄운다 (`--robot amr2`).
- `--gate` 옵션 (기본 꺼짐, AMR2 시나리오에서 쓸 수 있게 남겨 둠) —
  `<robot>/on_duty` (Bool) True 인 동안만 실화면, 아니면 STANDBY 판.
  전송만 끊으면 서버가 마지막 프레임을 계속 보여줘 방송 중처럼 보이기
  때문에 빈 판을 능동적으로 올린다.
- 검증: `/api/amr1/frame/latest/`·`/api/amr2/frame/latest/` 둘 다 실화면
  수신 확인. OCR 노드도 같은 토픽(`amr_images/<ns>/ocr`)을 구독하면 된다.
- 기각 안 기록: 웹캠1 줌(탐지 상수 0.0302 m/px 가 깨짐), 근접 웹캠 증설
  (서버 슬롯 부족), 로봇 추적 카메라(FollowCam — 구현했다가 사용자 결정으로
  제거, 렌더 부하만 늘었음).
- ⚠ 실물에서는 AMR 이 직접 POST 하므로 이 브리지는 시뮬 전용이다.

### 🚨 카메라가 로봇을 안 따라가던 버그 (사용자 발견)
대시보드의 AMR1 카메라에 **자기 자신이 지나가는 게** 찍혔다 — OcrCam·경광등을
로봇 **루트 Xform** 에 달았는데, 물리는 아티큘레이션 **링크**만 움직이고
루트는 저작 자세에 남는다. 물리 도입 전(루트를 직접 이동)에는 안 드러나던
잠복 버그. → `base_link` 링크 밑으로 이동 (`lot._amr`, 라이다를 base_scan
에 다는 것과 같은 이유). 카메라 프림 경로가
`/World/AMR{1,2}/base_link/OcrCam` 으로 바뀌었다.

### 출동 게이트 적용 (사용자 확정: 움직이는 로봇의 카메라만 표시)
`amr1_nav` 가 `/amr1/on_duty`(Bool) 를 임무 시작 True / 종료 False 로 발행
(피드백 5초 주기로도 반복 — 라칭 아님). 브리지는 둘 다 `--gate` 로 띄운다.
OcrCam 발행도 skip=11 (시뮬 5 Hz) 로 절감 — 해상도 유지라 품질 무손실.
rtf 실측: 카메라 3대(웹캠+OcrCam×2, 10 Hz) 시 0.20.

### 실차 치수 반영 (사용자 확정 "차량만") + 지도 재작성
`layout.VEHICLES`: SEDAN/EV 4.30→**4.70**(총고 1.45), COMPACT 1.60×3.60
(총고 1.45), FIRE 2.50×**7.50**×3.20 (FIRE_AREA 깊이 8.0 제약).
번호판(520×110)·TB3·주차면(일반 2.5×5.0/장애인 3.3×5.0)·선 두께 0.12 는
이미 실측 규격이라 그대로. 지도는 차가 장애물로 찍혀 있어 **재매핑**
(explore 완주 → 저장 → 유령 21px 정리 → 풋프린트 실측 대조: 세단 4.7 m·
소방구역의 EV 1.8×4.65 m ✓). ⚠ 차량 배치·크기가 바뀔 때만 재매핑이 필요.

### 🚨 그림자 필터 — 실차 높이로 웹캠 탐지가 깨졌다
차가 높아지자(총고 1.45) 그림자가 길어져 **빈 경차 칸(스톨 4)이 이웃 차
그림자에 덮여 오탐**됐다 (12/11건). 남쪽 띠 회피로는 부족 → 마스크에
그림자 제외를 추가: 렌더 실측으로 그림자 = **무채색(chroma ~9) + 중간
밝기**, 차체·캐빈 = 유채색(chroma ~30+), 바퀴 = v<40. 조건:
`chroma<16 ∧ 40<v<0.82·바닥밝기` 는 바닥 취급. 재검증 **11/11·오탐 0**,
관측 좌표도 그림자 부풀림이 빠져 정확해짐 (블록A 앞 x 11.9→11.3~11.5).
⚠ 무채색 회색 차체는 캐빈·바퀴로만 잡힌다 — seed 바꾸면 확인할 것.
⚠ 브리지 `_sent_coords` 캐시 함정 재확인: 탐지만 재시작하면 반올림이 같은
좌표가 스킵된다 — **브리지→탐지 순서로 둘 다** 재시작해야 한다.

### 🚨 Nav2 가 차량 사이 0.55 m 틈으로 파고들어 로봇이 낌 (2회)
벽쪽 2·3번 차 관측점(이웃 차 내부)으로 출동하다, 플래너가 매핑 때 틈
너머로 스캔된 빈 공간을 통로로 보고 차 사이로 경로를 냈다. 로봇(0.18 m)은
이론상 통과하지만 접촉 즉시 회전력이 죽어 탈출 불가 (wz 0.8 로 4분에 5°).
3중 수정:
1. **전역 코스트맵 robot_radius 0.28** (로컬은 실제 0.11 유지) — 0.55 m
   틈이 계획 단계에서 막힌 길이 됨. 실측으로 파고들기 차단 확인.
2. planner `allow_unknown: false` — 가림 영역(unknown) 통과 금지.
3. `amr1_nav.goal_blocked()` — 목표 주변 0.15 m 가 지도상 확실한 빈 공간이
   아니면 **이동 없이 스킵** (transient_local /map 라치 대기 포함).
구출은 cmd_vel 로 불가능해서 씬 재시작으로 리셋했다.

### 🚨 목표 수락 응답 유실 (DDS 레이스)
send_goal 후 bt_navigator 쪽에 "Failed to send goal response (timeout)" 만
남고 클라이언트는 영원히 대기 — 로봇이 출발도 안 한다 (사용자 발견).
→ 수락 응답 10초 타임아웃 + 3회 재전송 (NavigateToPose 는 새 목표가 이전
목표를 선점하므로 중복 전송 무해).

### ⚠ 팀 Supabase 스키마 분기 발견 (.env 추가 시점)
팀 DB 에는 이 저장소에 없는 마이그레이션 0013~0015 가 적용돼 있다 —
parking_events 에서 vehicle_type·zone_type **삭제**, vehicle_id 추가,
vehicle_info.ocr_image_path→ocr_image, amr_vehicle_x/y 삭제. 즉 팀 서버
코드가 이 저장소보다 최신. 사용자 결정으로 **sqlite 로 계속** (Django 를
`DB_HOST=` 빈값으로 기동, .env 는 유지). 팀 코드와 동기화 후 재검토.
서버 수정 1건: `ZoneUpdateSerializer` 의 zone_type choices 에 빠져 있던
COMPACT·EV 를 모델(ZONE_CHOICES)과 일치시킴 — 경차·전기차 구역 PATCH 가
400 으로 거부되던 버그.

### 구역·차종 판별 결과 ✅ — 11/11 시나리오 정답 일치
`sim/vision/zone_classify.py` + `amr1_nav.classify_here()` (도착 →
OcrCam 프레임 + odom 위치 → 판별 → `PATCH /api/parking/<id>/zone/`):

    이벤트  대상                판별                     정답   ✓
    57     벽쪽 남단           Not / ILLEGAL            불법   ✓
    61,58  벽쪽 가운데·북단     접근 불가 스킵/실패       (기하) ✓
    59     소방구역의 EV       FIRE / ILLEGAL (빨강 0px) 불법   ✓
    63,64  일반구역 2대        NORMAL / NORMAL 스킵      정상   ✓
    62,65  경차구역 SEDAN 2대  COMPACT / ILLEGAL         불법   ✓
    60     EV구역 EV          EV / NORMAL (파란판 8386px) 정상  ✓
    67     EV구역 SEDAN       EV / ILLEGAL (파란판 0px)  불법   ✓
    66     장애인구역 EV       DISABLED / 보류(OCR 단계)  미등록 ✓

판별 순서: 정면 주차면 탐색(사전 정의 좌표, ≤6 m·±25° — 도착 오차만큼만
여유) → 없으면 Not → 있으면 그 구역 + 색 교차검증 → 구역별 차종 판별.
- EV 파란 번호판 분리 완벽 (8386 vs 0 px).
- ⚠ car_width 측정 2.76 m (실제 1.8) — 어두운 하부 폭에 그림자가 섞여
  과대. 세단 불법 판정은 맞지만 경차(1.6)가 오면 오판 위험 — 그림자
  제외를 여기도 적용할 것 (seed 7 엔 경차구역에 경차가 없어 미검증).
- ⚠ 색 단독으로는 못 가른다 재확인: NORMAL 자리에서도 이웃 경차구역
  파란 선이 프레임에 더 많이 잡힘 (color_zone 은 로그용, 좌표가 우선).
