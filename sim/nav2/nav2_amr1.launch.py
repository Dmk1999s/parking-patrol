"""[ROS 3.10] Nav2 기동 — AMR1, 저장 지도 위에서.

    patrol_ros
    ros2 launch sim/nav2/nav2_amr1.launch.py

띄우는 것:
    map_server(/map, 네임스페이스 밖) + 정적 TF map→amr1/odom(항등)
    /amr1 네임스페이스: planner · controller · behaviors · bt_navigator
    라이프사이클 매니저 2개 (지도 / 내비)

좌표계 근거(왜 AMCL 이 없는가)는 nav2_params_amr1.yaml 머리말 참고.
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
        # map 프레임 = amr1/odom 프레임 (스캔 매칭 없이 만든 지도 — yaml 머리말)
        Node(
            package="tf2_ros", executable="static_transform_publisher",
            name="map_to_amr1_odom", output="screen",
            arguments=["--frame-id", "map", "--child-frame-id", f"{NS}/odom"],
            parameters=[sim_time],
        ),
        Node(
            package="nav2_lifecycle_manager", executable="lifecycle_manager",
            name="lifecycle_manager_map", output="screen",
            parameters=[sim_time, {"autostart": True, "node_names": ["map_server"]}],
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
                "node_names": ["planner_server", "controller_server",
                               "behavior_server", "bt_navigator"],
            }],
        ),
    ])
