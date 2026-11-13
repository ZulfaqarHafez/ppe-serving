// Unit tests for the debounce and cooldown rules of the patrol node.

#include <gtest/gtest.h>

#include <vector>

#include "ppe_patrol/patrol_logic.hpp"

using ppe_patrol::PatrolConfig;
using ppe_patrol::PatrolLogic;
using ppe_patrol::PatrolState;
using ppe_patrol::Seen;

namespace
{
PatrolConfig config()
{
  PatrolConfig c;
  c.violation_classes = {"No-Helmet", "No-vest"};
  c.min_confidence = 0.5;
  c.consecutive_frames = 3;
  c.cooldown_s = 10.0;
  return c;
}
const std::vector<Seen> kViolation = {{"Vest", 0.9}, {"No-Helmet", 0.62}};
const std::vector<Seen> kWeak = {{"No-Helmet", 0.49}};
const std::vector<Seen> kCompliant = {{"Helmet", 0.8}, {"Vest", 0.7}};
}  // namespace

TEST(PatrolLogic, FiresAfterNConsecutiveFrames)
{
  PatrolLogic p(config());
  EXPECT_FALSE(p.on_frame(kViolation, 0.0));
  EXPECT_FALSE(p.on_frame(kViolation, 0.1));
  EXPECT_TRUE(p.on_frame(kViolation, 0.2));
  EXPECT_EQ(p.last_violation().label, "No-Helmet");
  EXPECT_DOUBLE_EQ(p.streak_start(), 0.0);
}

TEST(PatrolLogic, BreakInStreakResets)
{
  PatrolLogic p(config());
  EXPECT_FALSE(p.on_frame(kViolation, 0.0));
  EXPECT_FALSE(p.on_frame(kViolation, 0.1));
  EXPECT_FALSE(p.on_frame(kCompliant, 0.2));
  EXPECT_FALSE(p.on_frame(kViolation, 0.3));
  EXPECT_FALSE(p.on_frame(kViolation, 0.4));
  EXPECT_TRUE(p.on_frame(kViolation, 0.5));
  EXPECT_DOUBLE_EQ(p.streak_start(), 0.3);
}

TEST(PatrolLogic, BelowConfidenceAndOtherClassesDoNotCount)
{
  PatrolLogic p(config());
  for (int i = 0; i < 10; ++i) {
    EXPECT_FALSE(p.on_frame(kWeak, i));
    EXPECT_FALSE(p.on_frame(kCompliant, i));
    EXPECT_FALSE(p.on_frame({{"No-gloves", 0.95}}, i));
  }
}

TEST(PatrolLogic, NoSecondGoalWhileActiveOrCoolingDown)
{
  PatrolLogic p(config());
  p.on_frame(kViolation, 0.0);
  p.on_frame(kViolation, 0.1);
  ASSERT_TRUE(p.on_frame(kViolation, 0.2));
  p.goal_sent();
  EXPECT_EQ(p.state(), PatrolState::kGoalActive);
  for (int i = 0; i < 5; ++i) {
    EXPECT_FALSE(p.on_frame(kViolation, 1.0 + i));
  }
  p.goal_finished(6.0);
  EXPECT_EQ(p.state(), PatrolState::kCooldown);
  for (int i = 0; i < 5; ++i) {
    EXPECT_FALSE(p.on_frame(kViolation, 7.0 + i));  // cooldown until 16.0
  }
  // After the cooldown a fresh run of three frames is needed.
  EXPECT_FALSE(p.on_frame(kViolation, 16.0));
  EXPECT_EQ(p.state(), PatrolState::kIdle);
  EXPECT_FALSE(p.on_frame(kViolation, 16.1));
  EXPECT_TRUE(p.on_frame(kViolation, 16.2));
}

TEST(PatrolLogic, GoalNotSentReturnsToIdle)
{
  PatrolLogic p(config());
  p.on_frame(kViolation, 0.0);
  p.on_frame(kViolation, 0.1);
  ASSERT_TRUE(p.on_frame(kViolation, 0.2));
  p.goal_not_sent();
  EXPECT_EQ(p.state(), PatrolState::kIdle);
  EXPECT_FALSE(p.on_frame(kViolation, 0.3));
}

TEST(PatrolLogic, RejectedGoalRetriesAfterShortWait)
{
  PatrolConfig c = config();
  c.retry_after_reject_s = 2.0;
  PatrolLogic p(c);
  p.on_frame(kViolation, 0.0);
  p.on_frame(kViolation, 0.1);
  ASSERT_TRUE(p.on_frame(kViolation, 0.2));
  p.goal_sent();
  p.goal_rejected(0.3);
  EXPECT_FALSE(p.on_frame(kViolation, 1.0));  // still waiting
  EXPECT_FALSE(p.on_frame(kViolation, 2.3));
  EXPECT_FALSE(p.on_frame(kViolation, 2.4));
  EXPECT_TRUE(p.on_frame(kViolation, 2.5));  // well before the 10 s cooldown
}
