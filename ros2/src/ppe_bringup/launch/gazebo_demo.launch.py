"""
Level (a) demo: Gazebo Harmonic (headless), TurtleBot3 Waffle, Nav2, detector, patrol.

Starts from the Nav2 TurtleBot3 sandbox (nav2_minimal_tb3_sim and nav2_bringup)
and changes three things at launch time, without copying the upstream files:

* world: adds a flat, visual-only "poster" showing one of the five sample
  images, floating above the lidar plane so it does not change the map;
* robot: replaces the depth camera with a 640 x 480 RGB camera pitched up
  0.25 rad, published on /camera/image_raw;
* Nav2 params: AMCL gets the spawn pose as its initial pose.

The PPE model only recognises PPE in photos, so the poster is the trick that
lets a simulated camera see something it can detect.

    ros2 launch ppe_bringup gazebo_demo.launch.py poster:=plant-cctv
"""
import json
import os
import tempfile

from ament_index_python.packages import get_package_share_directory
import launch
from launch.actions import (AppendEnvironmentVariable, DeclareLaunchArgument, EmitEvent,
                            ExecuteProcess, IncludeLaunchDescription, OpaqueFunction,
                            RegisterEventHandler)
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition
import xacro
import yaml

SPAWN = {'x': -2.0, 'y': -0.5, 'yaw': 0.0}

POSTER = """
    <model name="ppe_poster">
      <static>true</static>
      <pose>{x} {y} {z} 0 0 {yaw}</pose>
      <link name="link">
        <!-- Visual only: no collision, and it floats above the lidar plane. -->
        <visual name="image">
          <geometry><box><size>0.005 {w} {h}</size></box></geometry>
          <material>
            <ambient>1 1 1 1</ambient>
            <diffuse>1 1 1 1</diffuse>
            <emissive>1 1 1 1</emissive>
            <pbr><metal>
              <albedo_map>{texture}</albedo_map>
              <!-- Self-lit, so the photo looks the same whatever the sun does. -->
              <emissive_map>{texture}</emissive_map>
              <metalness>0</metalness>
              <roughness>1</roughness>
            </metal></pbr>
          </material>
        </visual>
      </link>
    </model>
"""

RGB_CAMERA = """<sensor name="ppe_rgb_camera" type="camera">
          <always_on>1</always_on>
          <update_rate>{rate}</update_rate>
          <pose>0.064 -0.047 0.107 0 -0.25 0</pose>
          <topic>$(arg namespace)/camera/image_raw</topic>
          <gz_frame_id>camera_rgb_optical_frame</gz_frame_id>
          <camera name="rgb">
            <horizontal_fov>1.047</horizontal_fov>
            <image><width>640</width><height>480</height><format>R8G8B8</format></image>
            <clip><near>0.05</near><far>20.0</far></clip>
          </camera>
        </sensor>"""


def lifecycle_autostart(node):
    configure = EmitEvent(event=ChangeState(
        lifecycle_node_matcher=matches_action(node),
        transition_id=Transition.TRANSITION_CONFIGURE))
    activate = RegisterEventHandler(OnStateTransition(
        target_lifecycle_node=node, goal_state='inactive',
        entities=[EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=Transition.TRANSITION_ACTIVATE))]))
    return [activate, configure]


def setup(context):
    sim_dir = get_package_share_directory('nav2_minimal_tb3_sim')
    nav2_dir = get_package_share_directory('nav2_bringup')
    me = get_package_share_directory('ppe_bringup')
    tmp = tempfile.mkdtemp(prefix='ppe_gz_')
    poster = LaunchConfiguration('poster').perform(context)
    camera_rate = LaunchConfiguration('camera_rate').perform(context)

    # World: upstream sandbox plus the poster, in line with the first pillars.
    with open(os.path.join(sim_dir, 'worlds', 'tb3_sandbox.sdf.xacro')) as f:
        world = f.read()
    with open(os.path.join(me, 'samples', 'samples.json')) as f:
        meta = {s['id']: s for s in json.load(f)['samples']}[poster]
    h = 0.8
    w = round(h * meta['width'] / meta['height'], 3)
    x = float(LaunchConfiguration('poster_x').perform(context))
    world = world.replace('  </world>', POSTER.format(
        x=x, y=-0.5, z=0.2 + h / 2, yaw=3.14159, w=w, h=h,
        texture=os.path.join(me, 'samples', poster + '.png')) + '  </world>')
    world_xacro = os.path.join(tmp, 'world.sdf.xacro')
    with open(world_xacro, 'w') as f:
        f.write(world)
    world_sdf = os.path.join(tmp, 'world.sdf')
    with open(world_sdf, 'w') as f:
        f.write(xacro.process_file(world_xacro, mappings={'headless': 'true'}).toxml())

    # Robot: upstream TurtleBot3 Waffle with the depth sensor swapped for RGB.
    with open(os.path.join(sim_dir, 'urdf', 'gz_waffle.sdf.xacro')) as f:
        robot = f.read()
    start = robot.index('<sensor name="intel_realsense_r200_depth"')
    end = robot.index('</sensor>', start) + len('</sensor>')
    robot = robot[:start] + RGB_CAMERA.format(rate=camera_rate) + robot[end:]
    robot_sdf = os.path.join(tmp, 'ppe_waffle.sdf.xacro')
    with open(robot_sdf, 'w') as f:
        f.write(robot)

    # Nav2 params: upstream defaults, AMCL starts at the spawn pose.
    with open(os.path.join(nav2_dir, 'params', 'nav2_params.yaml')) as f:
        params = yaml.safe_load(f)
    amcl = params['amcl']['ros__parameters']
    amcl['set_initial_pose'] = True
    amcl['initial_pose'] = {'x': SPAWN['x'], 'y': SPAWN['y'], 'z': 0.0, 'yaw': SPAWN['yaw']}
    params_file = os.path.join(tmp, 'nav2_params.yaml')
    with open(params_file, 'w') as f:
        yaml.safe_dump(params, f)

    gz_server = ExecuteProcess(
        cmd=['gz', 'sim', '-r', '-s', '--headless-rendering', world_sdf], output='screen')
    spawn = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(sim_dir, 'launch', 'spawn_tb3.launch.py')),
        launch_arguments={
            'use_sim_time': 'True', 'robot_sdf': robot_sdf,
            'x_pose': str(SPAWN['x']), 'y_pose': str(SPAWN['y']), 'z_pose': '0.01',
            'yaw': str(SPAWN['yaw'])}.items())
    with open(os.path.join(sim_dir, 'urdf', 'turtlebot3_waffle.urdf')) as f:
        robot_description = f.read()
    rsp = Node(
        package='robot_state_publisher', executable='robot_state_publisher', output='screen',
        parameters=[{'use_sim_time': True, 'robot_description': robot_description}])
    camera_bridge = Node(
        package='ros_gz_bridge', executable='parameter_bridge', name='camera_bridge',
        arguments=['/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image'],
        parameters=[{'use_sim_time': True}], output='screen')
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(nav2_dir, 'launch', 'bringup_launch.py')),
        launch_arguments={
            'map': os.path.join(nav2_dir, 'maps', 'tb3_sandbox.yaml'),
            'use_sim_time': 'True', 'params_file': params_file, 'autostart': 'True',
            'use_composition': 'True'}.items())

    detector_cfg = os.path.join(
        get_package_share_directory('ppe_detector'), 'config', 'detector.yaml')
    patrol_cfg = os.path.join(get_package_share_directory('ppe_patrol'), 'config', 'patrol.yaml')
    detector = LifecycleNode(
        package='ppe_detector', executable='ppe_detector_node', name='ppe_detector',
        namespace='', output='screen', parameters=[detector_cfg, {
            'use_sim_time': True,
            'intra_op_threads': int(LaunchConfiguration('intra_op_threads').perform(context)),
        }])
    patrol = Node(
        package='ppe_patrol', executable='ppe_patrol_node', name='ppe_patrol', output='screen',
        parameters=[patrol_cfg, {
            'use_sim_time': True,
            'goal_x': float(LaunchConfiguration('goal_x').perform(context)),
            'goal_y': float(LaunchConfiguration('goal_y').perform(context)),
            'goal_yaw': float(LaunchConfiguration('goal_yaw').perform(context)),
            'cooldown_s': 30.0,
            'violation_classes':
                LaunchConfiguration('violation_classes').perform(context).split(','),
        }])
    return [
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(sim_dir, 'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.dirname(sim_dir)),
        gz_server, spawn, rsp, camera_bridge, nav2, detector, patrol,
    ] + lifecycle_autostart(detector)


def generate_launch_description():
    return launch.LaunchDescription([
        DeclareLaunchArgument('poster', default_value='plant-cctv',
                              description='Sample id shown on the poster in the world'),
        DeclareLaunchArgument('poster_x', default_value='-1.05',
                              description='x of the poster; the robot spawns at x -2.0'),
        # On the rendered poster No-Helmet scores about 0.3 (0.627 on the
        # original image), so the simulation also watches No-vest. See README.
        DeclareLaunchArgument('violation_classes', default_value='No-Helmet,No-vest'),
        DeclareLaunchArgument('camera_rate', default_value='5'),
        DeclareLaunchArgument('intra_op_threads', default_value='0'),
        DeclareLaunchArgument('goal_x', default_value='0.6'),
        DeclareLaunchArgument('goal_y', default_value='-0.5'),
        DeclareLaunchArgument('goal_yaw', default_value='3.14159'),
        OpaqueFunction(function=setup),
    ])
