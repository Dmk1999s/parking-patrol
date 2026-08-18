"""[ROS 3.10] Nav2 기동 — AMR1, 저장 지도 위에서.

    patrol_ros
    ros2 launch sim/nav2/nav2_amr1.launch.py

띄우는 것:
    map_server(/map, 네임스페이스 밖)
    /amr1 네임스페이스: amcl · planner · controller · behaviors · bt_navigator
    라이프사이클 매니저 2개 (지도 / 내비)

🚨 세션 6 부터 map→amr1/odom 은 **AMCL 이 추정한다.** 그전까지는 정적 TF
   (항등)로 국지화를 우회했다 — 시뮬 odom 이 참값이라 가능했던 "커닝"이고
   실물엔 없다. 근거·전제(외곽 담장)는 nav2_params_amr1.yaml 머리말 참고.
목표는 amr1_nav.py 가 /amr1/navigate_to_pose 액션으로 넣는다.

nav2_bringup 의 navigation_launch.py 를 안 쓰는 이유: 그쪽은 velocity_smoother
를 경유(cmd_vel_nav 리매핑)하는데, 이 씬의 cmd_vel 소비자는 Isaac 차동구동
하나뿐이라 껴 봐야 조율할 파라미터만 는다. 필요한 노드만 직접 나열한다.
"""

import os

from launch import LaunchDescription
from launch_ros.actions import Node

_HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(_HERE, "nav2_params_amr1.yaml")
MAP_YAML = os.path.normpath(os.path.join(_HERE, "..", "slam", "maps", "parking.yaml"))

NS = "amr1"


def generate_launch_description():
    sim_time = {"use_sim_time": True}

    return LaunchDescription([
        # ── 지도 (공용, 네임스페이스 밖) ──────────────────────────
        Node(
            package="nav2_map_server", executable="map_server", name="map_server",
            output="screen",
            parameters=[PARAMS, {"yaml_filename": MAP_YAML}],
        ),
        Node(
            package="nav2_lifecycle_manager", executable="lifecycle_manager",
            name="lifecycle_manager_map", output="screen",
            parameters=[sim_time, {"autostart": True, "node_names": ["map_server"]}],
        ),

        # ── 국지화 (/amr1) ────────────────────────────────────────
        # map→amr1/odom 을 발행한다. 초기 위치는 params 의 set_initial_pose.
        Node(
            package="nav2_amcl", executable="amcl",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),

        # ── 내비게이션 (/amr1) ────────────────────────────────────
        Node(
            package="nav2_controller", executable="controller_server",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),
        Node(
            package="nav2_planner", executable="planner_server",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),
        Node(
            package="nav2_behaviors", executable="behavior_server",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),
        Node(
            package="nav2_bt_navigator", executable="bt_navigator",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),
        Node(
            package="nav2_lifecycle_manager", executable="lifecycle_manager",
            namespace=NS, name="lifecycle_manager_navigation", output="screen",
            parameters=[sim_time, {
                "autostart": True,
                # ⚠ amcl 이 맨 앞 — 활성화 순서대로 올라간다. map→odom TF 가
                #   없으면 코스트맵이 map 프레임을 못 잡는다.
                "node_names": ["amcl", "planner_server", "controller_server",
                               "behavior_server", "bt_navigator"],
            }],
        ),
    ])
