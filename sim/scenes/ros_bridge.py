"""ROS 2 배선 — 씬이 `/cmd_vel` 을 받고 `/scan` · `/odom` · `/tf` · `/clock` 을 낸다.

`lot.py` 가 형상과 물리를 세우고, 이 파일이 그 위에 **센서와 통신**을 얹는다.
갈라 둔 이유는 성질이 다르기 때문이다 — `lot.py` 는 순수 USD 라 `.usd` 로 굽거나
Isaac 없이 검사할 수 있지만, 여기 있는 것들은 Kit 확장(OmniGraph · Replicator ·
RTX 센서)이 떠 있어야만 만들어진다.

## 이걸 붙이면 무엇이 되는가

SLAM → Nav2 → 순찰이 전부 이 위에서 돈다:

    /clock                     시뮬 시간 (모든 노드가 use_sim_time 으로 이걸 따른다)
    /amr1/scan    LaserScan    ← RTX 라이다.  SLAM 의 입력
    /amr1/odom    Odometry     ← 물리에서 뽑은 주행거리
    /tf                        amr1/odom → amr1/base_link → amr1/base_scan
    /amr1/cmd_vel Twist        → 차동구동.  Nav2 가 여기로 명령한다

## 🚨 로봇이 두 대라 이름을 갈라야 한다

AMR1·AMR2 가 같은 토픽을 쓰면 서로의 명령을 받는다. 그래서 **토픽은 네임스페이스
(`/amr1/...`), 프레임은 접두사(`amr1/base_link`)** 로 가른다. `/tf` 는 하나로
두고 프레임 이름만 갈라 놓는 것이 다중 로봇의 통례다 — `/amr1/tf` 로 갈라 두면
RViz 와 Nav2 가 두 트리를 따로 들고 있어야 해서 오히려 번거롭다.

## 🚨 물리(충돌)와 라이다(가시성)는 다른 것을 본다

RTX 라이다는 **보이는 형상**에 광선을 쏘고, PhysX 는 **콜라이더**로 부딪친다.
안 보이는 콜라이더는 스캔에 안 잡히고, 콜라이더 없는 형상은 스캔에는 잡히는데
통과해 지나간다. 둘 다 필요하다 (`lot.ROCKER_Z0` 주석 참고 — 라이다 높이 때문에
차체를 바닥까지 이어 붙였다).
"""

import os

import lot

# ── 라이다 ──────────────────────────────────────────────────────
# TB3 Burger 의 실제 센서는 LDS-01 (360°, **최대 3.5 m**, 5 Hz) 이다. 그런데
# 이 주차장은 32×23 m 라 3.5 m 로는 통로 한복판에서 아무 벽도 안 닿는 구간이
# 생겨 SLAM 이 끊긴다. 그래서 같은 2D 회전 라이다로 사거리를 늘려 쓴다.
#
# 🚨 이건 **실물과 다르게 만든 부분**이다. 실제 TB3 로 옮길 때 사거리가 3.5 m 로
#    줄어들면 SLAM 파라미터를 다시 잡아야 한다. 실물과 맞추려면:
#        PATROL_LIDAR_RANGE=3.5 ...
LIDAR_CONFIG = os.environ.get("PATROL_LIDAR_CONFIG", "Example_Rotary_2D")
LIDAR_RANGE = float(os.environ.get("PATROL_LIDAR_RANGE", "20.0"))
LIDAR_RP_RES = (128, 128)     # 렌더 프로덕트 해상도 — 라이다는 결과에 안 쓴다

EXTENSIONS = ("isaacsim.ros2.bridge",)


def enable_extensions():
    """ROS 2 브리지 확장을 켠다. **SimulationApp 을 만든 뒤** 부른다.

    🚨 이 함수가 성공해도 브리지가 살아 있다는 뜻은 아니다. 번들 C 라이브러리
       경로가 없으면 로그에 `ROS2 Bridge startup failed` 만 찍히고 확장은
       enabled 로 남는다 — 그 함정은 `pyver.ensure_ros2_libs()` 가 프로세스가
       뜨기 전에 막는다. 씬 스크립트가 그것을 **먼저** 부르는지 확인할 것.
    """
    import omni.kit.app
    mgr = omni.kit.app.get_app().get_extension_manager()
    for ext in EXTENSIONS:
        mgr.set_extension_enabled_immediate(ext, True)
        if not mgr.is_extension_enabled(ext):
            raise RuntimeError(f"확장을 못 켰다: {ext}")


def add_lidar(stage, robot_path):
    """로봇의 `base_scan` 링크에 RTX 라이다를 달고 (프림, 렌더프로덕트) 를 준다.

    ## 왜 링크 **아래**에 다는가

    스캔 원점이 로봇과 함께 움직여야 한다. `/World` 아래에 두면 로봇이 굴러가도
    라이다는 제자리에 남는데, 스캔은 계속 나오므로 **오류 없이 지도가 뭉개진다.**

    ## 프림을 만드는 방식

    6.0 에서는 `isaacsim.sensors.experimental.rtx.Lidar` 가 `OmniLidar` 프림을
    만든다 (5.x 의 `IsaacSensorCreateRtxLidar` 커맨드 자리다). `config` 는 센서
    모델 USD 이름이고, NVIDIA CDN 에서 받아 온다 — TB3 자산과 같은 경로다.
    """
    from isaacsim.sensors.experimental.rtx import Lidar

    scan_link = f"{robot_path}/{lot.TB3_SCAN_LINK}"
    if not stage.GetPrimAtPath(scan_link):
        raise RuntimeError(f"라이다를 달 링크가 없다: {scan_link}")

    path = f"{scan_link}/Lidar"
    Lidar.create(path, config=LIDAR_CONFIG,
                 attributes={"omni:sensor:Core:farRangeM": LIDAR_RANGE})

    # 렌더 프로덕트가 있어야 RTX 파이프라인이 이 센서를 돌린다. 라이다는
    # 픽셀을 쓰지 않으므로 해상도는 결과에 영향이 없다 (테스트 코드도 128 이다).
    import omni.replicator.core as rep
    rp = rep.create.render_product(path, resolution=LIDAR_RP_RES)
    return path, rp.path


def _scan_link_offset(stage, robot_path):
    """`base_link` → `base_scan` 로컬 변위 (m). 정적 TF 로 내보낼 값이다.

    자산에 저작된 값을 **읽어서** 쓴다. TB3 Burger 는 (-0.032, 0, 0.182) 인데,
    손으로 적어 두면 자산이 바뀔 때 조용히 틀어진다 — TF 는 틀려도 오류가 안 나고
    지도만 어긋난다.
    """
    from pxr import Gf, UsdGeom
    prim = stage.GetPrimAtPath(f"{robot_path}/{lot.TB3_SCAN_LINK}")
    xf = UsdGeom.Xformable(prim).GetLocalTransformation()
    t = xf.ExtractTranslation()
    return Gf.Vec3d(t[0], t[1], t[2])


def clock_graph(graph_path="/Graphs/ROS_Clock"):
    """`/clock` 발행 그래프. 로봇 수와 무관하게 **하나만** 만든다.

    두 번 만들면 같은 토픽에 두 노드가 발행해 시간이 앞뒤로 튄다 — TF 보간이
    깨져 "가끔 위치가 순간이동하는" 증상이 된다.
    """
    import omni.graph.core as og
    keys = og.Controller.Keys
    og.Controller.edit(
        {"graph_path": graph_path, "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: [
                ("Tick", "omni.graph.action.OnPlaybackTick"),
                ("SimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
            ],
            keys.CONNECT: [
                ("Tick.outputs:tick", "PublishClock.inputs:execIn"),
                ("SimTime.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
            ],
        },
    )
    return graph_path


def robot_graph(stage, robot_path, ns, lidar_rp, graph_path=None):
    """AMR 한 대의 ROS 2 배선 — 구독 `cmd_vel`, 발행 `odom` · `tf` · `scan`.

    Args:
        robot_path: 아티큘레이션 루트 (`/World/AMR1`).
        ns: 토픽 네임스페이스이자 프레임 접두사 (`amr1`).
        lidar_rp: `add_lidar` 가 준 렌더 프로덕트 경로.

    ## 배선 (한 줄 요약)

        cmd_vel ─→ BreakVector3 ─→ DifferentialController ─→ ArticulationController
        물리 ────→ ComputeOdometry ─→ PublishOdometry / PublishRawTransformTree

    ## 🚨 Twist 는 벡터, 컨트롤러는 스칼라를 받는다

    `ROS2SubscribeTwist` 는 linear/angular 를 각각 vec3 로 주는데
    `DifferentialController` 는 `double` 하나씩 받는다. 그래서 `BreakVector3` 로
    linear**.x** 와 angular**.z** 만 뽑아 넣는다. 나머지 성분은 차동구동이 낼 수
    없는 움직임이라 버리는 것이 맞다.

    ## 🚨 execIn 을 tick 에 물리면 명령이 흐른다

    `DifferentialController` 는 tick 이 아니라 **`subscribeTwist.outputs:execOut`**
    으로 깨워야 한다. tick 에 물리면 메시지가 안 와도 매 프레임 마지막 값으로
    계속 돌아, `/cmd_vel` 이 끊겨도 로봇이 멈추지 않는다.
    """
    import omni.graph.core as og
    import usdrt

    graph_path = graph_path or f"/Graphs/ROS_{ns}"
    off = _scan_link_offset(stage, robot_path)
    target = [usdrt.Sdf.Path(robot_path)]

    keys = og.Controller.Keys
    og.Controller.edit(
        {"graph_path": graph_path, "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: [
                ("Tick", "omni.graph.action.OnPlaybackTick"),
                ("SimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                # 주행계 → /odom + /tf
                ("ComputeOdom", "isaacsim.core.nodes.IsaacComputeOdometry"),
                ("PublishOdom", "isaacsim.ros2.bridge.ROS2PublishOdometry"),
                ("PublishOdomTF", "isaacsim.ros2.bridge.ROS2PublishRawTransformTree"),
                # base_link → base_scan 정적 TF
                ("PublishScanTF", "isaacsim.ros2.bridge.ROS2PublishRawTransformTree"),
                # /cmd_vel → 차동구동
                ("SubTwist", "isaacsim.ros2.bridge.ROS2SubscribeTwist"),
                ("BreakLin", "omni.graph.nodes.BreakVector3"),
                ("BreakAng", "omni.graph.nodes.BreakVector3"),
                ("DiffDrive", "isaacsim.robot.wheeled_robots.DifferentialController"),
                ("ArtCtrl", "isaacsim.core.nodes.IsaacArticulationController"),
                # 라이다 → /scan
                ("PublishScan", "isaacsim.ros2.bridge.ROS2RtxLidarHelper"),
            ],
            keys.CONNECT: [
                ("Tick.outputs:tick", "ComputeOdom.inputs:execIn"),
                ("Tick.outputs:tick", "PublishOdom.inputs:execIn"),
                ("Tick.outputs:tick", "PublishOdomTF.inputs:execIn"),
                ("Tick.outputs:tick", "PublishScanTF.inputs:execIn"),
                ("Tick.outputs:tick", "SubTwist.inputs:execIn"),
                ("Tick.outputs:tick", "ArtCtrl.inputs:execIn"),
                ("Tick.outputs:tick", "PublishScan.inputs:execIn"),

                ("SimTime.outputs:simulationTime", "PublishOdom.inputs:timeStamp"),
                ("SimTime.outputs:simulationTime", "PublishOdomTF.inputs:timeStamp"),
                ("SimTime.outputs:simulationTime", "PublishScanTF.inputs:timeStamp"),

                ("ComputeOdom.outputs:position", "PublishOdom.inputs:position"),
                ("ComputeOdom.outputs:orientation", "PublishOdom.inputs:orientation"),
                ("ComputeOdom.outputs:linearVelocity", "PublishOdom.inputs:linearVelocity"),
                ("ComputeOdom.outputs:angularVelocity", "PublishOdom.inputs:angularVelocity"),
                ("ComputeOdom.outputs:position", "PublishOdomTF.inputs:translation"),
                ("ComputeOdom.outputs:orientation", "PublishOdomTF.inputs:rotation"),

                ("SubTwist.outputs:execOut", "DiffDrive.inputs:execIn"),
                ("SubTwist.outputs:linearVelocity", "BreakLin.inputs:tuple"),
                ("SubTwist.outputs:angularVelocity", "BreakAng.inputs:tuple"),
                ("BreakLin.outputs:x", "DiffDrive.inputs:linearVelocity"),
                ("BreakAng.outputs:z", "DiffDrive.inputs:angularVelocity"),
                ("DiffDrive.outputs:velocityCommand", "ArtCtrl.inputs:velocityCommand"),
            ],
            keys.SET_VALUES: [
                ("ComputeOdom.inputs:chassisPrim", target),
                ("ArtCtrl.inputs:targetPrim", target),
                ("ArtCtrl.inputs:jointNames", list(lot.TB3_WHEEL_JOINTS)),

                ("DiffDrive.inputs:wheelRadius", lot.TB3_WHEEL_RADIUS),
                ("DiffDrive.inputs:wheelDistance", lot.TB3_WHEEL_BASE),
                # 🔑 상한을 실물 정격(0.22)보다 넉넉히 둔다. 이 값은 목표가
                #    아니라 **자르는 선**이다 — 실제 속도는 /cmd_vel 을 내는
                #    쪽(순찰 드라이버·Nav2)이 정한다. 시뮬은 실물보다 빠르게
                #    몰 일이 많아(시간 절약) 여기서 막지 않는다.
                #    ⚠ 실물 이관 시 명령하는 쪽 속도를 0.2 이하로 잡을 것.
                ("DiffDrive.inputs:maxLinearSpeed", 0.6),
                ("DiffDrive.inputs:maxAngularSpeed", lot.TB3_MAX_ANG),

                # 토픽은 네임스페이스로, 프레임은 접두사로 가른다 (머리말 참고).
                ("PublishOdom.inputs:nodeNamespace", f"/{ns}"),
                ("PublishOdom.inputs:topicName", "odom"),
                ("PublishOdom.inputs:odomFrameId", f"{ns}/odom"),
                ("PublishOdom.inputs:chassisFrameId", f"{ns}/base_link"),

                # 🔑 TF 는 네임스페이스를 주지 않는다 — 전역 `/tf` 하나로 모은다.
                ("PublishOdomTF.inputs:topicName", "tf"),
                ("PublishOdomTF.inputs:parentFrameId", f"{ns}/odom"),
                ("PublishOdomTF.inputs:childFrameId", f"{ns}/base_link"),

                ("PublishScanTF.inputs:topicName", "tf"),
                ("PublishScanTF.inputs:parentFrameId", f"{ns}/base_link"),
                ("PublishScanTF.inputs:childFrameId", f"{ns}/base_scan"),
                ("PublishScanTF.inputs:translation", off),

                ("SubTwist.inputs:nodeNamespace", f"/{ns}"),
                ("SubTwist.inputs:topicName", "cmd_vel"),

                ("PublishScan.inputs:nodeNamespace", f"/{ns}"),
                ("PublishScan.inputs:topicName", "scan"),
                ("PublishScan.inputs:frameId", f"{ns}/base_scan"),
                ("PublishScan.inputs:type", "laser_scan"),
                ("PublishScan.inputs:renderProductPath", lidar_rp),
                # 🔑 한 바퀴를 모아서 낸다. 끄면 부분 스캔이 조각조각 나가
                #    SLAM 이 같은 자리를 여러 번 다른 각도로 본 것처럼 오해한다.
                ("PublishScan.inputs:fullScan", True),
            ],
        },
    )
    return graph_path


def webcam_graph(stage, cam_prim="/World/Webcam1",
                 topic="webcam_images/webcam1/detections",
                 resolution=(1280, 720), skip=5,
                 graph_path="/Graphs/ROS_Webcam1",
                 frame_id="webcam1", label="webcam1",
                 depth_topic=None):
    """오버헤드 웹캠을 `sensor_msgs/Image` 로 발행 — 기존 시스템이 받는 쪽이다.

    토픽 이름은 `bridge/bridge_webcam.py` 가 구독하는 것과 **글자까지 같아야
    한다** (`webcam_images/webcam1/detections`). 브리지가 이걸 받아 Django
    `/api/webcam1/frame/` 로 올리고, 모니터 대시보드와
    `/api/webcam1/stream/` (MJPEG) 에 그대로 뜬다 — **서버 쪽 코드는 한 줄도
    안 고치고** 웹에서 웹캠을 보게 된다.

    ## frameSkipCount 를 왜 두는가

    카메라 헬퍼는 기본으로 **매 렌더 프레임**(시뮬 60 Hz) 발행한다. 1280×720
    이미지를 60 Hz 로 나르면 DDS·브리지·Django 가 전부 그걸 삼켜야 하고 GPU
    렌더 부하도 같이 커진다. 감시 카메라 용도로는 몇 Hz 면 충분하다.
    skip=5 → 6프레임에 1장 (시뮬 10 Hz).
    """
    import omni.graph.core as og
    import omni.replicator.core as rep

    if not stage.GetPrimAtPath(cam_prim):
        raise RuntimeError(f"웹캠 프림이 없다: {cam_prim}")
    rp = rep.create.render_product(cam_prim, resolution=resolution)

    nodes = [
        ("Tick", "omni.graph.action.OnPlaybackTick"),
        ("Publish", "isaacsim.ros2.bridge.ROS2CameraHelper"),
    ]
    connect = [("Tick.outputs:tick", "Publish.inputs:execIn")]
    values = [
        ("Publish.inputs:renderProductPath", rp.path),
        ("Publish.inputs:topicName", topic),
        ("Publish.inputs:type", "rgb"),
        ("Publish.inputs:frameId", frame_id),
        ("Publish.inputs:frameSkipCount", skip),
    ]
    if depth_topic:
        # 같은 render product 에서 depth(AOV)도 뽑는다 — 렌더는 한 번이라
        # 추가 부담이 작다 (32FC1 distance_to_image_plane, 미터).
        # 판별 노드가 차체/그림자를 거리로 가르는 데 쓴다 (pipe 프로젝트의
        # distance_to_camera annotator 방식을 ROS 발행으로 옮긴 것).
        nodes.append(("PublishDepth", "isaacsim.ros2.bridge.ROS2CameraHelper"))
        connect.append(("Tick.outputs:tick", "PublishDepth.inputs:execIn"))
        values += [
            ("PublishDepth.inputs:renderProductPath", rp.path),
            ("PublishDepth.inputs:topicName", depth_topic),
            ("PublishDepth.inputs:type", "depth"),
            ("PublishDepth.inputs:frameId", frame_id),
            ("PublishDepth.inputs:frameSkipCount", skip),
        ]

    keys = og.Controller.Keys
    og.Controller.edit(
        {"graph_path": graph_path, "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: nodes,
            keys.CONNECT: connect,
            keys.SET_VALUES: values,
        },
    )
    print(f"[ros] {label}: {topic} 발행 ({resolution[0]}×{resolution[1]}, "
          f"시뮬 {60 // (skip + 1)} Hz"
          + (f", depth → {depth_topic}" if depth_topic else "") + ")")
    return rp.path


def wire(stage, robots, webcam=True, cam_robots=None):
    """`/clock` + 로봇별 그래프를 한 번에. `robots` 는 [(프림경로, 네임스페이스)].

    Args:
        webcam: 오버헤드 웹캠 발행도 켠다 (`webcam_graph`).
        cam_robots: OcrCam 을 Image 로 발행할 로봇 목록 — 토픽
            `amr_images/<ns>/ocr`. `sim/vision/amr_cam_bridge.py` 가 받아
            `POST /api/<ns>/frame/` 로 올리면 모니터 대시보드의
            "AMR (Police) 카메라" 패널에 뜬다. OCR 노드도 같은 토픽을 쓴다.
            **라이다 배선(`robots`)과 별개다** — 관리자 화면에는 두 로봇
            카메라가 다 나와야 해서, `--robots amr1` 이어도 카메라는 전부
            발행한다 (patrol.py 가 전체 목록을 준다). None 이면 `robots`.

    Returns:
        {네임스페이스: dict(lidar=..., render_product=..., graph=...)}
    """
    enable_extensions()
    clock_graph()
    out = {}
    for path, ns in robots:
        lidar, rp = add_lidar(stage, path)
        graph = robot_graph(stage, path, ns, rp)
        out[ns] = dict(lidar=lidar, render_product=rp, graph=graph)
        print(f"[ros] {ns}: /{ns}/cmd_vel → 차동구동, "
              f"/{ns}/scan · /{ns}/odom · /tf 발행")
    for path, ns in (cam_robots if cam_robots is not None else robots):
        # skip=11 → 시뮬 5 Hz. 대시보드(벽시계 4 Hz)와 OCR(정지 상태 한 장)
        # 에는 충분하고, 해상도는 그대로라 품질 손실이 없다 — DDS·인코딩
        # 부하만 절반이 된다.
        # OcrCam 은 base_link **링크** 밑에 있다 (루트에 달면 로봇을 안
        # 따라간다 — lot._amr 참고). 폴백(원통 로봇)이면 루트 바로 밑.
        cam_prim = f"{path}/base_link/OcrCam"
        if not stage.GetPrimAtPath(cam_prim):
            cam_prim = f"{path}/OcrCam"
        webcam_graph(stage, cam_prim=cam_prim,
                     topic=f"amr_images/{ns}/ocr", skip=11,
                     graph_path=f"/Graphs/ROS_OcrCam_{ns}",
                     frame_id=f"{ns}/ocr", label=f"{ns} OcrCam",
                     depth_topic=f"amr_images/{ns}/depth")
    if webcam:
        webcam_graph(stage)
    return out
