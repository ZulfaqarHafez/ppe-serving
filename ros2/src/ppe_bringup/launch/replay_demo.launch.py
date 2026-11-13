"""
Level (b) demo: replayed images, detector, patrol node and a fake Nav2 server.

The fake NavigateToPose server stands in for Nav2; see README.

    ros2 launch ppe_bringup replay_demo.launch.py images:=plant-cctv
"""
import os

from ament_index_python.packages import get_package_share_directory
import launch
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def lifecycle_autostart(node):
    """Configure the lifecycle node on start and activate it once inactive."""
    configure = EmitEvent(event=ChangeState(
        lifecycle_node_matcher=matches_action(node),
        transition_id=Transition.TRANSITION_CONFIGURE))
    activate = RegisterEventHandler(OnStateTransition(
        target_lifecycle_node=node, goal_state='inactive',
        entities=[EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=Transition.TRANSITION_ACTIVATE))]))
    return [activate, configure]


def generate_launch_description():
    detector_cfg = os.path.join(
        get_package_share_directory('ppe_detector'), 'config', 'detector.yaml')
    patrol_cfg = os.path.join(
        get_package_share_directory('ppe_patrol'), 'config', 'patrol.yaml')

    args = [
        DeclareLaunchArgument('images', default_value='plant-cctv',
                              description='Comma-separated sample ids to replay'),
        DeclareLaunchArgument('rate_hz', default_value='5.0'),
        DeclareLaunchArgument('repeat_each', default_value='1'),
        DeclareLaunchArgument('loop', default_value='true'),
        DeclareLaunchArgument('max_frames', default_value='0'),
        DeclareLaunchArgument('start_delay_s', default_value='2.0'),
        DeclareLaunchArgument('intra_op_threads', default_value='0'),
        DeclareLaunchArgument('score_threshold', default_value='0.25'),
        DeclareLaunchArgument('cooldown_s', default_value='10.0'),
        DeclareLaunchArgument('consecutive_frames', default_value='3'),
    ]

    images = PythonExpression(["'", LaunchConfiguration('images'), "'.split(',')"])

    publisher = Node(
        package='ppe_bringup', executable='sample_image_publisher', name='sample_image_publisher',
        parameters=[{
            'images': images,
            'rate_hz': LaunchConfiguration('rate_hz'),
            'repeat_each': LaunchConfiguration('repeat_each'),
            'loop': LaunchConfiguration('loop'),
            'max_frames': LaunchConfiguration('max_frames'),
            'start_delay_s': LaunchConfiguration('start_delay_s'),
        }], output='screen')
    detector = LifecycleNode(
        package='ppe_detector', executable='ppe_detector_node', name='ppe_detector',
        namespace='', parameters=[detector_cfg, {
            'intra_op_threads': LaunchConfiguration('intra_op_threads'),
            'score_threshold': LaunchConfiguration('score_threshold'),
        }], output='screen')
    patrol = Node(
        package='ppe_patrol', executable='ppe_patrol_node', name='ppe_patrol',
        parameters=[patrol_cfg, {
            'cooldown_s': LaunchConfiguration('cooldown_s'),
            'consecutive_frames': LaunchConfiguration('consecutive_frames'),
        }], output='screen')
    fake_nav = Node(
        package='ppe_bringup', executable='fake_navigate_to_pose_server',
        name='fake_navigate_to_pose_server', output='screen')

    return launch.LaunchDescription(
        args + [publisher, detector, patrol, fake_nav] + lifecycle_autostart(detector))
