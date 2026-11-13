// STAND-IN FOR NAV2. Not a planner, controller or map: a minimal
// nav2_msgs/NavigateToPose action server so the detection-to-goal path can run
// end to end without Nav2. It "drives" in a straight line from its current
// pose toward the goal at a fixed speed, publishes feedback at 10 Hz, honours
// cancel requests and succeeds on arrival. Use the Gazebo launch for real Nav2.

#include <chrono>
#include <cmath>
#include <memory>
#include <thread>

#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

namespace ppe_bringup
{

using NavigateToPose = nav2_msgs::action::NavigateToPose;
using ServerGoalHandle = rclcpp_action::ServerGoalHandle<NavigateToPose>;

class FakeNavigateToPoseServer : public rclcpp::Node
{
public:
  FakeNavigateToPoseServer()
  : rclcpp::Node("fake_navigate_to_pose_server")
  {
    speed_ = declare_parameter("speed_mps", 0.5);
    reject_ = declare_parameter("reject_goals", false);
    server_ = rclcpp_action::create_server<NavigateToPose>(
      this, declare_parameter("action_name", "navigate_to_pose"),
      [this](const rclcpp_action::GoalUUID &, std::shared_ptr<const NavigateToPose::Goal> goal) {
        RCLCPP_INFO(
          get_logger(), "goal (%.2f, %.2f) in %s: %s", goal->pose.pose.position.x,
          goal->pose.pose.position.y, goal->pose.header.frame_id.c_str(),
          reject_ ? "rejecting" : "accepting");
        return reject_ ? rclcpp_action::GoalResponse::REJECT :
               rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
      },
      [this](const std::shared_ptr<ServerGoalHandle>) {
        RCLCPP_INFO(get_logger(), "cancel requested");
        return rclcpp_action::CancelResponse::ACCEPT;
      },
      [this](const std::shared_ptr<ServerGoalHandle> handle) {
        std::thread([this, handle]() {execute(handle);}).detach();
      });
    RCLCPP_WARN(get_logger(), "fake NavigateToPose server (stand-in for Nav2) is up");
  }

private:
  void execute(const std::shared_ptr<ServerGoalHandle> handle)
  {
    const auto goal = handle->get_goal();
    const auto start = now();
    auto feedback = std::make_shared<NavigateToPose::Feedback>();
    auto result = std::make_shared<NavigateToPose::Result>();
    rclcpp::Rate rate(10.0);
    while (rclcpp::ok()) {
      const double dx = goal->pose.pose.position.x - x_;
      const double dy = goal->pose.pose.position.y - y_;
      const double dist = std::hypot(dx, dy);
      if (handle->is_canceling()) {
        handle->canceled(result);
        RCLCPP_INFO(get_logger(), "goal canceled");
        return;
      }
      if (dist < 0.05) {
        break;
      }
      const double step = std::min(dist, speed_ * 0.1);
      x_ += step * dx / dist;
      y_ += step * dy / dist;
      feedback->current_pose.header.frame_id = goal->pose.header.frame_id;
      feedback->current_pose.header.stamp = now();
      feedback->current_pose.pose.position.x = x_;
      feedback->current_pose.pose.position.y = y_;
      feedback->distance_remaining = static_cast<float>(dist - step);
      feedback->navigation_time = now() - start;
      handle->publish_feedback(feedback);
      rate.sleep();
    }
    if (rclcpp::ok()) {
      handle->succeed(result);
      RCLCPP_INFO(get_logger(), "goal reached (fake) after %.1f s", (now() - start).seconds());
    }
  }

  double speed_{0.5};
  bool reject_{false};
  double x_{0.0};
  double y_{0.0};
  rclcpp_action::Server<NavigateToPose>::SharedPtr server_;
};

}  // namespace ppe_bringup

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ppe_bringup::FakeNavigateToPoseServer>());
  rclcpp::shutdown();
  return 0;
}
