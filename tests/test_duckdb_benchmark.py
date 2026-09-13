from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

import duckdb

from benchmarks.run_duckdb_benchmark import DEFAULT_SQL_DIR, percentile, run_benchmark


ROOT = Path(__file__).resolve().parents[1]
COMMITTED_RESULT = ROOT / "benchmarks" / "results" / "latest.json"
SQL_GUIDE = ROOT / "docs" / "SQL_PERFORMANCE.md"


class DuckDBBenchmarkTests(unittest.TestCase):
    def test_percentile_interpolates_and_validates_input(self):
        self.assertEqual(percentile([10.0, 20.0, 30.0], 0.5), 20.0)
        self.assertAlmostEqual(percentile([10.0, 20.0], 0.95), 19.5)
        with self.assertRaises(ValueError):
            percentile([], 0.95)

    def test_runner_preserves_results_across_thread_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fixture.duckdb"
            connection = duckdb.connect(str(database_path))
            connection.execute("CREATE SCHEMA silver")
            connection.execute(
                """
                CREATE TABLE silver.fact_pitch (
                    game_pk BIGINT,
                    game_date DATE,
                    pitcher_id BIGINT,
                    pitch_type VARCHAR,
                    swing_flag INTEGER,
                    whiff_flag INTEGER,
                    release_speed DOUBLE
                )
                """
            )
            connection.execute(
                """
                INSERT INTO silver.fact_pitch VALUES
                    (1, DATE '2026-08-01', 10, 'FF', 1, 0, 95.0),
                    (1, DATE '2026-08-01', 10, 'SL', 1, 1, 86.0),
                    (2, DATE '2026-09-01', 11, 'FF', 0, 0, 94.0),
                    (2, DATE '2026-09-01', 11, 'CH', 1, 1, 88.0)
                """
            )
            connection.execute(
                """
                CREATE TABLE silver.fact_game_context (
                    game_pk BIGINT,
                    venue_id BIGINT,
                    day_night VARCHAR
                )
                """
            )
            connection.execute(
                "INSERT INTO silver.fact_game_context VALUES (1, 100, 'day'), (2, 200, 'night')"
            )
            connection.close()

            report, plans = run_benchmark(
                database_path=database_path,
                sql_dir=DEFAULT_SQL_DIR,
                thread_counts=(1, 2),
                repetitions=2,
                warmups=0,
                capture_explain=False,
            )

            self.assertEqual(report["dataset"]["fact_pitch_rows"], 4)
            self.assertEqual(report["dataset"]["recent_filter_input_rows"], 2)
            self.assertEqual(report["dataset"]["recent_filter_selectivity_pct"], 50.0)
            self.assertEqual(len(report["results"]), 8)
            self.assertEqual(plans, {})
            for query_name in {row["query"] for row in report["results"]}:
                query_rows = [row for row in report["results"] if row["query"] == query_name]
                self.assertEqual(len({row["result_rows"] for row in query_rows}), 1)
                self.assertEqual(len({row["result_sha256"] for row in query_rows}), 1)

    def test_committed_evidence_covers_real_data_and_matches_documented_speedups(self):
        report = json.loads(COMMITTED_RESULT.read_text(encoding="utf-8"))
        guide = SQL_GUIDE.read_text(encoding="utf-8")

        self.assertGreater(report["dataset"]["fact_pitch_rows"], 1_000_000)
        self.assertEqual(report["environment"]["thread_counts"], [1, 2, 4, 8])
        self.assertEqual(
            {row["query"] for row in report["results"]},
            {
                "full_scan_aggregate",
                "recent_filter_aggregate",
                "game_context_join",
                "partitioned_window",
            },
        )
        for query_name in {row["query"] for row in report["results"]}:
            query_rows = [row for row in report["results"] if row["query"] == query_name]
            self.assertEqual(len(query_rows), 4)
            self.assertEqual(len({row["result_sha256"] for row in query_rows}), 1)
            best = max(row["speedup_vs_1_thread"] for row in query_rows)
            self.assertIn(f"{best:.3f}x", guide)

        for relative_path in report["explain_analyze_files"].values():
            self.assertTrue((ROOT / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
