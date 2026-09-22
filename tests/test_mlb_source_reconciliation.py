from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

import duckdb

from src.reconcile_mlb_source import reconcile_date


class MlbSourceReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE SCHEMA silver")
        self.connection.execute("""
            CREATE TABLE silver.fact_game_context (
                game_pk BIGINT,
                official_date DATE,
                game_status VARCHAR
            )
        """)
        self.connection.execute("""
            CREATE TABLE silver.fact_pitch (
                game_pk BIGINT,
                game_date DATE,
                at_bat_number INTEGER
            )
        """)
        self.day = date(2025, 4, 2)
        self.now = datetime(2025, 4, 3, 12, tzinfo=timezone.utc)

    @staticmethod
    def schedule_payload(*, final=True):
        status = (
            {"abstractGameState": "Final", "detailedState": "Final"}
            if final
            else {"abstractGameState": "Preview", "detailedState": "Scheduled"}
        )
        return {
            "dates": [{
                "date": "2025-04-02",
                "games": [{
                    "gamePk": 2001,
                    "officialDate": "2025-04-02",
                    "status": status,
                }],
            }]
        }

    @staticmethod
    def feed_payload():
        return {
            "gameData": {
                "game": {"pk": 2001},
                "datetime": {"officialDate": "2025-04-02"},
            },
            "liveData": {
                "plays": {
                    "allPlays": [
                        {
                            "about": {"atBatIndex": 0},
                            "playEvents": [
                                {"isPitch": True},
                                {"isPitch": False, "type": "action"},
                                {"isPitch": True},
                            ],
                        },
                        {
                            "about": {"atBatIndex": 1},
                            "playEvents": [{"isPitch": True}],
                        },
                    ]
                }
            },
        }

    def fetcher(self, url):
        if "/schedule?" in url:
            return self.schedule_payload()
        if "/game/2001/feed/live" in url:
            return self.feed_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    def seed_complete_local_game(self):
        self.connection.execute(
            "INSERT INTO silver.fact_game_context VALUES (2001, DATE '2025-04-02', 'Final')"
        )
        self.connection.execute("""
            INSERT INTO silver.fact_pitch VALUES
                (2001, DATE '2025-04-02', 1),
                (2001, DATE '2025-04-02', 1),
                (2001, DATE '2025-04-02', 2)
        """)

    def reconcile(self, fetcher=None):
        return reconcile_date(
            self.connection,
            self.day,
            fetch_json=fetcher or self.fetcher,
            now=self.now,
        )

    def test_matching_schedule_and_plate_appearance_counts_pass(self):
        self.seed_complete_local_game()

        result = self.reconcile()

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["assessment"], "source_reconciled")
        self.assertEqual(result["metrics"]["official_final_games"], 1)
        self.assertEqual(result["metrics"]["play_by_play_games_checked"], 1)
        self.assertEqual(result["metrics"]["official_pitch_events"], 3)
        self.assertEqual(result["metrics"]["local_pitch_rows"], 3)
        self.assertEqual(result["mismatches"], {})

    def test_game_missing_from_both_local_tables_is_detected_from_live_schedule(self):
        result = self.reconcile()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["assessment"], "source_mismatch")
        self.assertEqual(result["mismatches"]["missing_context_games"], [2001])
        self.assertEqual(result["mismatches"]["missing_pitch_games"], [2001])
        self.assertEqual(result["metrics"]["play_by_play_games_checked"], 0)

    def test_equal_daily_total_cannot_hide_plate_appearance_mismatches(self):
        self.connection.execute(
            "INSERT INTO silver.fact_game_context VALUES (2001, DATE '2025-04-02', 'Final')"
        )
        self.connection.execute("""
            INSERT INTO silver.fact_pitch VALUES
                (2001, DATE '2025-04-02', 1),
                (2001, DATE '2025-04-02', 2),
                (2001, DATE '2025-04-02', 2)
        """)

        result = self.reconcile()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["metrics"]["official_pitch_events"], 3)
        self.assertEqual(result["metrics"]["local_pitch_rows"], 3)
        self.assertEqual(
            result["mismatches"]["plate_appearance_pitch_counts"],
            [
                {"game_pk": 2001, "at_bat_number": 1, "official": 2, "local": 1},
                {"game_pk": 2001, "at_bat_number": 2, "official": 1, "local": 2},
            ],
        )

    def test_wrong_date_pitches_are_reported_not_counted_as_coverage(self):
        self.connection.execute(
            "INSERT INTO silver.fact_game_context VALUES (2001, DATE '2025-04-02', 'Final')"
        )
        self.connection.execute("""
            INSERT INTO silver.fact_pitch VALUES
                (2001, DATE '2025-04-01', 1),
                (2001, DATE '2025-04-01', 1),
                (2001, DATE '2025-04-01', 2)
        """)

        result = self.reconcile()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["mismatches"]["missing_pitch_games"], [2001])
        self.assertEqual(
            result["mismatches"]["pitch_games_on_other_dates"],
            [{"game_pk": 2001, "dates": ["2025-04-01"]}],
        )

    def test_date_without_final_games_is_unknown_not_pass(self):
        result = self.reconcile(
            fetcher=lambda url: self.schedule_payload(final=False)
        )

        self.assertEqual(result["status"], "attention")
        self.assertEqual(result["assessment"], "unknown_no_final_games")


if __name__ == "__main__":
    unittest.main()
