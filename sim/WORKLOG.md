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
