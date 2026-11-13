// Lifecycle node: sensor_msgs/Image in, vision_msgs/Detection2DArray and an
// annotated image out, using the PPE detector through ONNX Runtime.

#include <chrono>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <cv_bridge/cv_bridge.hpp>
#include <lifecycle_msgs/msg/state.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_lifecycle/lifecycle_node.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <vision_msgs/msg/detection2_d_array.hpp>

#include "ppe_detector/onnx_detector.hpp"
#include "ppe_detector/ppe_core.hpp"

namespace ppe_detector
{

using CallbackReturn = rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn;

class PpeDetectorNode : public rclcpp_lifecycle::LifecycleNode
{
public:
  explicit PpeDetectorNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions())
  : rclcpp_lifecycle::LifecycleNode("ppe_detector", options)
  {
    std::string default_model;
    try {
      default_model = ament_index_cpp::get_package_share_directory("ppe_detector") +
        "/models/ppe_yolov8s_320_int8dyn.onnx";
    } catch (const std::exception &) {
      default_model = "ppe_yolov8s_320_int8dyn.onnx";
    }
    declare_parameter("model_path", default_model);
    declare_parameter("input_size", 320);
    declare_parameter("intra_op_threads", 0);
    declare_parameter("score_threshold", 0.25);
    declare_parameter("candidate_floor", 0.05);
    declare_parameter("iou_threshold", 0.7);
    declare_parameter("image_topic", "camera/image_raw");
    declare_parameter("detections_topic", "detections");
    declare_parameter("annotated_topic", "detections/image");
    declare_parameter("publish_annotated", true);
    declare_parameter("image_queue_depth", 1);
    declare_parameter("image_reliability", "reliable");
  }

  CallbackReturn on_configure(const rclcpp_lifecycle::State &) override
  {
    DetectorOptions opts;
    opts.model_path = get_parameter("model_path").as_string();
    opts.input_size = static_cast<int>(get_parameter("input_size").as_int());
    opts.intra_op_threads = static_cast<int>(get_parameter("intra_op_threads").as_int());
    score_threshold_ = get_parameter("score_threshold").as_double();
    candidate_floor_ = get_parameter("candidate_floor").as_double();
    iou_threshold_ = get_parameter("iou_threshold").as_double();
    publish_annotated_ = get_parameter("publish_annotated").as_bool();
    try {
      detector_ = std::make_unique<OnnxDetector>(opts);
    } catch (const std::exception & e) {
      RCLCPP_ERROR(get_logger(), "cannot load model %s: %s", opts.model_path.c_str(), e.what());
      return CallbackReturn::FAILURE;
    }
    RCLCPP_INFO(
      get_logger(), "loaded %s (input %d, intra-op threads %s)", opts.model_path.c_str(),
      opts.input_size,
      opts.intra_op_threads > 0 ? std::to_string(opts.intra_op_threads).c_str() : "default");

    const auto reliable = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();
    det_pub_ = create_publisher<vision_msgs::msg::Detection2DArray>(
      get_parameter("detections_topic").as_string(), reliable);
    img_pub_ = create_publisher<sensor_msgs::msg::Image>(
      get_parameter("annotated_topic").as_string(), rclcpp::QoS(rclcpp::KeepLast(2)).reliable());
    timing_pub_ = create_publisher<std_msgs::msg::Float64MultiArray>("~/timing", reliable);
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_activate(const rclcpp_lifecycle::State & state) override
  {
    LifecycleNode::on_activate(state);
    // Keep only the newest frame so a slow detector drops stale frames instead
    // of queueing them. Reliable by default: on this machine, best effort lost
    // most 1 MB frames sent over UDP between processes (default socket
    // buffers), see results/benchmark.md. Set "best_effort" for a sensor-data
    // style subscription.
    const auto depth = static_cast<size_t>(get_parameter("image_queue_depth").as_int());
    auto qos = rclcpp::SensorDataQoS().keep_last(depth);
    if (get_parameter("image_reliability").as_string() != "best_effort") {
      qos.reliable();
    }
    image_sub_ = create_subscription<sensor_msgs::msg::Image>(
      get_parameter("image_topic").as_string(), qos,
      [this](sensor_msgs::msg::Image::ConstSharedPtr msg) {on_image(msg);});
    RCLCPP_INFO(get_logger(), "active, listening on %s", image_sub_->get_topic_name());
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_deactivate(const rclcpp_lifecycle::State & state) override
  {
    image_sub_.reset();
    LifecycleNode::on_deactivate(state);
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_cleanup(const rclcpp_lifecycle::State &) override
  {
    image_sub_.reset();
    det_pub_.reset();
    img_pub_.reset();
    timing_pub_.reset();
    detector_.reset();
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_shutdown(const rclcpp_lifecycle::State & state) override
  {
    return on_cleanup(state);
  }

private:
  void on_image(const sensor_msgs::msg::Image::ConstSharedPtr & msg)
  {
    const auto t0 = std::chrono::steady_clock::now();
    cv_bridge::CvImageConstPtr cv;
    try {
      cv = cv_bridge::toCvShare(msg, "rgb8");
    } catch (const std::exception & e) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000, "cannot convert %s image: %s",
        msg->encoding.c_str(), e.what());
      return;
    }
    const cv::Mat & rgb = cv->image;
    DetectTiming timing;
    const auto candidates = detector_->detect(
      rgb.data, rgb.cols, rgb.rows, static_cast<int>(rgb.step), candidate_floor_, &timing);
    const auto kept = select_detections(candidates, score_threshold_, iou_threshold_);

    vision_msgs::msg::Detection2DArray out;
    out.header = msg->header;
    for (const auto & d : kept) {
      vision_msgs::msg::Detection2D det;
      det.header = msg->header;
      det.id = kClassNames[d.class_id];
      det.bbox.center.position.x = (d.x1 + d.x2) / 2.0;
      det.bbox.center.position.y = (d.y1 + d.y2) / 2.0;
      det.bbox.size_x = d.x2 - d.x1;
      det.bbox.size_y = d.y2 - d.y1;
      vision_msgs::msg::ObjectHypothesisWithPose hyp;
      hyp.hypothesis.class_id = kClassNames[d.class_id];
      hyp.hypothesis.score = d.score;
      det.results.push_back(hyp);
      out.detections.push_back(det);
    }
    det_pub_->publish(out);

    if (publish_annotated_ && img_pub_->get_subscription_count() > 0) {
      publish_annotated(*cv, kept);
    }
    std_msgs::msg::Float64MultiArray t;
    t.data = {timing.preprocess_ms, timing.inference_ms, timing.decode_ms,
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count()};
    timing_pub_->publish(t);
  }

  void publish_annotated(const cv_bridge::CvImage & src, const std::vector<Detection> & kept)
  {
    cv_bridge::CvImage out(src.header, "rgb8", src.image.clone());
    const cv::Scalar missing(166, 58, 43);  // RGB, the site's "item missing" colour
    const cv::Scalar worn(46, 125, 50);
    for (const auto & d : kept) {
      const std::string label = kClassNames[d.class_id];
      const cv::Scalar colour = is_missing_item(label) ? missing : worn;
      cv::rectangle(out.image, cv::Point(d.x1, d.y1), cv::Point(d.x2, d.y2), colour, 2);
      char text[64];
      std::snprintf(text, sizeof(text), "%s %.2f", label.c_str(), d.score);
      int base = 0;
      const cv::Size ts = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, 0.45, 1, &base);
      const int ty = std::max(static_cast<int>(d.y1), ts.height + 4);
      cv::rectangle(
        out.image, cv::Point(d.x1, ty - ts.height - 4), cv::Point(d.x1 + ts.width + 4, ty),
        colour, cv::FILLED);
      cv::putText(
        out.image, text, cv::Point(d.x1 + 2, ty - 3), cv::FONT_HERSHEY_SIMPLEX, 0.45,
        cv::Scalar(255, 255, 255), 1, cv::LINE_AA);
    }
    img_pub_->publish(*out.toImageMsg());
  }

  std::unique_ptr<OnnxDetector> detector_;
  double score_threshold_{0.25};
  double candidate_floor_{0.05};
  double iou_threshold_{0.7};
  bool publish_annotated_{true};
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_sub_;
  rclcpp_lifecycle::LifecyclePublisher<vision_msgs::msg::Detection2DArray>::SharedPtr det_pub_;
  rclcpp_lifecycle::LifecyclePublisher<sensor_msgs::msg::Image>::SharedPtr img_pub_;
  rclcpp_lifecycle::LifecyclePublisher<std_msgs::msg::Float64MultiArray>::SharedPtr timing_pub_;
};

}  // namespace ppe_detector

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<ppe_detector::PpeDetectorNode>();
  // Optional self-transition for scripts that do not run a lifecycle manager.
  if (node->declare_parameter("autostart", false)) {
    if (node->configure().id() == lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE) {
      node->activate();
    }
  }
  rclcpp::spin(node->get_node_base_interface());
  rclcpp::shutdown();
  return 0;
}
