"""[ROS 3.10] Nav2 기동 — AMR2. **nav2_amr1.launch.py 가 떠 있는 위에** 얹는다.

    patrol_ros
    ros2 launch sim/nav2/nav2_amr2.launch.py

map_server 와 map 프레임은 amr1 런치가 이미 제공하므로 여기서는:
    정적 TF map→amr2/odom + /amr2 네임스페이스의 내비 4종 + 매니저
만 띄운다. (amr1 런치를 내리면 amr2 도 지도를 잃는다 — 순서 주의.)

## 정적 TF 값의 근거

map 프레임 = world − AMR_START[0](amr1 시작). amr2 의 odom 원점은 자기
시작 좌표 AMR_START[1] = (3.2, −3.0) 이므로:

    map→amr2/odom = AMR_START[1] − AMR_START[0] = (2.0, 0.0)

시뮬 odom 이 참값이라 amr1 과 같은 이유로 AMCL 이 필요 없다
(nav2_params_amr1.yaml 머리말).
"""

import os

from launch import LaunchDescription
from launch_ros.actions import Node

_HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(_HERE, "nav2_params_amr2.yaml")

NS = "amr2"
# 🚨 세션 6: 정적 TF 를 없애고 AMCL 로 바꿨다. 여기 있던 TF_X/TF_Y (2.0, 0.0)
#    는 nav2_params_amr2.yaml 의 amcl.initial_pose 로 옮겨갔다 — AMR_START[1]
#    - AMR_START[0] 라는 의미는 그대로다 (layout.py 를 바꾸면 거기도).


def generate_launch_description():
    sim_time = {"use_sim_time": True}

    return LaunchDescription([
        # 국지화 — map→amr2/odom (초기 위치는 params 의 set_initial_pose)
        Node(
            package="nav2_amcl", executable="amcl",
            namespace=NS, output="screen", parameters=[PARAMS],
        ),
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
                "node_names": ["amcl", "planner_server", "controller_server",
                               "behavior_server", "bt_navigator"],
            }],
        ),
    ])
