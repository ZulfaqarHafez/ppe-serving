// Decides when a run of PPE violations should send the robot to inspect.
// Kept free of ROS so it can be unit tested.

#ifndef PPE_PATROL__PATROL_LOGIC_HPP_
#define PPE_PATROL__PATROL_LOGIC_HPP_

#include <set>
#include <string>
#include <vector>

namespace ppe_patrol
{

struct Seen
{
  std::string label;
  double score{0.0};
};

struct PatrolConfig
{
  std::set<std::string> violation_classes{"No-Helmet"};
  double min_confidence{0.5};
  int consecutive_frames{3};
  double cooldown_s{10.0};
  /// Wait after a rejected goal (for example Nav2 still starting up).
  double retry_after_reject_s{2.0};
};

enum class PatrolState { kIdle, kGoalActive, kCooldown };

class PatrolLogic
{
public:
  explicit PatrolLogic(const PatrolConfig & config)
  : config_(config) {}

  /// Feed one frame of detections at time `t` (seconds). Returns true when a
  /// goal should be sent now; the caller then calls goal_sent().
  bool on_frame(const std::vector<Seen> & detections, double t);

  /// The strongest qualifying detection in the last frame passed to on_frame.
  const Seen & last_violation() const {return last_violation_;}
  /// Time of the first frame of the current (or just completed) streak.
  double streak_start() const {return streak_start_;}
  int streak() const {return streak_;}
  PatrolState state() const {return state_;}

  void goal_sent();
  /// Goal finished (any outcome): start the cooldown.
  void goal_finished(double t);
  /// Goal rejected by the server: wait retry_after_reject_s, not the cooldown.
  void goal_rejected(double t);
  /// Sending failed before a goal existed (no server): back to idle.
  void goal_not_sent();

private:
  PatrolConfig config_;
  PatrolState state_{PatrolState::kIdle};
  int streak_{0};
  double streak_start_{0.0};
  double cooldown_until_{0.0};
  Seen last_violation_;
};

}  // namespace ppe_patrol

#endif  // PPE_PATROL__PATROL_LOGIC_HPP_
