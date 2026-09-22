from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import io
from unittest.mock import patch
from contextlib import redirect_stdout
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
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
        self.policy = dict(freshness_grace_days=2, minimum_row_ratio=0.9, maximum_row_ratio=1.5,
                           recent_partition_lookback_dates=14,
                           recent_partition_minimum_baseline_dates=1,
                           minimum_pitches_per_game_ratio=0.65,
                           maximum_pitches_per_game_ratio=1.35)
        with duckdb.connect(str(self.db)) as c:
            c.execute("CREATE SCHEMA metadata; CREATE SCHEMA silver")
            c.execute("CREATE TABLE metadata.dataset_version AS SELECT 'sample' AS mode")
            c.execute("CREATE TABLE metadata.pipeline_ranges AS SELECT DATE '2025-04-01' AS start_date, DATE '2025-04-03' AS end_date")
            c.execute("CREATE TABLE silver.fact_game_context AS SELECT 1 AS game_pk, DATE '2025-04-03' AS official_date, 'Final' AS game_status")
            c.execute("INSERT INTO silver.fact_game_context VALUES (2, DATE '2025-04-02', 'Final')")
            c.execute("CREATE TABLE silver.fact_pitch AS SELECT i AS pitch_id, 1 AS game_pk, DATE '2025-04-03' AS game_date FROM range(100) t(i)")
            c.execute("INSERT INTO silver.fact_pitch SELECT -100 + i, 2, DATE '2025-04-02' FROM range(100) t(i)")

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
            c.execute("INSERT INTO silver.fact_pitch SELECT i, 1, DATE '2025-04-03' FROM range(20,100) t(i)")
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
            c.execute("UPDATE silver.fact_game_context SET official_date=DATE '2025-03-01'")
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

    def seed_recent_partitions(self, latest_pitch_rows, latest_games=1):
        with duckdb.connect(str(self.db)) as c:
            c.execute("DELETE FROM silver.fact_pitch")
            c.execute("DELETE FROM silver.fact_game_context")
            c.execute("DELETE FROM metadata.pipeline_ranges")
            c.execute("INSERT INTO metadata.pipeline_ranges VALUES (DATE '2025-03-20', DATE '2025-04-03')")
            for offset in range(8):
                game_date = (date(2025, 3, 27) + timedelta(days=offset)).isoformat()
                games = latest_games if offset == 7 else 2
                pitch_rows = latest_pitch_rows if offset == 7 else 600
                c.execute("INSERT INTO silver.fact_game_context SELECT ? * 10 + i, CAST(? AS DATE), 'Final' FROM range(?) t(i)",
                          [offset, game_date, games])
                c.execute("INSERT INTO silver.fact_pitch SELECT ? * 1000 + i, ? * 10 + (i % ?), CAST(? AS DATE) FROM range(?) t(i)",
                          [offset, offset, games, game_date, pitch_rows])

    def test_recent_partition_normalizes_for_schedule_size(self):
        self.seed_recent_partitions(latest_pitch_rows=300)
        with duckdb.connect(str(self.db)) as c:
            c.execute("INSERT INTO silver.fact_game_context VALUES (999, DATE '2025-04-03', 'Postponed')")
            c.execute("INSERT INTO silver.fact_pitch SELECT 9000 + i, 999, DATE '2025-04-03' FROM range(500) t(i)")
        result = self.check(self.run_observation(), "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["ratio"], 1.0)
        self.assertEqual(result["detail"]["game_coverage_ratio"], 1.0)

    def test_recent_partition_flags_low_daily_pitch_volume(self):
        self.seed_recent_partitions(latest_pitch_rows=100, latest_games=2)
        result = self.check(self.run_observation(), "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "volume_anomaly")
        self.assertLess(result["detail"]["ratio"], self.policy["minimum_pitches_per_game_ratio"])

    def test_recent_partition_flags_low_individual_game_volume(self):
        self.seed_recent_partitions(latest_pitch_rows=4500, latest_games=15)
        with duckdb.connect(str(self.db)) as c:
            c.execute("DELETE FROM silver.fact_pitch WHERE game_pk=84 AND pitch_id >= 8500")
        result = self.check(self.run_observation(), "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "volume_anomaly")
        self.assertEqual(result["detail"]["minimum_game_pitch_rows"], 100)

    def test_missing_game_fails_before_partition_baseline_exists(self):
        with duckdb.connect(str(self.db)) as c:
            c.execute("INSERT INTO silver.fact_game_context VALUES (3, DATE '2025-04-03', 'Final')")
        result = self.check(self.run_observation(), "recent_partition_completeness")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["detail"]["game_coverage_ratio"], 0.5)

    def test_recent_partition_is_attention_with_insufficient_history(self):
        self.policy["recent_partition_minimum_baseline_dates"] = 2
        result = self.check(self.run_observation(), "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "unknown_insufficient_baseline")
        self.assertEqual(result["detail"]["eligible_baseline_dates"], 1)

    def test_freshness_detail_is_not_mutated_by_partition_metrics(self):
        result = self.check(self.run_observation(), "freshness")
        self.assertNotIn("recent_partition", result["detail"])

    def test_freshness_expected_date_uses_los_angeles_boundary(self):
        self.config["sample"] = {
            "ranges": [{
                "season": 2025,
                "start_date": "2025-04-01",
                "end_date": "2025-04-10",
                "chunk_days": 7,
                "latest_complete_day": True,
            }]
        }
        with duckdb.connect(str(self.db)) as connection:
            connection.execute("DELETE FROM silver.fact_pitch WHERE game_date = DATE '2025-04-03'")
            connection.execute("DELETE FROM silver.fact_game_context WHERE official_date = DATE '2025-04-03'")

        report = observe(
            self.config,
            self.policy,
            now=datetime(2025, 4, 4, 2, 0, tzinfo=timezone.utc),
        )
        freshness = self.check(report, "freshness")

        self.assertEqual(freshness["status"], "pass")
        self.assertEqual(freshness["detail"]["data_through"], "2025-04-02")
        self.assertEqual(freshness["detail"]["expected_through"], "2025-04-02")
        self.assertEqual(freshness["detail"]["lag_days"], 0)

    def test_freshness_rejects_current_los_angeles_date_as_complete(self):
        self.config["sample"] = {
            "ranges": [{
                "season": 2025,
                "start_date": "2025-04-01",
                "end_date": "2025-04-10",
                "chunk_days": 7,
                "latest_complete_day": True,
            }]
        }

        report = observe(
            self.config,
            self.policy,
            now=datetime(2025, 4, 4, 2, 0, tzinfo=timezone.utc),
        )
        freshness = self.check(report, "freshness")

        self.assertEqual(freshness["status"], "error")
        self.assertEqual(freshness["detail"]["data_through"], "2025-04-03")
        self.assertEqual(freshness["detail"]["expected_through"], "2025-04-02")

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


class Version2RecentPartitionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def pitches(game_pk, game_date, count):
        return [(f"{game_pk}:{number}", game_pk, game_date) for number in range(1, count + 1)]

    def observe_fixture(self, *, start_date, end_date, games, pitches, now=None):
        database = self.root / "v2-contract.duckdb"
        config = dict(
            sample=dict(start_date=start_date, end_date=end_date, chunk_days=3),
            paths=dict(database=str(database), outputs_dir=str(self.root)),
        )
        policy = dict(
            freshness_grace_days=2,
            minimum_row_ratio=0.9,
            maximum_row_ratio=1.5,
            recent_partition_timezone="America/Los_Angeles",
            recent_partition_lookback_dates=14,
            recent_partition_minimum_baseline_dates=1,
            minimum_pitches_per_game_ratio=0.65,
            maximum_pitches_per_game_ratio=1.35,
        )
        with duckdb.connect(str(database)) as connection:
            connection.execute("CREATE SCHEMA metadata; CREATE SCHEMA silver")
            connection.execute("CREATE TABLE metadata.dataset_version AS SELECT 'sample' AS mode")
            connection.execute("""
                CREATE TABLE metadata.pipeline_ranges (
                    season INTEGER,
                    start_date DATE,
                    end_date DATE,
                    chunk_days INTEGER,
                    latest_complete_day BOOLEAN
                )
            """)
            connection.execute(
                "INSERT INTO metadata.pipeline_ranges VALUES (2025, CAST(? AS DATE), CAST(? AS DATE), 3, FALSE)",
                [start_date, end_date],
            )
            connection.execute("""
                CREATE TABLE silver.fact_game_context (
                    game_pk BIGINT,
                    official_date DATE,
                    game_status VARCHAR
                )
            """)
            connection.execute("""
                CREATE TABLE silver.fact_pitch (
                    pitch_id VARCHAR,
                    game_pk BIGINT,
                    game_date DATE
                )
            """)
            connection.executemany(
                "INSERT INTO silver.fact_game_context VALUES (?, CAST(? AS DATE), ?)", games,
            )
            connection.executemany(
                "INSERT INTO silver.fact_pitch VALUES (?, ?, CAST(? AS DATE))", pitches,
            )
        return observe(
            config,
            policy,
            now=now or datetime(2025, 4, 10, tzinfo=timezone.utc),
            checks=[("unique", "SELECT COUNT(*)=COUNT(DISTINCT pitch_id) FROM silver.fact_pitch", True)],
        )

    @staticmethod
    def check(report, name):
        return next(item for item in report["checks"] if item["check"] == name)

    def test_wrong_date_pitches_do_not_count_as_same_date_coverage(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-01", 300)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "error")
        self.assertEqual(report["status"], "error")

    def test_insufficient_baseline_does_not_result_in_overall_pass(self):
        games = [
            (2001, "2025-04-02", "Final"),
            (3001, "2025-04-03", "Final"),
        ]
        pitches = self.pitches(3001, "2025-04-03", 1)
        report = self.observe_fixture(
            start_date="2025-04-02", end_date="2025-04-03", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "unknown_insufficient_baseline")
        self.assertEqual(result["detail"]["eligible_baseline_dates"], 0)
        self.assertEqual(report["status"], "attention")

    def test_invalid_historical_date_is_not_an_eligible_baseline_candidate(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (3001, "2025-04-03", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(3001, "2025-04-03", 300)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-03", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["eligible_baseline_dates"], 1)
        self.assertEqual(result["detail"]["baseline_median_pitches_per_game"], 300.0)

    def test_multiple_completed_status_rows_do_not_duplicate_game_pitches(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Game Over"),
            (2001, "2025-04-02", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["completed_games"], 1)
        self.assertEqual(result["detail"]["pitch_games"], 1)
        self.assertEqual(result["detail"]["pitch_rows"], 300)
        self.assertEqual(result["detail"]["pitches_per_completed_game"], 300.0)
        self.assertEqual(result["detail"]["ratio"], 1.0)

    def test_legitimate_low_volume_game_is_attention_not_integrity_error(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (1002, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Completed Early"),
            (2002, "2025-04-02", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(1002, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 175)
            + self.pitches(2002, "2025-04-02", 425)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "volume_anomaly")
        self.assertEqual(report["status"], "attention")

    def test_high_volume_ratio_is_attention_not_integrity_error(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 500)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "volume_anomaly")
        self.assertGreater(result["detail"]["ratio"], 1.35)

    def test_past_date_with_active_game_is_not_reported_as_healthy(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (2002, "2025-04-02", "In Progress"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
            + self.pitches(2002, "2025-04-02", 50)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "unknown_unsettled_date")
        self.assertEqual(report["status"], "attention")

    def test_missing_same_date_coverage_outranks_unsettled_status(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (2002, "2025-04-02", "In Progress"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2002, "2025-04-02", 50)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["detail"]["completed_games"], 1)
        self.assertEqual(result["detail"]["pitch_games"], 0)
        self.assertEqual(result["detail"]["unsettled_games"], 1)
        self.assertEqual(report["status"], "error")

    def test_latest_past_date_with_only_active_games_requires_attention(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (3001, "2025-04-03", "In Progress"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
            + self.pitches(3001, "2025-04-03", 50)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-03", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention", result)
        self.assertEqual(result["detail"]["assessment"], "unknown_unsettled_date")
        self.assertEqual(report["status"], "attention")

    def test_latest_past_date_with_only_null_status_requires_attention(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (3001, "2025-04-03", None),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
            + self.pitches(3001, "2025-04-03", 50)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-03", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention", result)
        self.assertEqual(result["detail"]["assessment"], "unknown_unsettled_date")
        self.assertEqual(report["status"], "attention")

    def test_latest_postponed_only_date_is_skipped(self):
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-03",
            games=[(1001, "2025-04-01", "Final"),
                   (2001, "2025-04-02", "Final"),
                   (3001, "2025-04-03", "Postponed")],
            pitches=self.pitches(1001, "2025-04-01", 300)
                    + self.pitches(2001, "2025-04-02", 300),
        )
        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["latest_evaluated_date"], "2025-04-02")

    def test_only_unsettled_date_has_unknown_rates_not_bootstrap(self):
        report = self.observe_fixture(
            start_date="2025-04-03", end_date="2025-04-03",
            games=[(3001, "2025-04-03", "In Progress")],
            pitches=self.pitches(3001, "2025-04-03", 50),
        )
        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "unknown_unsettled_date")
        self.assertEqual(result["detail"]["latest_evaluated_date"], "2025-04-03")
        self.assertEqual(result["detail"]["completed_games"], 0)
        self.assertIsNone(result["detail"]["latest_completed_date"])
        self.assertIsNone(result["detail"]["pitches_per_completed_game"])
        self.assertIsNone(result["detail"]["game_coverage_ratio"])
        self.assertEqual(report["status"], "attention")

    def test_postponed_game_does_not_make_date_unsettled(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (2002, "2025-04-02", "Postponed"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["unsettled_games"], 0)

    def test_past_date_with_unknown_game_status_is_not_reported_as_healthy(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (2002, "2025-04-02", None),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
            + self.pitches(2002, "2025-04-02", 50)
        )
        report = self.observe_fixture(
            start_date="2025-04-01", end_date="2025-04-02", games=games, pitches=pitches,
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["detail"]["assessment"], "unknown_unsettled_date")
        self.assertEqual(report["status"], "attention")

    def test_local_date_boundary_excludes_current_los_angeles_date(self):
        games = [
            (1001, "2025-04-01", "Final"),
            (2001, "2025-04-02", "Final"),
            (3001, "2025-04-03", "Final"),
        ]
        pitches = (
            self.pitches(1001, "2025-04-01", 300)
            + self.pitches(2001, "2025-04-02", 300)
            + self.pitches(3001, "2025-04-03", 1)
        )
        report = self.observe_fixture(
            start_date="2025-04-01",
            end_date="2025-04-03",
            games=games,
            pitches=pitches,
            now=datetime(2025, 4, 4, 2, tzinfo=timezone.utc),
        )

        result = self.check(report, "recent_partition_completeness")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["detail"]["latest_completed_date"], "2025-04-02")


if __name__ == "__main__":
    unittest.main()
