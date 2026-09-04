from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.score_pitch_models import TARGETS, leaderboard_rows


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREDICTION_DIR = PROJECT_ROOT / "outputs" / "predictions"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"


class PitchModelScoringTests(unittest.TestCase):
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

    def test_leaderboard_artifact_respects_sample_thresholds(self):
        frame = pd.read_csv(PREDICTION_DIR / "model_leaderboards.csv")
        self.assertTrue((frame["sample_size"] >= frame["minimum_sample"]).all())
        for _, group in frame.groupby(["target_key", "entity_type"]):
            expected = list(range(1, len(group) + 1))
            self.assertEqual(group.sort_values("rank")["rank"].tolist(), expected)


if __name__ == "__main__":
    unittest.main()
