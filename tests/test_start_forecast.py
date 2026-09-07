from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.build_start_forecast import (
    MODELS, chronological_predictions, count_bounds, evaluate_backtest,
    settle_archives, upcoming_predictions,
)


BOUNDARIES = dict(train_end="2025-09-28", validation_start="2026-03-25",
                  test_start="2026-06-13", test_end="2026-09-03")


def appearances():
    rows = []
    for index, date in enumerate(["2025-04-01","2025-04-02","2026-03-25","2026-03-26",
                                   "2026-03-27","2026-03-28","2026-06-13","2026-06-14"]):
        for pitcher in (1,2):
            rows.append(dict(game_pk=index+1,game_date=date,pitcher_id=pitcher,pitcher_name=f"P{pitcher}",
                             pitcher_team="A" if pitcher==1 else "B",opponent_team="B" if pitcher==1 else "A",
                             is_starter=True,batters_faced=20,strikeouts=3+index%3+pitcher,pitches=80,
                             game_datetime_utc=pd.Timestamp(date+"T19:00:00Z")))
    return pd.DataFrame(rows)


class StartForecastTests(unittest.TestCase):
    def test_same_day_outcomes_cannot_change_either_starters_forecast(self):
        data = appearances()
        before, _ = chronological_predictions(data, BOUNDARIES)
        data.loc[(data.game_date == "2026-06-13") & (data.pitcher_id == 1), "strikeouts"] = 19
        after, _ = chronological_predictions(data, BOUNDARIES)
        columns = list(MODELS) + ["prior_starts", "pitcher_k_rate", "opponent_k_rate"]
        pd.testing.assert_frame_equal(before.loc[before.game_date == "2026-06-13", columns],
                                      after.loc[after.game_date == "2026-06-13", columns])
        self.assertTrue((pd.to_datetime(before.feature_data_through) < pd.to_datetime(before.game_date)).all())

    def test_test_labels_cannot_choose_model_or_calibration_radius(self):
        predictions, _ = chronological_predictions(appearances(), BOUNDARIES)
        before, _ = evaluate_backtest(predictions, BOUNDARIES)
        predictions.loc[predictions.game_date >= BOUNDARIES["test_start"], "actual_k"] = 20
        after, _ = evaluate_backtest(predictions, BOUNDARIES)
        self.assertEqual(before["champion"], after["champion"])
        self.assertEqual(before["interval_radius"], after["interval_radius"])
        self.assertLess(before["selection_end"], before["calibration_start"])
        self.assertLess(before["calibration_end"], BOUNDARIES["test_start"])

    def test_future_dates_do_not_move_fixed_backtest(self):
        data = appearances()
        before, _ = chronological_predictions(data, BOUNDARIES)
        future = data.iloc[-2:].copy()
        future["game_date"] = "2026-09-04"
        after, _ = chronological_predictions(pd.concat([data,future]), BOUNDARIES)
        pd.testing.assert_frame_equal(before, after)

    def test_integer_interval_contains_only_counts_within_error_radius(self):
        lower, upper = count_bounds([0.5, 5.2], 2.0)
        self.assertEqual(lower.tolist(), [0,4])
        self.assertEqual(upper.tolist(), [2,7])

    def test_only_future_confirmed_starters_are_forecast_with_rookie_fallback(self):
        predictions, history = chronological_predictions(appearances(), BOUNDARIES)
        model, _ = evaluate_backtest(predictions, BOUNDARIES)
        slot = dict(game_pk=50,pitcher_team="A",pitcher_name="Rookie",pitcher_id=99,opponent_team="B",
                    game_date="2026-06-16",game_datetime_utc="2026-06-16T19:00:00Z",probable_status="Confirmed probable")
        slots = pd.DataFrame([slot, dict(slot), dict(slot, game_pk=51, probable_status="TBD"),
                              dict(slot, game_pk=52,game_date="2026-06-14",game_datetime_utc="2026-06-14T19:00:00Z")])
        result = upcoming_predictions(slots, history, model, datetime(2026,6,15,tzinfo=timezone.utc))
        self.assertEqual(len(result),1)
        self.assertEqual(result.iloc[0].prior_starts,0)
        self.assertGreaterEqual(result.iloc[0].predicted_k,0)
        self.assertEqual(result.iloc[0].sample_status,"Limited starting history")

    def test_archive_keeps_first_forecast_and_never_scores_changed_starter_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            early = dict(game_pk=7,pitcher_id=1,generated_at_utc="2026-06-12T20:00:00+00:00",predicted_k=3)
            root.joinpath("one.json").write_text(json.dumps({"predictions":[early, dict(early,pitcher_id=99)]}))
            root.joinpath("two.json").write_text(json.dumps({"predictions":[dict(early,generated_at_utc="2026-06-13T10:00:00+00:00",predicted_k=9)]}))
            result = settle_archives(root, appearances())
            observed = result[result.pitcher_id==1].iloc[0]
            self.assertEqual(observed.predicted_k,3)
            self.assertEqual(observed.outcome_status,"observed")
            changed = result[result.pitcher_id==99].iloc[0]
            self.assertEqual(changed.outcome_status,"did_not_start")
            self.assertTrue(pd.isna(changed.actual_k))

    def test_no_archives_produces_readable_empty_result_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = settle_archives(Path(directory), appearances())
            self.assertTrue(frame.empty)
            self.assertIn("outcome_status",frame.columns)


if __name__ == "__main__":
    unittest.main()
