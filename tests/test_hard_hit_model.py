from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.train_hard_hit_model import (
    HARD_HIT_MATCHUP_NUMERIC_FEATURES,
    HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES,
    HARD_HIT_ROLLING_NUMERIC_FEATURES,
    TARGET_COLUMN,
    evaluate_predictions,
    fit_baseline,
    predict_baseline,
)


class HardHitModelTests(unittest.TestCase):
    def test_rolling_features_do_not_include_contact_outcomes(self):
        forbidden_tokens = {"launch_speed", "launch_angle", "estimated_woba"}
        all_history_features = (
            HARD_HIT_ROLLING_NUMERIC_FEATURES
            + HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
            + HARD_HIT_MATCHUP_NUMERIC_FEATURES
        )
        self.assertFalse(set(all_history_features).intersection(forbidden_tokens))

    def test_smoothed_baseline_falls_back_for_unseen_group(self):
        train = pd.DataFrame(
            {
                "pitch_type": ["FF", "FF", "SL", "SL"],
                "balls": [0, 0, 1, 1],
                "strikes": [0, 0, 2, 2],
                "batter_stand": ["R", "R", "L", "L"],
                TARGET_COLUMN: [0, 1, 1, 1],
            }
        )
        evaluation = pd.DataFrame(
            {
                "pitch_type": ["CH"],
                "balls": [3],
                "strikes": [2],
                "batter_stand": ["R"],
            }
        )
        predicted = predict_baseline(fit_baseline(train), evaluation)
        self.assertAlmostEqual(predicted[0], train[TARGET_COLUMN].mean())

    def test_metrics_are_finite(self):
        metrics = evaluate_predictions(
            pd.Series([0, 0, 1, 1]),
            np.array([0.1, 0.3, 0.7, 0.9]),
        )
        for value in metrics.values():
            self.assertTrue(np.isfinite(value))


if __name__ == "__main__":
    unittest.main()
