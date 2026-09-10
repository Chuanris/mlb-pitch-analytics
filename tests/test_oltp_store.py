from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src.oltp_store import (
    database_url_from_env,
    finish_ingestion_run,
    get_or_create_forecast_request,
    migration_files,
    normalize_sha256,
    record_forecast_result,
    split_sql_statements,
    start_ingestion_run,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OltpStoreUnitTests(unittest.TestCase):
    def test_migration_contains_relational_and_performance_contracts(self):
        files = migration_files()
        self.assertEqual([path.name for path in files], ["001_operational_store.sql"])
        sql = files[0].read_text(encoding="utf-8").lower()
        for table in (
            "ingestion_runs",
            "source_partitions",
            "forecast_requests",
            "forecast_results",
            "user_watchlists",
        ):
            self.assertIn(f"operational.{table}", sql)
        for contract in (
            "primary key",
            "references operational.ingestion_runs",
            "references operational.forecast_requests",
            "check (",
            "unique",
            "create index if not exists",
            "where status = 'pending'",
            "include (source_name, row_count, content_sha256)",
        ):
            self.assertIn(contract, sql)
        self.assertGreaterEqual(len(list(split_sql_statements(sql))), 10)

    def test_normalize_sha256_accepts_hex_and_rejects_bad_values(self):
        self.assertEqual(normalize_sha256("A" * 64), "a" * 64)
        for value in ("", "a" * 63, "g" * 64, "a" * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_sha256(value)

    def test_database_url_is_required_without_exposing_a_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "MLB_OLTP_DATABASE_URL") as error:
                database_url_from_env()
        self.assertNotIn("password", str(error.exception).lower())

    def test_invalid_values_fail_before_database_access(self):
        with self.assertRaises(ValueError):
            start_ingestion_run(None, "sample", date(2026, 4, 2), date(2026, 4, 1))
        with self.assertRaises(ValueError):
            finish_ingestion_run(None, uuid4(), "running", 0)
        with self.assertRaises(ValueError):
            get_or_create_forecast_request(
                None,
                idempotency_key="",
                game_pk=1,
                pitcher_id=1,
                model_version="v1",
            )
        with self.assertRaises(ValueError):
            record_forecast_result(
                None,
                request_id=uuid4(),
                predicted_strikeouts=5.0,
                lower_bound=3,
                upper_bound=8,
                outcome_status="unknown",
            )


if __name__ == "__main__":
    unittest.main()
