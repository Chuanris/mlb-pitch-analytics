from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
import unittest

from src.observability_demo import main, run_demo


class ObservabilityDemoTests(unittest.TestCase):
    def test_demo_exposes_pass_attention_and_error_contracts(self):
        result = run_demo()
        scenarios = {item["scenario"]: item for item in result["scenarios"]}

        self.assertTrue(result["verified"])
        self.assertEqual(scenarios["healthy_complete_date"]["status"], "pass")
        self.assertEqual(scenarios["unsettled_date"]["status"], "attention")
        self.assertEqual(
            scenarios["unsettled_date"]["assessment"],
            "unknown_unsettled_date",
        )
        self.assertEqual(scenarios["missing_same_date_coverage"]["status"], "error")
        self.assertEqual(scenarios["missing_same_date_coverage"]["completed_games"], 1)
        self.assertEqual(scenarios["missing_same_date_coverage"]["pitch_games"], 0)
        self.assertEqual(scenarios["missing_same_date_coverage"]["unsettled_games"], 1)

    def test_main_prints_machine_readable_verified_evidence(self):
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["verified"])
        self.assertEqual(len(payload["scenarios"]), 3)


if __name__ == "__main__":
    unittest.main()
