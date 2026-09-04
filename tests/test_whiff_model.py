from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.train_whiff_model import (
    ALL_NUMERIC_FEATURES,
    FORBIDDEN_LEAKAGE_COLUMNS,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    assert_feature_contract,
    apply_platt_calibrator,
    evaluate_predictions,
    fit_baseline,
    fit_platt_calibrator,
    make_time_split,
    predict_baseline,
)


class WhiffModelTests(unittest.TestCase):
    def test_model_feature_contract_excludes_outcomes_and_future_data(self):
        model_features = set(ALL_NUMERIC_FEATURES + CATEGORICAL_FEATURES)
        self.assertFalse(model_features.intersection(FORBIDDEN_LEAKAGE_COLUMNS))
        assert_feature_contract(ALL_NUMERIC_FEATURES + CATEGORICAL_FEATURES)

    def test_feature_contract_rejects_leakage(self):
        with self.assertRaises(ValueError):
            assert_feature_contract(["release_speed", "launch_speed"])

    def test_time_split_is_strictly_chronological(self):
        frame = pd.DataFrame(
            {
                "season": [2025, 2025, 2026, 2026, 2026, 2026],
                "game_date": [
                    "2025-04-01",
                    "2025-09-28",
                    "2026-03-25",
                    "2026-04-01",
                    "2026-07-01",
                    "2026-08-30",
                ],
                "target_whiff": [0, 1, 0, 1, 0, 1],
            }
        )
        split = make_time_split(frame)
        self.assertLess(split.train["game_date"].max(), split.validation["game_date"].min())
        self.assertLess(split.validation["game_date"].max(), split.test["game_date"].min())

    def test_smoothed_baseline_falls_back_for_unseen_group(self):
        train = pd.DataFrame(
            {
                "pitch_type": ["FF", "FF", "SL", "SL"],
                "balls": [0, 0, 1, 1],
                "strikes": [0, 0, 2, 2],
                "batter_stand": ["R", "R", "L", "L"],
                "target_whiff": [0, 1, 1, 1],
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
        model = fit_baseline(train)
        predicted = predict_baseline(model, evaluation)
        self.assertAlmostEqual(predicted[0], train["target_whiff"].mean())

    def test_metrics_are_finite(self):
        metrics = evaluate_predictions(pd.Series([0, 0, 1, 1]), np.array([0.1, 0.3, 0.7, 0.9]))
        for value in metrics.values():
            self.assertTrue(np.isfinite(value))

    def test_platt_calibrator_returns_monotonic_probabilities(self):
        raw = np.array([0.05, 0.15, 0.35, 0.55, 0.75, 0.9])
        observed = pd.Series([0, 0, 0, 1, 1, 1])
        calibrator = fit_platt_calibrator(observed, raw)
        calibrated = apply_platt_calibrator(calibrator, raw)
        self.assertTrue(np.all(np.diff(calibrated) > 0))
        self.assertTrue(np.all((calibrated > 0) & (calibrated < 1)))


if __name__ == "__main__":
    unittest.main()
