from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import io
from unittest.mock import patch
from contextlib import redirect_stdout
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.observability import observe


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "fixture.duckdb"
        self.config = dict(sample=dict(start_date="2025-04-01", end_date="2025-04-03", chunk_days=3),
                           paths=dict(database=str(self.db), outputs_dir=str(self.root)))
        self.policy = dict(freshness_grace_days=2, minimum_row_ratio=0.9, maximum_row_ratio=1.5)
        with duckdb.connect(str(self.db)) as c:
            c.execute("CREATE SCHEMA metadata; CREATE SCHEMA silver")
            c.execute("CREATE TABLE metadata.dataset_version AS SELECT 'sample' AS mode")
            c.execute("CREATE TABLE silver.fact_pitch AS SELECT i AS pitch_id, DATE '2025-04-03' AS game_date FROM range(100) t(i)")

    def run_observation(self, **kwargs):
        return observe(self.config, self.policy, now=datetime(2026, 9, 13, tzinfo=timezone.utc),
                       checks=[("unique", "SELECT COUNT(*)=COUNT(DISTINCT pitch_id) FROM silver.fact_pitch", True)], **kwargs)

    def check(self, report, name):
        return next(c for c in report["checks"] if c["check"] == name)

    def test_historical_sample_and_successful_baseline(self):
        first = self.run_observation()
        second = self.run_observation()
        self.assertEqual(first["status"], "pass")
        self.assertEqual(self.check(first, "schema_drift")["status"], "bootstrap")
        self.assertEqual(self.check(second, "schema_drift")["status"], "pass")
        self.assertEqual(self.check(second, "row_volume")["detail"]["baseline_run"], first["run_id"])

    def test_volume_failure_never_poison_baseline_and_recovery_is_recorded(self):
        first = self.run_observation()
        with duckdb.connect(str(self.db)) as c:
            c.execute("DELETE FROM silver.fact_pitch WHERE pitch_id >= 20")
        bad = self.run_observation()
        retry = self.run_observation()
        self.assertEqual(bad["exit_code"], 2)
        self.assertEqual(self.check(retry, "row_volume")["detail"]["baseline_run"], first["run_id"])
        with duckdb.connect(str(self.db)) as c:
            c.execute("INSERT INTO silver.fact_pitch SELECT i, DATE '2025-04-03' FROM range(20,100) t(i)")
        recovered = self.run_observation()
        self.assertEqual(recovered["status"], "pass")
        with closing(sqlite3.connect(self.root / "observability/history.sqlite")) as c:
            self.assertEqual(c.execute("SELECT status FROM observations ORDER BY id").fetchall(),
                             [("pass",), ("error",), ("error",), ("pass",)])

    def test_schema_addition_stays_failed_on_retry(self):
        self.run_observation()
        with duckdb.connect(str(self.db)) as c:
            c.execute("ALTER TABLE silver.fact_pitch ADD COLUMN unexpected INTEGER")
        for _ in range(2):
            self.assertEqual(self.check(self.run_observation(), "schema_drift")["status"], "error")

    def test_missing_column_records_failure_before_exit(self):
        self.run_observation()
        with duckdb.connect(str(self.db)) as c:
            c.execute("ALTER TABLE silver.fact_pitch DROP COLUMN game_date")
        bad = self.run_observation()
        self.assertEqual(bad["status"], "error")
        stored = json.loads((self.root / "observability/latest.json").read_text())
        self.assertEqual(stored["run_id"], bad["run_id"])
        self.assertEqual(self.check(bad, "collection")["status"], "error")

    def test_stale_and_empty_input(self):
        with duckdb.connect(str(self.db)) as c:
            c.execute("UPDATE silver.fact_pitch SET game_date=DATE '2025-03-01'")
        self.assertEqual(self.run_observation()["exit_code"], 1)
        with duckdb.connect(str(self.db)) as c:
            c.execute("DELETE FROM silver.fact_pitch")
        self.assertEqual(self.run_observation()["exit_code"], 2)

    def test_quality_sql_failure_is_persisted(self):
        with duckdb.connect(str(self.db)) as c:
            c.execute("ALTER TABLE silver.fact_pitch DROP COLUMN pitch_id")
        bad = self.run_observation()
        self.assertEqual(bad["quality_checks"][0]["status"], "FAIL")
        self.assertEqual(bad["exit_code"], 2)

    def test_invalid_policy_rejected(self):
        self.policy["minimum_row_ratio"] = -1
        with self.assertRaises(ValueError):
            self.run_observation()

    def test_quality_entrypoint_persists_then_exits_before_exports(self):
        from src import validate_data
        with duckdb.connect(str(self.db)) as c:
            c.execute("DELETE FROM silver.fact_pitch")
        with patch("sys.argv", ["validate_data"]), patch.object(validate_data, "load_config", side_effect=[self.config, self.policy]), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                validate_data.main()
        self.assertEqual(error.exception.code, 2)
        self.assertTrue((self.root / "data_quality_report.csv").is_file())
        self.assertTrue((self.root / "observability/latest.json").is_file())
        self.assertFalse((self.root / "measurement_coverage.csv").exists())

    def test_missing_database_does_not_create_a_source_file(self):
        missing = self.root / "missing.duckdb"
        self.config["paths"]["database"] = str(missing)
        self.assertEqual(self.run_observation()["exit_code"], 2)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
