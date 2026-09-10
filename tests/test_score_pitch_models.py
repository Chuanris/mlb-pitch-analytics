from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.score_pitch_models import TARGETS, leaderboard_rows


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREDICTION_DIR = PROJECT_ROOT / "outputs" / "predictions"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"
RECENT_ARTIFACTS_AVAILABLE = (
    (PREDICTION_DIR / "prediction_manifest.json").exists()
    and all(
        (PREDICTION_DIR / f"{target}_recent_predictions.parquet").exists()
        for target in TARGETS
    )
)
TEST_ARTIFACTS_AVAILABLE = all(
    (MODEL_DIR / f"{target}_model_metrics.json").exists()
    and (PREDICTION_DIR / f"{target}_test_predictions.parquet").exists()
    for target in TARGETS
)
LEADERBOARD_ARTIFACT_AVAILABLE = (PREDICTION_DIR / "model_leaderboards.csv").exists()


class PitchModelScoringTests(unittest.TestCase):
    @unittest.skipUnless(
        RECENT_ARTIFACTS_AVAILABLE,
        "Generated recent prediction artifacts are not available in this checkout",
    )
    def test_recent_monitoring_is_separate_and_supports_two_30_day_windows(self):
        manifest = json.loads((PREDICTION_DIR / "prediction_manifest.json").read_text())
        end = pd.Timestamp(manifest["recent_monitoring"]["data_through"])
        for target in TARGETS:
            recent = pd.read_parquet(PREDICTION_DIR / f"{target}_recent_predictions.parquet")
            dates = pd.to_datetime(recent["game_date"])
            self.assertEqual(len(recent), manifest["recent_monitoring"]["rows"][target])
            self.assertTrue(dates.between(end - pd.Timedelta(days=59), end).all())
            self.assertEqual(dates.max(), end)
            self.assertFalse(recent["pitch_id"].duplicated().any())

    def test_leaderboard_direction_rewards_more_whiffs(self):
        frame = pd.DataFrame(
            {
                "pitcher_id": [1, 1, 2, 2],
                "pitcher_name": ["A", "A", "B", "B"],
                "pitcher_team": ["AAA", "AAA", "BBB", "BBB"],
                "pitch_name": ["Slider", "Slider", "Fastball", "Fastball"],
                "actual_event": [1, 0, 0, 0],
                "predicted_probability": [0.7, 0.5, 0.2, 0.2],
                "release_speed": [85.0, 86.0, 95.0, 96.0],
                "game_date": pd.to_datetime(["2026-07-01"] * 4),
            }
        )
        rows = leaderboard_rows(frame, TARGETS["whiff"], "Pitcher", 2)
        self.assertEqual(rows.iloc[0]["entity_label"], "A")
        self.assertGreater(rows.iloc[0]["model_edge_pp"], 0)

    def test_leaderboard_direction_rewards_less_hard_contact(self):
        frame = pd.DataFrame(
            {
                "pitcher_id": [1, 1, 2, 2],
                "pitcher_name": ["A", "A", "B", "B"],
                "pitcher_team": ["AAA", "AAA", "BBB", "BBB"],
                "pitch_name": ["Sweeper", "Sweeper", "Sinker", "Sinker"],
                "actual_event": [0, 0, 1, 0],
                "predicted_probability": [0.2, 0.2, 0.6, 0.4],
                "release_speed": [84.0, 85.0, 94.0, 95.0],
                "game_date": pd.to_datetime(["2026-07-01"] * 4),
            }
        )
        rows = leaderboard_rows(frame, TARGETS["hard_hit"], "Pitcher", 2)
        self.assertEqual(rows.iloc[0]["entity_label"], "A")
        self.assertGreater(rows.iloc[0]["model_edge_pp"], 0)

    @unittest.skipUnless(
        TEST_ARTIFACTS_AVAILABLE,
        "Generated test prediction artifacts are not available in this checkout",
    )
    def test_prediction_artifacts_reconcile_to_test_manifests(self):
        for target_key in TARGETS:
            manifest = json.loads(
                (MODEL_DIR / f"{target_key}_model_metrics.json").read_text(encoding="utf-8")
            )
            frame = pd.read_parquet(
                PREDICTION_DIR / f"{target_key}_test_predictions.parquet"
            )
            champion = manifest["champion"]
            self.assertEqual(len(frame), manifest["metrics"][champion]["test"]["rows"])
            self.assertEqual(frame["pitch_id"].nunique(), len(frame))
            self.assertEqual(set(frame["model"]), {champion})
            self.assertTrue(frame["predicted_probability"].between(0, 1).all())
            self.assertEqual(
                frame["game_date"].min().date().isoformat(), manifest["split"]["test_start"]
            )
            self.assertEqual(
                frame["game_date"].max().date().isoformat(), manifest["split"]["test_end"]
            )

    @unittest.skipUnless(
        LEADERBOARD_ARTIFACT_AVAILABLE,
        "Generated model leaderboard is not available in this checkout",
    )
    def test_leaderboard_artifact_respects_sample_thresholds(self):
        frame = pd.read_csv(PREDICTION_DIR / "model_leaderboards.csv")
        self.assertTrue((frame["sample_size"] >= frame["minimum_sample"]).all())
        for _, group in frame.groupby(["target_key", "entity_type"]):
            expected = list(range(1, len(group) + 1))
            self.assertEqual(group.sort_values("rank")["rank"].tolist(), expected)


if __name__ == "__main__":
    unittest.main()
