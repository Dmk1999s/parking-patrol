# sim/ — Isaac Sim + WebRTC 스트리밍

주차 단속 시스템을 Isaac Sim 위에 올리기 위한 환경. `pipe_repair_robot_IsaacSim`
에서 쓰던 **WebRTC 스트리밍 방식**을 이 프로젝트로 옮긴 것이다.

디스플레이가 없는 EC2 에서 Isaac Sim 을 띄우고, 화면은 전용 클라이언트로 본다.

## 상태 — 여기까지 실제로 확인했다

| | |
|---|---|
| Isaac Sim 6.0.1.0 기동 | ✅ A10G / Vulkan / RTX, GPU 가속 확인 |
| 드라이버 교체 | ✅ **불필요** (5.1 기록과 다름 — 아래 참고) |
| WebRTC 자동 스트리밍 | ✅ TCP 49100 리슨, 퍼블릭 IP 자동 인식 |
| 주차장 씬 | ✅ 6칸 · 차량 3대 · AMR 2대, 렌더·캡처·USD 내보내기 |
| 순찰 로봇 | ✅ TurtleBot3 Burger (Isaac 번들 자산) + 번호판 촬영 카메라 |
| 번호판 OCR | ✅ 2 m 에서 tesseract 가 `34나5678` 정확히 읽음 |
| Isaac 쪽 rclpy | ✅ `isaac_ros` 후 `rclpy` · `sensor_msgs` · `std_msgs` · `visualization_msgs` import 확인 (python 3.12, 도커 빌드 불필요) |
| 물리 (콜라이더·중력·마찰) | ✅ 바닥·벽·차량 정적 콜라이더, TB3 캐스터 보정 (아래 참고) |
| 차동구동 | ✅ `/amr1/cmd_vel` 로 실주행 확인 — v 는 명령과 일치 |
| RTX 라이다 `/scan` | ✅ 3600점 · 360° · 20 m, Humble 쪽에서 수신 확인 |
| `/odom` · `/tf` · `/clock` | ✅ `amr{1,2}/odom → base_link → base_scan` 두 트리 |
| SLAM (slam_toolbox) | ✅ `sim/slam/` — 순찰 드라이버로 지도 작성, `maps/` 에 저장 |
| Nav2 | ⬜ 다음 단계 — 지도 위에서 돈다 |
| 웹캠 → 웹 스트리밍 | ✅ 씬 → ROS → `bridge_webcam.py` → Django MJPEG. 브라우저에서 보인다 |
| 웹캠 좌표(MarkerArray) 발행 | ⬜ 아직 — 차량탐지 로직과 같이 붙인다 |
| Django `.env` | ✅ 로컬 sqlite 폴백으로 뜬다. 팀 Supabase `.env` 를 받으면 자동 전환 |

```
sim/
  setup/
    install.sh          설치 (멱등 — 이미 돼 있으면 건너뛴다)
    env.sh              셸 환경. ~/.bashrc 에서 source 한다
    nvme_cache.sh       캐시를 로컬 NVMe 로 빼서 EBS 절약
    pyver.py            어느 파이썬으로 돌아야 하는 코드인지 못박는다
  tools/isaac_autostream/
    sitecustomize.py    SimulationApp 을 가로채 스트리밍을 자동으로 켠다
    livestream.py       WebRTC 설정 한 곳         ← 둘은 한 몸이다. 갈라 두지 말 것
  scenes/
    layout.py           배치 + 랜덤 배정 (Isaac 없이 python3 로 돈다)
    lot.py              주차장 형상 + 물리 (순수 USD)
    markings.py         휠체어 바닥 표시 텍스처
    plate.py            번호판 텍스처
    ros_bridge.py       ROS 2 배선 (OmniGraph) — 라이다·주행계·차동구동
    parking_lot.py      확인용 씬 — 화면이 나가는지 보는 것이 목적 (물리 없음)
    patrol.py           순찰 씬 — 물리·라이다·차동구동이 도는 판. SLAM 은 여기서
```

---

## 이 환경의 구성

| | |
|---|---|
| OS | Ubuntu 22.04.5 LTS |
| GPU | NVIDIA A10G 23GB (g5.2xlarge) |
| Isaac Sim | **6.0.1.0** (pip, python **3.12**) |
| ROS 2 | **Humble** (시스템 python **3.10**) |
| 디스크 | EBS 146G (영구) + 로컬 NVMe 412G (휘발) |

### 왜 Isaac 6.0 인데 ROS 는 Jazzy 가 아닌가

**팀 로봇이 Humble 이기 때문이다.** `bridge/bridge_webcam.py` · `bridge_amr1.py`
와 AMR1/AMR2 가 전부 Humble 위에서 돈다. Humble↔Jazzy 는 공식 지원 조합이 아니라
섞으면 토픽이 안 통할 수 있다.

그리고 애초에 **Ubuntu 22.04 에는 Jazzy 가 없다** — ROS 2 저장소가 jammy 에 주는
것은 humble / iron / rolling 뿐이다. Jazzy 는 Ubuntu 24.04 전용이다.

Isaac Sim 6.0 은 **humble 과 jazzy 를 둘 다 번들로 갖고 있고**, humble 쪽이
python 3.12 용으로 빌드돼 있다(`*-py3.12.egg-info` 로 확인). 그래서 6.0 + Humble
은 버전 불일치가 아니라 지원되는 조합이다.

> 24.04 + Jazzy 로 가면 시스템 파이썬이 3.12 라 Isaac 과 하나로 합쳐져 훨씬
> 단순해진다. 팀 전체가 24.04 로 옮길 때 다시 검토할 것.

---

## 🚨 Isaac Sim 5.1 → 6.0 에서 바뀐 것 (실측)

파이프 프로젝트 문서(`docs/SETUP_EC2.md`)는 **5.1 기준**이다. 그대로 옮기면
동작하지 않는다. 실제로 확인한 차이는 아래와 같다.

| | 5.1 | **6.0** |
|---|---|---|
| Python | 3.11 | **3.12** |
| 스트리밍 확장 | `omni.kit.livestream.webrtc` | **`omni.kit.livestream.app`** |
| 시그널링 포트 | `/app/livestream/port` | `/exts/omni.kit.livestream.app/primaryStream/signalPort` |
| 퍼블릭 IP | `/app/livestream/publicEndpointAddress` | `.../primaryStream/publicIp` |
| 미디어 포트 | `minHostPort`~`maxHostPort` (범위) | `.../primaryStream/streamPort` (하나) |
| 자동 종료 함정 | `omni.services.livestream.nvcf` | `omni.services.livestream.session` |
| 번들 rclpy | `exts/isaacsim.ros2.bridge/humble/` | **`exts/isaacsim.ros2.core/humble/`** |
| 번들 ROS 배포판 | humble | humble **+ jazzy** |

### ⚠ 옛 설정 경로를 써도 오류가 안 난다

carb 은 모르는 설정 키도 그냥 받는다. 그래서 5.1 코드를 그대로 가져오면
**"설정은 분명히 했는데 기본 포트로 열리는"** 증상이 된다. 오류가 없어서
원인을 찾기 어렵다. 같은 이유로 `isaac_ros` 가 없는 경로를 PYTHONPATH 에
넣어도 조용히 무시된다.

### 🚨 `isaacsim[all]` 만으로는 안 뜬다

`pip install isaacsim[all]==6.0.1.0` 은 필요한 패키지를 **다 가져오지 않는다.**
빠진 것을 따로 깔아야 한다:

```
isaacsim-robot-schema        isaacsim.anim.robot.schema 를 제공.
                             없으면 의존성 해결 실패로 앱이 즉시 종료된다
isaacsim-extscache-kit       확장 캐시 (5.9 GB)
isaacsim-extscache-kit-sdk   확장 캐시
isaacsim-extscache-physics   확장 캐시
```

증상은 이렇게 나온다 — **드라이버 문제로 착각하기 쉽다**:

```
Failed to solve some dependencies locally, syncing with extension registry...
[Error] No versions of isaacsim.anim.robot.schema that satisfies:
        isaacsim.exp.base-6.0.1 depends on isaacsim.anim.robot.schema version *
        - Available packages: (none found)
[Error] Exiting app because of dependency solver failure...
```

`install.sh isaac` 가 이 넷을 같이 깐다.

---

## 설치

```bash
./sim/setup/install.sh          # driver 를 뺀 전부
./sim/setup/install.sh check    # 상태만 점검
```

`check` 는 6.0 에서 바뀐 것들(experience 이름 · 스트리밍 확장 · 번들 rclpy)을
**실제 디스크에서 찾아 찍어 준다.** 버전을 올렸을 때 여기부터 본다.

### ✅ GPU 드라이버 — 6.0 에서는 교체가 필요 없다 (실측)

파이프 프로젝트(5.1)는 **AWS DLAMI 기본 드라이버(595 계열)로는 Isaac Sim 이
첫 프레임에서 반드시 세그폴트한다**고 기록하고 있다. 연산용(datacenter)
드라이버라 `nvidia-drm.ko` 가 없고 `/dev/dri/renderD128` 이 안 생긴다는 것이
이유였다. 그래서 GRID 580.65.06 으로 교체 + 재부팅이 필요했다.

**Isaac Sim 6.0.1.0 에서는 그렇지 않다.** 이 환경에서 그대로 확인했다:

```
드라이버 595.91.07 / nvidia_drm 미로드 / /dev/dri/renderD128 없음
  → 20 프레임 렌더 성공, 세그폴트 없음
  → NVIDIA A10G | Active: Yes:0 | 23028 MB | Graphics API: Vulkan
  → omni.hydra.rtx 로드됨, cuda:0 "NVIDIA A10G" (22 GiB, sm_86)
  → 씬 캡처 PNG 정상 (그림자·머티리얼 전부 나옴) — 소프트웨어 폴백 아님
```

headless 라 `GLFW initialization failed` 와 `carb.audio ... eDeviceLost` 경고가
뜨지만 **정상이다** (창도 오디오 장치도 없는 게 맞다).

> `driver` 단계는 그대로 남겨 두었다. 다른 드라이버 조합에서 세그폴트가 나면
> 그때 쓴다. 지금 이 환경에서는 **돌릴 필요가 없다.**

```bash
./sim/setup/install.sh driver   # 필요할 때만. GRID 580.65.06 으로 교체 + 재부팅
```

---

## 실행

```bash
isaac_ros                                              # rclpy 경로 (ROS 를 쓸 때)
PYTHONUNBUFFERED=1 isaac_python sim/scenes/parking_lot.py
```

`isaac_python` 이 `sim/tools/isaac_autostream` 을 PYTHONPATH 앞에 끼운다.
파이썬은 본문을 실행하기 전에 거기 있는 `sitecustomize.py` 를 읽는데, 그 파일이
`SimulationApp` 을 가로채 스트리밍을 켠다. **씬 코드는 한 줄도 안 고쳐도 된다.**

```bash
ISAAC_STREAM=0 isaac_python <씬>    # 스트리밍 끄기 (배치로 산출물만 뽑을 때)
```

### 씬은 USD 파일이 아니라 **코드로 만든다**

`scenes/lot.py` 가 실행 시점에 `pxr` API 로 도형을 쌓는다 — `UsdGeom.Cube`
(바닥·주차선·차체), `UsdGeom.Cylinder`(바퀴·AMR), `UsdLux`(조명),
`UsdGeom.Camera`(웹캠). **외부 자산을 하나도 안 읽는다.**

Isaac Sim 의 기본 로봇·소품은 NVIDIA CDN 에서 받아 오는데, 그 경로가 막히거나
느리면 씬이 자산을 기다리다 멈춘 것처럼 보인다. 확인용 씬에서 그런 변수를
빼려고 전부 기본 도형으로 만들었다.

필요하면 `.usd` 로 굽는다 (도형뿐이라 9 KB 밖에 안 된다):

```bash
ISAAC_STREAM=0 isaac_python sim/scenes/parking_lot.py --save out.usd
ISAAC_STREAM=0 isaac_python sim/scenes/parking_lot.py --shot out.png  # 한 장 찍기
```

`--shot` 은 WebRTC 클라이언트를 붙이지 않고도 씬이 제대로 그려지는지 볼 때 쓴다.

### 주차장 배치

`lot.py` 의 `STALLS` 를 고치면 배치가 바뀐다. 지금은 6칸이다:

```
0 NORMAL(은색 차)  1 NORMAL(빔)  2 DISABLED(빔)
3 FIRE(빨간 차 ← 불법주차)      4 NORMAL(남색 차)  5 NORMAL(빔)
```

구역 색은 `app/models.py:4` 의 `ZONE_CHOICES` 를 따른다 — 주황(NORMAL) ·
파랑(DISABLED) · 빨강(FIRE). AMR1 이 "주황색 주차선"을 보면 정상으로 판단하고
스킵하는 로직(`CLAUDE.md` 2단계)이 여기 대응한다.

### 순찰 로봇 — TurtleBot3 Burger

Isaac 번들 자산을 reference 로 얹는다
(`Isaac/Robots/Turtlebot/Turtlebot3/turtlebot3_burger.usd`). 실측 치수
0.138 × 0.178 × 0.191 m, 바퀴 반지름 0.033 m, `wheel_left_joint` /
`wheel_right_joint` 두 개가 RevoluteJoint 라 차동구동을 바로 붙일 수 있다.

> TurtleBot**4** 는 Isaac 자산 라이브러리에 없다. Burger 와 iRobot Create 3
> 만 있다. TB4 가 꼭 필요하면 `turtlebot4_description` 의 URDF 를
> `isaacsim.asset.importer.urdf` 로 임포트해야 한다.

🚨 이 자산만 **원격**이다 (NVIDIA CDN). 씬의 나머지는 코드로 만들어 외부
의존이 없다. 네트워크가 막힌 곳에서는 파일을 받아 두고 경로를 준다:

```bash
PATROL_TB3_USD=/path/to/turtlebot3_burger.usd isaac_python ...
```

Burger 에는 카메라가 없어서(LDS-01 라이다만 있다) 번호판 촬영용으로 직접
단다 — `OcrCam`, 높이 0.20 m, 위로 6° 기울임.

### 번호판 — 코드로 굽는다

`scenes/plate.py` 가 문자열 하나로 PNG 를 만들고, `lot.py` 가 차 뒷면에
붙인다. **이미지를 미리 만들어 두지 않는 이유**는 번호가 Django
`vehicle_info.plate_number` 와 같아야 하기 때문이다 — 미리 구워 두면 둘이
갈라지고, 번호를 바꿀 때마다 이미지를 다시 만들어야 한다.

`lot.STALLS` 의 세 번째 값이 번호판 문자열이다. 한글이 필요하므로:

```bash
sudo apt-get install -y fonts-nanum      # 없으면 한글이 □ 로 나온다
```

#### 실측 — 2 m 에서 OCR 이 읽는다

```
AMR1 을 3번(FIRE) 주차면 촬영 위치에 세우고 OcrCam 으로 찍은 뒤 tesseract:
  번호판이 화면에서 차지하는 크기   275 × 70 px  (1280×720 프레임)
  tesseract -l kor+eng --psm 7    →  "34나5678"   ✅ 정확
```

```bash
isaac_python sim/scenes/parking_lot.py --amr1-stall 3 \
    --cam /World/AMR1/OcrCam --shot ocr.png
```

거리와 화각이 결과를 좌우한다. 두 가지가 실제로 발목을 잡았다:

- 🚨 **초점거리만 정하면 화각이 안 정해진다.** USD 카메라는
  `화각 = 2·atan(가로조리개 / 2·초점거리)` 이고 **가로 조리개 기본값이
  20.955 mm** 다. 초점거리 24 를 주면 화각이 47° 라 2 m 앞 차가 화면을 꽉
  채운다. 로봇 카메라에 흔한 69° 로 맞추려면 초점거리 15.2 다.
- 🚨 **확대하면 오히려 나빠진다.** 잘라낸 번호판을 3배로 키워 넣었더니
  `3415678` 로 `나` 를 놓쳤다. 원본 해상도 그대로 넘길 것.

`approach_pose(stall, dist=2.0)` 이 돌려주는 값이 곧 Django
`parking_events.observation_x / observation_y` 다. 이 함수에서 **두 번 틀렸다** —
둘 다 오류가 안 나서 렌더를 눈으로 봐야 드러났다:

- 🚨 **AMR 이 반대쪽을 봤다.** AMR 카메라는 로컬 +Y 를 본다. yaw 를 "차가 어느
  쪽을 보는가" 로 잡으면 뒤집힌다 — AMR 이 통로 **건너편** 차를 찍었는데,
  번호판이 또렷하게 나와서 오히려 정상처럼 보였다(엉뚱한 차의 번호판이었다).
- 🚨 **거리를 주차면 깊이로 계산했다.** 차는 주차면 **한가운데**에 놓이므로
  번호판은 주차면 중심에서 차 길이의 절반만큼 나와 있다. 깊이로 계산했더니
  AMR 이 차에서 0.19 m 앞에 서서 **차 밑바닥만** 찍었다.

## 구역 색 — OpenCV 임계값

`layout.ZONES` 의 RGB 를 그대로 쓰면 안 된다. **조명이 세면 채널이 포화되며
색상(H)이 밀린다** — 소방차 주황을 (0.98,0.55,0.10) 으로 뒀더니 렌더에서
H=52° **노랑**으로 나왔다(RGB 238,224,139). AMR 이 색으로 구역을 판별하는데
노랑으로 읽히면 판별이 틀린다. 그래서 색을 어둡게 잡고 조명을 낮췄다.

오버헤드 웹캠 렌더에서 실측한 값이다. **OpenCV 의 H 는 0~180 이라 절반**이다:

| 구역 | 선 색 | 실측 H (0~360) | OpenCV H (0~180) | 비고 |
|---|---|---|---|---|
| `FIRE` | 주황 | 30 ~ 45 | **15 ~ 23** | S>0.6 |
| `EV` | 초록 | 135 ~ 165 | **68 ~ 83** | |
| `COMPACT` / `DISABLED` | 파랑 | 195 ~ 225 | **98 ~ 113** | 둘이 **같은 색** |
| `NORMAL` | 흰색 | — | — | 채도 S<0.2 로 거른다 |

🚨 **경차와 장애인 구역은 색이 같다** (지도에서 둘 다 파란 선). 색으로는 절대
   안 갈린다 — **휠체어 표시**(`markings.py` 가 굽는 바닥 텍스처)로만 구분된다.

> 이 값은 **오버헤드 웹캠 시점** 기준이다. AMR 카메라는 각도와 거리가 달라
> 밝기(V)가 다르게 나온다. 분류기를 붙일 때 AMR 시점에서 다시 재는 게 좋다.

### 화면 보기 — 브라우저로는 안 된다

`omni.kit.livestream.app` 은 백엔드 전용이고 HTML 클라이언트가 없다. 49100 은
웹페이지가 아니라 **WebSocket 시그널링 포트**라 브라우저로 열면 아무것도 안 나온다.

→ NVIDIA 가 배포하는 **Isaac Sim WebRTC Streaming Client**(데스크톱 앱)를 쓴다.
   앱의 주소 칸에 **IP 만** 넣는다 — 포트도 `http://` 도 붙이지 않는다.

```bash
isaac_pubip     # 지금 퍼블릭 IP. 씬이 뜰 때도 화면에 찍는다
```

### 보안그룹에서 열어야 하는 포트

| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 49100 | TCP | WebRTC 시그널링 (websocket) |
| 47998–48020 | UDP | 미디어 스트림 |

### ⚠ 두 개를 동시에 띄우지 말 것

WebRTC 시그널링 소켓은 SO_REUSEPORT 로 열려서 두 프로세스가 **오류 없이** 동시에
49100 을 리슨한다. 커널이 접속을 둘에 나눠 주므로 클라이언트가 엉뚱한 쪽에 붙어
"아무것도 안 뜨는" 증상이 된다. `sitecustomize.py` 가 이미 리슨 중이면 건너뛴다.

```bash
pgrep -af "isaacsim_venv/bin/python"
```

### ⚠ 퍼블릭 IP 는 하드코딩하지 않는다

EIP 가 없어 정지·시작할 때마다 주소가 바뀐다. 옛 IP 가 박혀 있으면 시그널링은
붙는데 ICE 후보가 옛 주소라 **영상이 영영 안 뜬다**(검은 화면). 그래서 실행
시점에 IMDS 에서 읽는다. 강제하려면 `ISAAC_PUB_IP=1.2.3.4 isaac_python ...`

---

## 물리 + 라이다 + 차동구동 (patrol.py)

```bash
isaac_python sim/scenes/patrol.py                  # ROS 2 + WebRTC
isaac_python sim/scenes/patrol.py --drive 0.15     # ROS 없이 물리만 자체 점검
```

| 토픽 | 타입 | 방향 |
|---|---|---|
| `/clock` | Clock | 발행 (하나만) |
| `/amr1/scan` `/amr2/scan` | LaserScan | 발행 — 3600점 · 360° · 20 m |
| `/amr1/odom` `/amr2/odom` | Odometry | 발행 |
| `/tf` | TFMessage | 발행 — `amr{1,2}/odom → base_link → base_scan` |
| `/amr1/cmd_vel` `/amr2/cmd_vel` | Twist | **구독** — Nav2/teleop 이 여기로 |

토픽은 네임스페이스로, 프레임은 접두사로 가른다. `/tf` 는 하나로 모은다.
Humble 쪽에서 확인 (ROS_DOMAIN_ID=2):

```bash
ros2 topic pub -r 10 /amr1/cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.15}, angular: {z: 0.2}}"     # AMR1 이 호를 그리며 돈다
```

여기까지 오는 데 **오류 없이 조용히 실패하는 함정**이 셋 있었다. 전부 코드가
자동으로 처리하지만, 알아야 다음에 안 헤맨다:

### 🚨 1. ROS 브리지는 LD_LIBRARY_PATH 가 없으면 조용히 죽는다

`isaacsim.ros2.bridge` 는 번들 C 라이브러리(`librcutils.so` 등)를 dlopen 하는데
경로가 없으면 로그에 `ROS2 Bridge startup failed` 한 줄 남기고 **확장은 enabled
로 남는다.** 그래프도 오류 없이 만들어지고, 그냥 토픽만 안 나온다.
→ `pyver.ensure_ros2_libs()` 가 경로를 넣고 프로세스를 재실행한다.
  `patrol.py` 가 SimulationApp 을 만들기 **전에** 부른다 (그 뒤에는 늦다).

### 🚨 2. TB3 자산은 그대로 두면 굴러가지 않는다

바퀴는 명령대로 도는데 로봇이 1 mm 도 안 나갔다. PhysX 접촉 리포트를 찍어 보니
바닥을 딛는 게 바퀴가 아니라 **캐스터 박스와 base_link 박스**였다 — 캐스터
콜라이더가 저작 자세에서 이미 바닥을 4 mm 뚫고 들어가 있어서, 시작하자마자
뒤가 밀려 올라가고 하중이 박스에 실려 바퀴가 헛돈다.
→ `lot._fix_tb3_physics()` 가 캐스터를 4 mm 올리고(밑면 = 바퀴 밑면 = z 0),
  캐스터 마찰 0(combine=min) · 바퀴 고무(마찰 1.0)를 바인딩한다.

### 🚨 3. 실린더 콜라이더 기본값은 접촉이 위치 따라 안 생긴다

같은 로봇이 (3.2,-3)에서는 멀쩡한데 (1.2,-3)에서는 바퀴 접촉이 안 생겨 4.4°
기운 채 주저앉았다. PhysX 커스텀 지오메트리 실린더의 접촉 생성 결함이다.
→ `patrol.py` 가 `/physics/collisionApproximateCylinders=true` (컨벡스 근사)
  를 물리 파싱 전에 넣는다.

### 알아 둘 것

- **라이다는 콜라이더가 아니라 보이는 형상에 광선을 쏜다.** 물리(충돌)와
  센서(가시성)는 완전히 별개다. 차체가 바퀴 높이(z 0.2475)에서 시작하면 스캔
  평면(z 0.18)이 차 밑을 지나가 차가 지도에 안 찍힌다 — 그래서 `lot.py` 가
  사이드실(`Rocker`)로 차체를 z 0.10 까지 이어 붙인다.
- **라이다 사거리는 실물(LDS-01 3.5 m)이 아니라 20 m 다.** 주차장이 32×23 m 라
  3.5 m 로는 SLAM 이 끊긴다. 실물로 옮길 때 유의. `PATROL_LIDAR_RANGE=3.5` 로
  되돌릴 수 있다.
- **OcrCam 이 로봇 진행 방향(로컬 +X)을 본다.** 물리 이전에는 +Y 를 봤다.
  ROS yaw 와 카메라 방향이 일치해야 Nav2 목표 pose 로 세웠을 때 카메라가
  대상을 본다. `approach_pose` 의 yaw 도 그에 맞춰 +90° 됐다.
- **`OnPlaybackTick` 은 재생 중일 때만 깨어난다.** 타임라인이 멈춰 있으면
  그래프가 통째로 안 돌아 토픽이 하나도 안 나온다. `patrol.py` 는 뜨자마자
  `play()` 를 건다.
- 회전(각속도)은 명령보다 조금 덜 나온다 (실측 w 0.3 명령 → ~0.17). 컨벡스
  근사 바퀴의 접촉 특성 때문으로 보인다. Nav2 는 `/odom` 폐루프라 문제가
  안 되지만, 개루프로 각도를 맞추려 하면 틀어진다.

---

## SLAM — 지도 작성 (sim/slam/)

4개를 각각 띄운다 (전부 백그라운드 가능):

```bash
# 1. Isaac 씬 (스트리밍 켠 채 — WebRTC 클라이언트로 로봇이 보인다)
isaac_python sim/scenes/patrol.py --cam /World/Webcam1

# 2~4. ROS 쪽 (각각 patrol_ros 한 터미널에서)
ros2 run slam_toolbox async_slam_toolbox_node \
    --ros-args --params-file sim/slam/slam_params.yaml
python3 sim/slam/map_snapshot.py --out /tmp/parking_map   # 지도 → PNG
python3 sim/slam/explore_amr1.py                          # 순찰 드라이버

# 끝나면 지도 저장 (Nav2 가 읽는 pgm+yaml)
ros2 run nav2_map_server map_saver_cli -f sim/slam/maps/parking \
    --ros-args -p use_sim_time:=true
```

`explore_amr1.py` 는 Nav2 없이 odom 폐루프 P 제어로 웨이포인트를 돈다 —
지도를 만드는 중이라 지도가 필요한 Nav2 를 쓸 수 없기 때문이다. 경로는 차량
배치와 무관하게 항상 비어 있는 통로만 지나가고, 마지막에 북쪽 띠를 되짚어
**루프를 닫는다**.

### RViz — 브라우저로 띄운다 (rviz_web.sh)

이 EC2 는 헤드리스라 RViz 창을 만들 곳이 없다. 대신 **가상 디스플레이(Xvfb)에
진짜 RViz2 를 띄우고 noVNC 로 브라우저에 내보낸다** — Isaac 의 WebRTC 와 같은
발상이다:

```bash
./sim/slam/rviz_web.sh          # 띄우기
./sim/slam/rviz_web.sh stop     # 내리기
```

브라우저에서 `http://<EC2 퍼블릭IP>:6080/vnc.html` → **Connect**.
지도(/map) · AMR1 스캔 · TF 가 표시된다 (`sim/slam/patrol.rviz`).

- ⚠ 보안그룹에 **TCP 6080**. (VNC 5900 은 localhost 전용으로 잠가 뒀다 —
  열지 말 것.)
- rviz 는 소프트웨어 렌더링(llvmpipe)으로 돈다 — GPU 는 Isaac 이 쓰고 있다.
  뜰 때 `indexed_8bit_image` GLSL 오류가 한 줄 나오는데 **무해하다** (지도
  정상 표시 확인).
- 마우스 드래그로 이동, 휠로 줌 — 보통 RViz 그대로다.

다른 방법들:

**① Foxglove Studio (권장 — 사실상 원격 RViz)**

서버에서 브리지를 띄운다:

```bash
ros2 run foxglove_bridge foxglove_bridge \
    --ros-args -p port:=8765 -p use_sim_time:=true
```

내 PC 에서 **Foxglove Studio 데스크톱 앱**(foxglove.dev 에서 다운로드)을 열고
→ *Open connection* → `ws://<EC2 퍼블릭IP>:8765`.
3D 패널을 추가하면 `/map` · `/amr1/scan` · `/tf` 가 RViz 처럼 실시간으로 보인다.
표시 프레임(display frame)은 `map` 으로 둔다.

- ⚠ 보안그룹에 **TCP 8765** 를 열어야 한다 (WebRTC 포트 열던 곳과 같다).
- ⚠ 브라우저판(app.foxglove.dev)은 https 페이지에서 ws:// 를 막아 안 붙는다.
  **데스크톱 앱**을 쓸 것.

**② 지도 스냅샷 PNG**

`map_snapshot.py` 가 `/map` 을 20초마다 `<out>_latest.png` 로 굽는다.
빨간 점이 로봇이다. 흰=빈 공간 · 검=장애물 · 회=미탐사.

**③ Isaac Sim WebRTC 클라이언트**

지도가 아니라 **씬 자체**(로봇이 실제로 도는 모습)를 본다. 늘 하던 방식.

**④ 웹 브라우저 — Django 웹캠 스트림 (설치 필요 없음)**

씬의 오버헤드 웹캠이 기존 파이프라인(`bridge_webcam.py` → Django)을 그대로
타고 웹에 나온다. 서버 쪽 코드는 안 고쳤다 — 씬이
`webcam_images/webcam1/detections` 를 발행하게 한 것뿐이다:

```bash
patrol_run                                            # Django (sqlite 폴백)
PATROL_SERVER=http://127.0.0.1:8000 python3 bridge/bridge_webcam.py
```

브라우저에서:

    http://<EC2 퍼블릭IP>:8000/api/webcam1/stream/    ← 로그인 없이 MJPEG
    http://<EC2 퍼블릭IP>:8000/monitor/               ← 대시보드 (user / password)

- ⚠ 보안그룹에 **TCP 8000** 을 열어야 한다.
- 씬 쪽 발행을 끄려면 `--no-webcam`. 해상도·주기는 `ros_bridge.webcam_graph`.
- 브리지의 서버 주소는 `PATROL_SERVER` 환경변수로 바꾼다 (기본은 팀 서버
  `192.168.107.42` — 시뮬 EC2 에서는 localhost 로 줘야 한다).

> 실측: 스트리밍 + RTX 라이다 2대를 켠 채로는 시뮬이 실시간의 ~25% 로 돈다.
> SLAM 은 /clock 기준이라 결과에는 지장 없다 — 그냥 오래 걸릴 뿐이다.
> 급하면 `ISAAC_STREAM=0` 으로 띄우면 빨라진다 (대신 실시간 화면은 포기).

---

## 터미널을 두 가지로 나눠 쓴다

**파이썬이 두 개다.** Isaac Sim 6.0 은 3.12, ROS 2 Humble 은 3.10 이고 확장 모듈
ABI 가 달라 서로의 라이브러리를 못 읽는다.

| 별칭 | 하는 일 |
|---|---|
| `patrol_ros` | ROS 2 Humble 소싱 (python 3.10) — `bridge/` 노드용 |
| `isaac_ros` | Isaac 번들 rclpy 경로 (python 3.12) — **여기서 `patrol_ros` 를 쓰면 안 된다** |
| `isaac_python` | Isaac 쪽 python 3.12 — WebRTC 스트리밍이 자동으로 켜진다 |
| `isaac_stream` | 빈 Isaac Sim 앱을 스트리밍으로 |
| `patrol_run` | Django 서버 (0.0.0.0:8000) |
| `pyver` | 지금 터미널이 어느 쪽인지 |
| `nvme_status` | 캐시가 NVMe 로 가 있는지 |

`LD_LIBRARY_PATH` 는 **앞에** 붙여야 한다. 뒤에 붙이면 `/opt/ros/humble/lib` 이
먼저 잡혀 3.12 rclpy 가 3.10 용 `librcl_logging_spdlog.so` 를 물고
`undefined symbol` 로 죽는다.

### ROS_DOMAIN_ID 는 2 다

`bridge/bridge_amr1.py:40` 이 import 전에 `os.environ['ROS_DOMAIN_ID']='2'` 로
직접 넣는다. 다르면 **오류 없이 토픽이 안 보인다.**

---

## 디스크 배치

```
EBS  146G (영구)    OS · Isaac Sim · 프로젝트 · Django venv
NVMe 412G (휘발)    셰이더 캐시 · Kit 로그 · 크래시덤프 · export
```

로컬 NVMe 는 공짜고 gp3 보다 빠르다. 다만 **stop → start 하면 통째로 비워진다**
(reboot 은 살아남는다). 그래서 Isaac Sim 본체는 EBS 에 두고, 다시 만들어지는
것만 NVMe 로 뺀다.

```bash
nvme_status                        # 상태 확인
./sim/setup/nvme_cache.sh setup    # 다시 걸기
```

NVMe 가 비워지면 링크가 **깨진 링크**가 되는데, `env.sh` 가 새 셸마다
`patrol_cache_repair` 를 조용히 불러 고친다.

---

## Isaac ↔ 기존 시스템이 만나는 곳

씬이 발행할 토픽은 `bridge/` 가 이미 정해 두었다. 이름·타입을 여기 맞추면
Django 서버와 모니터 대시보드는 **하나도 안 고쳐도** 된다.

| 토픽 | 타입 | 받는 곳 | → 서버 API |
|---|---|---|---|
| `webcam_images/webcam1/detections` | `sensor_msgs/Image` | `bridge_webcam.py` | `POST /api/webcam1/frame/` |
| `webcam_objects/map_detections` | `visualization_msgs/MarkerArray` | `bridge_webcam.py` | `POST /api/parking/` |
| `webtoamr_xy` | `std_msgs/String` (JSON) | AMR1 | ← `bridge_amr1.py` 가 발행 |

> ⚠ `cv_bridge` 는 Isaac 번들에 없다. Isaac 쪽에서 이미지를 낼 때는 cv2 로 직접
> `sensor_msgs/Image` 를 채운다.

> ⚠ 구역 종류는 `app/models.py:4` 의 `ZONE_CHOICES`(`Not` / `NORMAL` /
> `DISABLED` / `FIRE`) 를 따랐다. `CLAUDE.md` 는 `COMPACT` · `EV` 도 적고 있지만
> 모델에는 없다.

---

## 로그 위치

```
~/isaacsim_venv/lib/python3.12/site-packages/isaacsim/kit/logs/Kit/
~/.nvidia-omniverse/logs/          → NVMe 로 심볼릭
~/.local/share/ov/                 → NVMe 로 심볼릭 (크래시덤프)
```
