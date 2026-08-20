# Alley Park Patrol — 주차 단속 시스템

웹캠이 불법주차를 찾아내고 순찰 로봇 두 대가 차례로 출동해 번호판을 읽고
검증한 뒤 경보를 내리는 시스템. **Django 관제 서버 + Isaac Sim 시뮬레이션**
전체가 한 저장소에 들어 있다.

> 원본은 종이 판자 맵과 실물 TurtleBot4 2대로 진행한 팀 프로젝트였고 그 기간은
> 끝났다. 이 저장소는 그 시스템을 **혼자 Isaac Sim + TurtleBot3 로 다시 구현한
> 개인 작업**이다. 서버 API 는 팀 시절 규격을 그대로 유지하고, DB 는 sqlite 로 돈다.

시연 녹화: [`rehearsal5_20260819.mp4`](rehearsal5_20260819.mp4) — 탐지부터 경보까지 한 번에 완주한 리허설.

---

## 동작 흐름

```
[웹캠 + 탐지]        차량 탐지 → 관측 좌표 계산 → 이벤트 생성
      ↓                                              status = DETECTED
[AMR1 / Police 1]    Nav2 자율 출동 → 구역·차종 판별 → 불법이면 번호판 OCR
      ↓                                              status = SCANNED
[AMR2 / Police 2]    Nav2 자율 출동 → 번호판 재판독 → DB 대조 → 경보
                                                     status = WARNING_ISSUED
```

AMR1 단계에서 끝나는 갈래가 둘 있다. 그대로 `DETECTED` 로 두면
`/api/parking/next/` 가 같은 건만 무한 반환하므로 별도 상태로 종결한다.

| 종결 | 언제 |
|---|---|
| `CLEARED` | 정상 주차로 판정 → 스킵 (구역 PATCH 시 서버가 자동 전환) |
| `UNREACHABLE` | 관측점 접근 불가 → 출동 생략 (AMR1 이 명시적으로 PATCH) |

번호판 OCR 실패는 예외로 `DETECTED` 를 유지해 다음 순회에서 재방문한다.

서버는 좌표를 **한 번** 넘길 뿐 경로를 안내하지 않는다. 로봇이 Nav2 로 스스로
경로를 세운다.

---

## 구성

```
app/            Django 앱 — 모델 · API · 모니터 대시보드
config/         Django 설정
templates/      대시보드 · 로그인 화면
bridge/         ROS 2 ↔ 서버 브리지 (웹캠 프레임, 좌표 전달)

sim/            Isaac Sim 시뮬레이션
  scenes/         주차장 씬 — 형상 · 물리 · 번호판 · ROS 배선 (전부 코드로 생성)
  slam/           SLAM 지도 작성 + 완성된 지도(parking.pgm/yaml) + RViz 웹
  nav2/           Nav2 스택 · AMCL · AMR1/AMR2 출동 노드
  vision/         웹캠 차량탐지 · 구역 판별 · 번호판 OCR
  setup/          EC2 설치 · 셸 환경 · NVMe 캐시
  고시별표/        국토부 번호판 고시 원문 (번호판 규격의 출처)
```

---

## 문서

| 파일 | 내용 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **시스템 사양** — 단계별 동작, DB 스키마, API 엔드포인트 전체 |
| [`sim/README.md`](sim/README.md) | **시뮬 환경** — Isaac Sim 설치·실행, 씬 구조, 밟은 함정과 원인 |
| [`sim/PROGRESS.md`](sim/PROGRESS.md) | 완료 항목 요약 · 알려진 공백 · **재시작 절차** |
| [`sim/WORKLOG.md`](sim/WORKLOG.md) | 세션별 상세 기록 |
| [`sim/OCR_PLATE_FONT.md`](sim/OCR_PLATE_FONT.md) | 번호판 서체·규격 조사 |
| [`SETUP.txt`](SETUP.txt) | 팀 시절 서버 세팅 가이드 (Supabase 기준) |

---

## 실행

서버만 띄우려면:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
DB_HOST= python manage.py runserver 0.0.0.0:8000
```

- 대시보드 `http://<서버IP>:8000/monitor/` (user / password)
- API 문서 `http://<서버IP>:8000/api/schema/swagger-ui/`

`DB_HOST=` 를 빈값으로 주면 sqlite 로 뜬다. Supabase 등 외부 DB 를 쓰려면
`.env` 에 `SECRET_KEY` · `DB_*` 를 채운다 (`.gitignore` 에 있어 저장소에는 없다).

시뮬 전체(씬 · SLAM · Nav2 · OCR)를 돌리는 순서는
[`sim/PROGRESS.md`](sim/PROGRESS.md) 의 **다음 세션 시작 절차**에 있다.
Isaac Sim 설치는 `./sim/setup/install.sh`.

---

## 검증된 결과 — 통짜 리허설 5

클린 DB 에서 단일 순회로 전 구간을 완주한 기록이다 (seed 7, 11대 배치).

| 단계 | 결과 |
|---|---|
| 웹캠 탐지 | **11/11** 대 탐지, 오탐 0 |
| AMR1 구역·차종 판별 | **11/11** 시나리오 정답 일치 (SCANNED 7 / CLEARED 3 / UNREACHABLE 1) |
| 번호판 OCR | **7/7** 전부 1회 성공 (EasyOCR 2단계, 장당 35 ms) |
| AMR2 검증 | **7/7** 매치 → `WARNING_ISSUED` → 복귀 완료 |
| 국지화 | AMCL (정적 TF 우회 제거, 보정량 0.24~0.27 m) |

번호판은 국토부 고시 별표 원문의 셀 배분·잉크 높이·글리프를 그대로 재현했다.
실제 서체가 들어가자 tesseract 가 43/70 으로 무너져 EasyOCR 2단계로 교체했고
70/70 이 됐다.

## 알려진 한계

- **차량 이탈 처리 없음** — DELETE API 호출이 없어 차가 떠나도 이벤트가 남고
  같은 자리 재탐지가 안 된다. 고정 배치 시연에는 지장 없다.
- **벽쪽 세로주차 1대 접근 불가** — 차 간격 0.1 m 라 남·북 관측점이 둘 다 이웃
  차 몸통에 걸린다. `UNREACHABLE` 로 종결해 흐름은 막지 않는다.
- **경차 차폭 판정 마진이 3.3 mm** — 픽셀→미터 환산이 "판에서 2 m" 를 전제로
  하는데 실제 정차 거리는 더 가깝다. depth 로 실제 거리를 읽어 환산하면 상쇄될
  것으로 보이나 미해결이며, seed 7 에 진짜 경차가 없어 임계 아래쪽은 미검증이다.

---

## 환경

| | |
|---|---|
| OS | Ubuntu 22.04.5 LTS (AWS g5.2xlarge, NVIDIA A10G) |
| Isaac Sim | 6.0.1.0 (python 3.12) |
| ROS 2 | Humble (python 3.10), `ROS_DOMAIN_ID=2` |
| 백엔드 | Django 5.2.15 + DRF |
| OCR | EasyOCR (별도 venv — Isaac 쪽 torch 를 건드리면 안 된다) |

파이썬이 3.12(Isaac)와 3.10(ROS)으로 나뉘어 있어 터미널을 구분해 쓴다.
자세한 이유와 별칭은 [`sim/README.md`](sim/README.md) 참고.
