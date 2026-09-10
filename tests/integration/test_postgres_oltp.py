from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from src.oltp_store import (
    apply_migrations,
    get_or_create_forecast_request,
    record_forecast_result,
)


try:
    import psycopg
except ImportError:
    psycopg = None


DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@unittest.skipUnless(psycopg is not None and DATABASE_URL, "PostgreSQL integration database is not configured")
class PostgreSqlOltpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = psycopg.connect(DATABASE_URL, autocommit=True)
        apply_migrations(cls.connection)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_migrations_are_idempotent_and_indexes_exist(self):
        self.assertEqual(apply_migrations(self.connection), [])
        rows = self.connection.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'operational'
            """
        ).fetchall()
        indexes = {row[0] for row in rows}
        self.assertTrue(
            {
                "source_partitions_date_idx",
                "forecast_requests_pitcher_game_idx",
                "forecast_requests_pending_idx",
            }.issubset(indexes)
        )

    def test_concurrent_requests_share_one_idempotent_row(self):
        key = f"integration:{uuid4()}"

        def create_request(_):
            connection = psycopg.connect(DATABASE_URL, autocommit=True)
            try:
                return get_or_create_forecast_request(
                    connection,
                    idempotency_key=key,
                    game_pk=900001,
                    pitcher_id=600001,
                    model_version="integration-v1",
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=8) as executor:
            request_ids = list(executor.map(create_request, range(16)))
        self.assertEqual(len(set(request_ids)), 1)
        count = self.connection.execute(
            "SELECT COUNT(*) FROM operational.forecast_requests WHERE idempotency_key = %s",
            (key,),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.connection.execute(
            "DELETE FROM operational.forecast_requests WHERE idempotency_key = %s",
            (key,),
        )

    def test_constraint_failure_rolls_back_request_status(self):
        key = f"rollback:{uuid4()}"
        request_id = get_or_create_forecast_request(
            self.connection,
            idempotency_key=key,
            game_pk=900002,
            pitcher_id=600002,
            model_version="integration-v1",
        )
        with self.assertRaises(Exception):
            record_forecast_result(
                self.connection,
                request_id=request_id,
                predicted_strikeouts=5.0,
                lower_bound=8,
                upper_bound=3,
            )
        status = self.connection.execute(
            "SELECT status FROM operational.forecast_requests WHERE request_id = %s",
            (request_id,),
        ).fetchone()[0]
        result_count = self.connection.execute(
            "SELECT COUNT(*) FROM operational.forecast_results WHERE request_id = %s",
            (request_id,),
        ).fetchone()[0]
        self.assertEqual(status, "pending")
        self.assertEqual(result_count, 0)
        self.connection.execute(
            "DELETE FROM operational.forecast_requests WHERE request_id = %s",
            (request_id,),
        )


if __name__ == "__main__":
    unittest.main()

