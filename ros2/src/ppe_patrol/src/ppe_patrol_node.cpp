// Watches PPE detections and, after N consecutive frames with a configured
// violation class, sends a nav2_msgs/NavigateToPose goal to an inspection pose.

#include <chrono>
#include <cmath>
#include <cstdio>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <std_msgs/msg/string.hpp>
#include <vision_msgs/msg/detection2_d_array.hpp>

#include "ppe_patrol/patrol_logic.hpp"

namespace ppe_patrol
{

using NavigateToPose = nav2_msgs::action::NavigateToPose;
using GoalHandle = rclcpp_action::ClientGoalHandle<NavigateToPose>;

class PpePatrolNode : public rclcpp::Node
{
public:
  PpePatrolNode()
  : rclcpp::Node("ppe_patrol"), logic_(read_config())
  {
    action_name_ = declare_parameter("action_name", "navigate_to_pose");
    goal_frame_ = declare_parameter("goal_frame", "map");
    goal_x_ = declare_parameter("goal_x", 1.0);
    goal_y_ = declare_parameter("goal_y", 0.0);
    goal_yaw_ = declare_parameter("goal_yaw", 0.0);
    goal_timeout_s_ = declare_parameter("goal_timeout_s", 120.0);
    feedback_period_s_ = declare_parameter("feedback_log_period_s", 1.0);

    client_ = rclcpp_action::create_client<NavigateToPose>(this, action_name_);
    events_pub_ = create_publisher<std_msgs::msg::String>(
      declare_parameter("events_topic", "patrol/events"),
      rclcpp::QoS(rclcpp::KeepLast(50)).reliable().transient_local());
    det_sub_ = create_subscription<vision_msgs::msg::Detection2DArray>(
      declare_parameter("detections_topic", "detections"), rclcpp::QoS(rclcpp::KeepLast(10)),
      [this](vision_msgs::msg::Detection2DArray::ConstSharedPtr msg) {on_detections(*msg);});
    timer_ = create_wall_timer(std::chrono::milliseconds(200), [this]() {check_timeout();});
    RCLCPP_INFO(
      get_logger(), "watching %s for %s; goal (%.2f, %.2f) in %s via %s",
      det_sub_->get_topic_name(), classes_text_.c_str(), goal_x_, goal_y_, goal_frame_.c_str(),
      action_name_.c_str());
  }

private:
  PatrolConfig read_config()
  {
    PatrolConfig c;
    const auto classes = declare_parameter(
      "violation_classes", std::vector<std::string>{"No-Helmet"});
    c.violation_classes = std::set<std::string>(classes.begin(), classes.end());
    for (const auto & s : classes) {
      classes_text_ += (classes_text_.empty() ? "" : ",") + s;
    }
    c.min_confidence = declare_parameter("min_confidence", 0.5);
    c.consecutive_frames = static_cast<int>(declare_parameter("consecutive_frames", 3));
    c.cooldown_s = declare_parameter("cooldown_s", 10.0);
    c.retry_after_reject_s = declare_parameter("retry_after_reject_s", 2.0);
    return c;
  }

  static double wall_now()
  {
    return std::chrono::duration<double>(
      std::chrono::system_clock::now().time_since_epoch()).count();
  }

  void emit(const std::string & event, const std::string & extra = "")
  {
    char head[160];
    std::snprintf(
      head, sizeof(head), "{\"event\": \"%s\", \"t\": %.6f, \"wall\": %.6f", event.c_str(),
      now().seconds(), wall_now());
    std_msgs::msg::String msg;
    msg.data = std::string(head) + (extra.empty() ? "" : ", " + extra) + "}";
    events_pub_->publish(msg);
  }

  void on_detections(const vision_msgs::msg::Detection2DArray & msg)
  {
    std::vector<Seen> seen;
    for (const auto & d : msg.detections) {
      if (!d.results.empty()) {
        seen.push_back({d.results[0].hypothesis.class_id, d.results[0].hypothesis.score});
      }
    }
    const bool fire = logic_.on_frame(seen, now().seconds());
    if (logic_.streak() == 1) {
      first_stamp_ = rclcpp::Time(msg.header.stamp).seconds();
    }
    if (fire) {
      send_goal(msg);
    }
  }

  void send_goal(const vision_msgs::msg::Detection2DArray & trigger)
  {
    char extra[320];
    const Seen & v = logic_.last_violation();
    std::snprintf(
      extra, sizeof(extra),
      "\"label\": \"%s\", \"score\": %.4f, \"frames\": %d, \"first_stamp\": %.6f, "
      "\"trigger_stamp\": %.6f, \"trigger_frame\": \"%s\"",
      v.label.c_str(), v.score, logic_.streak(), first_stamp_,
      rclcpp::Time(trigger.header.stamp).seconds(), trigger.header.frame_id.c_str());
    if (!client_->action_server_is_ready()) {
      RCLCPP_WARN(get_logger(), "violation confirmed but %s is not available",
          action_name_.c_str());
      emit("server_unavailable", extra);
      logic_.goal_not_sent();
      return;
    }
    NavigateToPose::Goal goal;
    goal.pose.header.frame_id = goal_frame_;
    goal.pose.header.stamp = now();
    goal.pose.pose.position.x = goal_x_;
    goal.pose.pose.position.y = goal_y_;
    goal.pose.pose.orientation.z = std::sin(goal_yaw_ / 2.0);
    goal.pose.pose.orientation.w = std::cos(goal_yaw_ / 2.0);

    rclcpp_action::Client<NavigateToPose>::SendGoalOptions opts;
    opts.goal_response_callback = [this](const GoalHandle::SharedPtr & handle) {
        if (!handle) {
          RCLCPP_WARN(get_logger(), "goal rejected");
          emit("goal_rejected");
          goal_pending_ = false;
          logic_.goal_rejected(now().seconds());
          return;
        }
        handle_ = handle;
        RCLCPP_INFO(get_logger(), "goal accepted");
        emit("goal_accepted");
      };
    opts.feedback_callback = [this](GoalHandle::SharedPtr,
      const std::shared_ptr<const NavigateToPose::Feedback> fb) {
        const double t = now().seconds();
        if (t - last_feedback_log_ >= feedback_period_s_) {
          last_feedback_log_ = t;
          RCLCPP_INFO(get_logger(), "feedback: %.2f m remaining", fb->distance_remaining);
          char e[96];
          std::snprintf(e, sizeof(e), "\"distance_remaining\": %.3f", fb->distance_remaining);
          emit("feedback", e);
        }
      };
    opts.result_callback = [this](const GoalHandle::WrappedResult & result) {
        handle_.reset();
        goal_pending_ = false;
        const char * name = "unknown";
        switch (result.code) {
          case rclcpp_action::ResultCode::SUCCEEDED: name = "succeeded"; break;
          case rclcpp_action::ResultCode::ABORTED: name = "aborted"; break;
          case rclcpp_action::ResultCode::CANCELED: name = "canceled"; break;
          default: break;
        }
        RCLCPP_INFO(get_logger(), "goal %s", name);
        emit(name);
        logic_.goal_finished(now().seconds());
      };

    RCLCPP_INFO(
      get_logger(), "%s %.2f for %d frames: sending NavigateToPose to (%.2f, %.2f)",
      v.label.c_str(), v.score, logic_.streak(), goal_x_, goal_y_);
    logic_.goal_sent();
    goal_pending_ = true;
    goal_sent_at_ = now().seconds();
    client_->async_send_goal(goal, opts);
    emit("goal_sent", extra);
  }

  // A goal that runs too long is cancelled; its result callback (CANCELED)
  // then starts the cooldown. A goal the server never answered is dropped.
  void check_timeout()
  {
    if (!goal_pending_ || goal_timeout_s_ <= 0 ||
      now().seconds() - goal_sent_at_ <= goal_timeout_s_)
    {
      return;
    }
    if (handle_) {
      RCLCPP_WARN(get_logger(), "goal took longer than %.1f s, cancelling", goal_timeout_s_);
      emit("timeout_cancel");
      client_->async_cancel_goal(handle_);
      goal_sent_at_ = now().seconds();  // give the cancel a full timeout before giving up
      handle_.reset();
    } else {
      RCLCPP_WARN(get_logger(), "no answer from %s, giving up on the goal", action_name_.c_str());
      emit("timeout_no_response");
      goal_pending_ = false;
      logic_.goal_finished(now().seconds());
    }
  }

  std::string classes_text_;
  PatrolLogic logic_;
  std::string action_name_;
  std::string goal_frame_;
  double goal_x_{0.0};
  double goal_y_{0.0};
  double goal_yaw_{0.0};
  double goal_timeout_s_{120.0};
  double feedback_period_s_{1.0};
  double goal_sent_at_{0.0};
  double first_stamp_{0.0};
  bool goal_pending_{false};
  double last_feedback_log_{0.0};
  rclcpp_action::Client<NavigateToPose>::SharedPtr client_;
  GoalHandle::SharedPtr handle_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr events_pub_;
  rclcpp::Subscription<vision_msgs::msg::Detection2DArray>::SharedPtr det_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace ppe_patrol

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ppe_patrol::PpePatrolNode>());
  rclcpp::shutdown();
  return 0;
}
