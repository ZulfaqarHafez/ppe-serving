// Replays still images on a camera topic, as a stand-in for a camera.
//
// Publishes rgb8 sensor_msgs/Image, stamped with the current time just before
// publishing. header.frame_id is the sample id (file stem) unless `frame_id`
// is set, so detections can be traced back to their image.

#include <chrono>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

namespace ppe_bringup
{

class SampleImagePublisher : public rclcpp::Node
{
public:
  SampleImagePublisher()
  : rclcpp::Node("sample_image_publisher")
  {
    const auto dir = declare_parameter(
      "samples_dir", ament_index_cpp::get_package_share_directory("ppe_bringup") + "/samples");
    const auto ids = declare_parameter(
      "images", std::vector<std::string>{
        "site-backs", "rooftop-cctv", "plant-cctv", "hi-vis-walk", "packing-cctv"});
    frame_id_ = declare_parameter("frame_id", "");
    repeat_each_ = std::max<int64_t>(1, declare_parameter("repeat_each", 1));
    loop_ = declare_parameter("loop", true);
    max_frames_ = declare_parameter("max_frames", 0);
    const double rate = declare_parameter("rate_hz", 5.0);
    const double start_delay = declare_parameter("start_delay_s", 0.0);

    for (const auto & id : ids) {
      cv::Mat bgr = cv::imread(dir + "/" + id + ".png", cv::IMREAD_COLOR);
      if (bgr.empty()) {
        throw std::runtime_error("cannot read " + dir + "/" + id + ".png");
      }
      sensor_msgs::msg::Image msg;
      cv::Mat rgb;
      cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
      msg.height = rgb.rows;
      msg.width = rgb.cols;
      msg.encoding = "rgb8";
      msg.step = rgb.cols * 3;
      msg.data.resize(msg.step * msg.height);
      for (int y = 0; y < rgb.rows; ++y) {
        std::memcpy(&msg.data[y * msg.step], rgb.ptr(y), msg.step);
      }
      msg.header.frame_id = frame_id_.empty() ? id : frame_id_;
      frames_.push_back(std::move(msg));
    }
    pub_ = create_publisher<sensor_msgs::msg::Image>(
      declare_parameter("topic", "camera/image_raw"), rclcpp::QoS(rclcpp::KeepLast(5)));
    RCLCPP_INFO(
      get_logger(), "replaying %zu images at %.1f Hz on %s", frames_.size(), rate,
      pub_->get_topic_name());
    start_at_ = now() + rclcpp::Duration::from_seconds(start_delay);
    timer_ = create_wall_timer(
      std::chrono::duration<double>(1.0 / rate), [this]() {tick();});
  }

private:
  void tick()
  {
    if (now() < start_at_) {
      return;
    }
    const size_t idx = static_cast<size_t>(count_ / repeat_each_);
    if ((!loop_ && idx >= frames_.size()) || (max_frames_ > 0 && count_ >= max_frames_)) {
      timer_->cancel();
      RCLCPP_INFO(get_logger(), "done after %s frames", std::to_string(count_).c_str());
      return;
    }
    auto msg = std::make_unique<sensor_msgs::msg::Image>(frames_[idx % frames_.size()]);
    msg->header.stamp = now();
    pub_->publish(std::move(msg));
    ++count_;
  }

  std::vector<sensor_msgs::msg::Image> frames_;
  std::string frame_id_;
  int64_t repeat_each_{1};
  bool loop_{true};
  int64_t max_frames_{0};
  int64_t count_{0};
  rclcpp::Time start_at_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

}  // namespace ppe_bringup

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ppe_bringup::SampleImagePublisher>());
  rclcpp::shutdown();
  return 0;
}
