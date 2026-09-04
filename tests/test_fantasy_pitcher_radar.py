from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.build_fantasy_pitcher_radar import PROFILE_WEIGHTS, WINDOW_MINIMUMS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RADAR_PATH = PROJECT_ROOT / "outputs" / "fantasy" / "pitcher_fantasy_radar.csv"
MANIFEST_PATH = PROJECT_ROOT / "outputs" / "fantasy" / "fantasy_radar_manifest.json"


class FantasyPitcherRadarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = pd.read_csv(RADAR_PATH)
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_profile_weights_sum_to_one(self):
        for profile in PROFILE_WEIGHTS.values():
            total = sum(float(value) for key, value in profile.items() if key != "label")
            self.assertAlmostEqual(total, 1.0)

    def test_artifact_keys_are_unique_and_complete(self):
        self.assertFalse(self.frame.empty)
        self.assertFalse(
            self.frame.duplicated(["pitcher_id", "window_days", "profile_key"]).any()
        )
        self.assertEqual(set(self.frame["window_days"]), set(WINDOW_MINIMUMS))
        self.assertEqual(set(self.frame["profile_key"]), set(PROFILE_WEIGHTS))
        self.assertEqual(len(self.frame), self.manifest["rows"])

    def test_scores_and_ranks_are_valid(self):
        self.assertTrue(self.frame["fantasy_signal"].between(0, 100).all())
        for _, group in self.frame.groupby(["window_days", "profile_key"]):
            self.assertEqual(sorted(group["rank"].tolist()), list(range(1, len(group) + 1)))
            ranked_scores = group.sort_values("rank")["fantasy_signal"].tolist()
            self.assertEqual(ranked_scores, sorted(ranked_scores, reverse=True))

    def test_insight_fields_are_bounded_and_explainable(self):
        self.assertTrue((self.frame["sample_strength_multiple"] >= 1).all())
        self.assertEqual(
            set(self.frame["sample_strength"]),
            {"Established sample", "Solid sample", "Qualified sample"},
        )
        self.assertTrue(
            set(self.frame["trend_status"]).issubset(
                {"Newly qualified", "Rising", "Stable", "Cooling"}
            )
        )
        self.assertTrue(
            set(self.frame["research_action"]).issubset(
                {
                    "Check availability",
                    "Roster fit review",
                    "Streaming review",
                    "Buy-low review",
                    "Monitor",
                }
            )
        )
        reconstructed_gap = 0.5 * (
            self.frame["expected_whiff_gap_pp"]
            + self.frame["expected_hard_hit_suppression_gap_pp"]
        )
        self.assertTrue(
            (reconstructed_gap - self.frame["underlying_skill_gap_pp"]).abs().lt(1e-9).all()
        )

    def test_each_window_respects_workload_minimums(self):
        for window_days, minimums in WINDOW_MINIMUMS.items():
            rows = self.frame[self.frame["window_days"] == window_days]
            self.assertTrue((rows["pitches"] >= minimums["pitches"]).all())
            self.assertTrue((rows["batters_faced"] >= minimums["batters_faced"]).all())
            self.assertTrue((rows["expected_swings"] >= minimums["expected_swings"]).all())
            self.assertTrue(
                (rows["expected_batted_balls"] >= minimums["expected_batted_balls"]).all()
            )


if __name__ == "__main__":
    unittest.main()
