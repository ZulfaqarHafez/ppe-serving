#include <vector>

#include "ppe_patrol/patrol_logic.hpp"

namespace ppe_patrol
{

bool PatrolLogic::on_frame(const std::vector<Seen> & detections, double t)
{
  if (state_ == PatrolState::kCooldown && t >= cooldown_until_) {
    state_ = PatrolState::kIdle;
  }
  bool violation = false;
  Seen best;
  for (const auto & d : detections) {
    if (config_.violation_classes.count(d.label) > 0 && d.score >= config_.min_confidence &&
      d.score > best.score)
    {
      best = d;
      violation = true;
    }
  }
  if (state_ != PatrolState::kIdle) {
    // A goal is running or we are cooling down: do not count frames, so a
    // new goal needs a fresh run of N frames afterwards.
    streak_ = 0;
    return false;
  }
  if (!violation) {
    streak_ = 0;
    return false;
  }
  if (streak_ == 0) {
    streak_start_ = t;
  }
  ++streak_;
  last_violation_ = best;
  return streak_ >= config_.consecutive_frames;
}

void PatrolLogic::goal_sent()
{
  state_ = PatrolState::kGoalActive;
  streak_ = 0;
}

void PatrolLogic::goal_finished(double t)
{
  state_ = PatrolState::kCooldown;
  cooldown_until_ = t + config_.cooldown_s;
  streak_ = 0;
}

void PatrolLogic::goal_rejected(double t)
{
  state_ = PatrolState::kCooldown;
  cooldown_until_ = t + config_.retry_after_reject_s;
  streak_ = 0;
}

void PatrolLogic::goal_not_sent()
{
  state_ = PatrolState::kIdle;
  streak_ = 0;
}

}  // namespace ppe_patrol
