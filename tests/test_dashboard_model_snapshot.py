from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "dashboard" / "src" / "data.json"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"
MODEL_MANIFESTS_AVAILABLE = all(
    (MODEL_DIR / f"{target}_model_metrics.json").exists()
    for target in ("whiff", "hard_hit")
)


class DashboardModelSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.evaluation_rows = cls.snapshot["queries"]["model_evaluation"]["rows"]
        cls.calibration_rows = cls.snapshot["queries"]["model_calibration"]["rows"]
        cls.leaderboard_rows = cls.snapshot["queries"]["model_leaderboard"]["rows"]
        cls.prediction_rows = cls.snapshot["queries"]["pitch_model_predictions"]["rows"]
        cls.fantasy_rows = cls.snapshot["queries"]["fantasy_pitcher_radar"]["rows"]
        cls.stream_rows = cls.snapshot["queries"]["matchup_stream_planner"]["rows"]

    def test_snapshot_has_one_champion_per_target(self):
        champions = [row for row in self.evaluation_rows if row["is_champion"]]
        self.assertEqual({row["target_key"] for row in champions}, {"whiff", "hard_hit"})
        self.assertEqual(len(champions), 2)

    @unittest.skipUnless(
        MODEL_MANIFESTS_AVAILABLE,
        "Generated model manifests are not available in this checkout",
    )
    def test_snapshot_champions_reconcile_to_model_manifests(self):
        for target_key in ("whiff", "hard_hit"):
            manifest = json.loads(
                (MODEL_DIR / f"{target_key}_model_metrics.json").read_text(encoding="utf-8")
            )
            row = next(
                item
                for item in self.evaluation_rows
                if item["target_key"] == target_key and item["is_champion"]
            )
            self.assertEqual(row["model"], manifest["champion"])
            self.assertAlmostEqual(
                row["log_loss"],
                manifest["metrics"][manifest["champion"]]["test"]["log_loss"],
            )

    @unittest.skipUnless(
        MODEL_MANIFESTS_AVAILABLE,
        "Generated model manifests are not available in this checkout",
    )
    def test_whiff_calibration_improves_untouched_test(self):
        manifest = json.loads(
            (MODEL_DIR / "whiff_model_metrics.json").read_text(encoding="utf-8")
        )
        raw = manifest["metrics"][manifest["champion_base_model"]]["test"]
        calibrated = manifest["metrics"][manifest["champion"]]["test"]
        self.assertTrue(manifest["probability_calibration"]["accepted"])
        self.assertLess(calibrated["log_loss"], raw["log_loss"])
        self.assertLess(
            calibrated["expected_calibration_error"],
            raw["expected_calibration_error"],
        )

    def test_calibration_query_includes_ideal_and_target_champions(self):
        series = {row["series"] for row in self.calibration_rows}
        self.assertIn("Ideal calibration", series)
        self.assertIn("Whiff \u00b7 calibrated champion", series)
        self.assertIn("Whiff \u00b7 raw champion", series)
        self.assertIn("Hard hit \u00b7 champion", series)

    def test_prediction_queries_cover_both_targets(self):
        self.assertEqual(
            {row["target_key"] for row in self.leaderboard_rows},
            {"whiff", "hard_hit"},
        )
        self.assertEqual(
            {row["target_key"] for row in self.prediction_rows},
            {"whiff", "hard_hit"},
        )
        self.assertEqual(len(self.prediction_rows), 500)

    def test_leaderboard_rows_show_sample_and_expected_rate(self):
        self.assertTrue(self.leaderboard_rows)
        self.assertTrue(
            all(row["sample_size"] >= row["minimum_sample"] for row in self.leaderboard_rows)
        )
        self.assertTrue(
            all(0 <= row["predicted_rate"] <= 1 for row in self.leaderboard_rows)
        )

    def test_fantasy_query_has_all_profiles_and_windows(self):
        self.assertTrue(self.fantasy_rows)
        self.assertEqual(
            {row["profile_key"] for row in self.fantasy_rows},
            {"roto_balance", "strikeout_upside", "ratio_protection"},
        )
        self.assertEqual({row["window_days"] for row in self.fantasy_rows}, {7, 14, 30})
        self.assertTrue(all(0 <= row["fantasy_signal"] <= 100 for row in self.fantasy_rows))

    def test_stream_planner_preserves_probable_and_tbd_status(self):
        self.assertTrue(self.stream_rows)
        self.assertEqual(
            {row["profile_key"] for row in self.stream_rows},
            {"roto_balance", "strikeout_upside", "ratio_protection"},
        )
        self.assertTrue(
            {row["probable_status"] for row in self.stream_rows}.issubset(
                {"Confirmed probable", "TBD"}
            )
        )
        self.assertTrue(
            all(row["stream_score"] is None for row in self.stream_rows if row["probable_status"] == "TBD")
        )


if __name__ == "__main__":
    unittest.main()
