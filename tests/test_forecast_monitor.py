import unittest
import pandas as pd
from src.forecast_monitor import summarize_live


class LiveMonitorTests(unittest.TestCase):
    def test_empty_history_has_schema(self):
        self.assertIn('mae', summarize_live(pd.DataFrame(), '2026-09-04').columns)

    def test_pending_is_unknown_not_perfect(self):
        frame = pd.DataFrame([dict(model_version='a', outcome_status='pending', predicted_k=5,
                                   actual_k=None, lower_k=2, upper_k=8)])
        row = summarize_live(frame, '2026-09-04').iloc[0]
        self.assertEqual(row.status, 'awaiting_outcomes')
        self.assertTrue(pd.isna(row.mae))
        self.assertTrue(pd.isna(row.interval_coverage))

    def test_version_and_metric_denominators(self):
        base = dict(model_version='a', outcome_status='observed', predicted_k=5, actual_k=3, lower_k=3, upper_k=7)
        frame = pd.DataFrame([base, dict(base, predicted_k=1, actual_k=5, lower_k=None),
                              dict(base, outcome_status='did_not_start', actual_k=None),
                              dict(base, actual_k=float('inf')),
                              dict(base, model_version='b', predicted_k=3)])
        rows = summarize_live(frame, '2026-09-04').set_index('model_version')
        self.assertEqual(rows.loc['a', 'observed'], 2)
        self.assertEqual(rows.loc['a', 'mae'], 3)
        self.assertEqual(rows.loc['a', 'bias'], -1)
        self.assertEqual(rows.loc['a', 'interval_rows'], 1)
        self.assertEqual(rows.loc['a', 'interval_coverage'], 1)
        self.assertEqual(rows.loc['a', 'excluded'], 1)
        self.assertEqual(rows.loc['a', 'invalid_outcomes'], 1)
        self.assertEqual(rows.loc['b', 'mae'], 0)
        self.assertEqual(rows.loc['b', 'status'], 'limited_sample')

    def test_threshold_never_claims_validated(self):
        frame = pd.DataFrame([dict(model_version='a', outcome_status='observed', predicted_k=5,
                                   actual_k=5, lower_k=2, upper_k=8)] * 30)
        self.assertEqual(summarize_live(frame, '2026-09-04').iloc[0].status, 'descriptive_only')
