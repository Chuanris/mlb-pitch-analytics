from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import unittest

import duckdb

from src.build_mlb_source_audit import build_audit


class MlbSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE SCHEMA bronze")
        self.connection.execute("CREATE SCHEMA silver")
        self.connection.execute("""
            CREATE TABLE bronze.raw_statcast (
                game_pk BIGINT,
                game_date DATE,
                game_type VARCHAR,
                description VARCHAR,
                pitch_type VARCHAR
            )
        """)
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
        self.start = date(2025, 4, 2)
        self.end = date(2025, 4, 3)
        self.now = datetime(2025, 4, 4, 12, tzinfo=timezone.utc)

        self.connection.execute("""
            INSERT INTO silver.fact_game_context VALUES
                (2001, DATE '2025-04-02', 'Final'),
                (2002, DATE '2025-04-03', 'Final')
        """)
        self.connection.execute("""
            INSERT INTO bronze.raw_statcast VALUES
                (2001, DATE '2025-04-02', 'R', 'called_strike', 'FF'),
                (2001, DATE '2025-04-02', 'R', 'foul', 'FF'),
                (2001, DATE '2025-04-02', 'R', 'ball', 'SL'),
                (2001, DATE '2025-04-02', 'R', 'automatic_ball', NULL),
                (2002, DATE '2025-04-03', 'R', 'called_strike', 'FF'),
                (2002, DATE '2025-04-03', 'R', 'foul', 'FF'),
                (2002, DATE '2025-04-03', 'R', 'ball', NULL)
        """)
        self.connection.execute("""
            INSERT INTO silver.fact_pitch VALUES
                (2001, DATE '2025-04-02', 1),
                (2001, DATE '2025-04-02', 1),
                (2001, DATE '2025-04-02', 2),
                (2002, DATE '2025-04-03', 1),
                (2002, DATE '2025-04-03', 1)
        """)

    @staticmethod
    def fetcher(url):
        if "/schedule?" in url:
            day = "2025-04-03" if "2025-04-03" in url else "2025-04-02"
            game_pk = 2002 if day == "2025-04-03" else 2001
            return {
                "dates": [{
                    "date": day,
                    "games": [{
                        "gamePk": game_pk,
                        "officialDate": day,
                        "status": {
                            "abstractGameState": "Final",
                            "detailedState": "Final",
                        },
                    }],
                }],
            }
        game_pk = 2002 if "/game/2002/" in url else 2001
        return {
            "gameData": {"game": {"pk": game_pk}},
            "liveData": {"plays": {"allPlays": [
                {
                    "about": {"atBatIndex": 0},
                    "playEvents": [{"isPitch": True}, {"isPitch": True}],
                },
                {
                    "about": {"atBatIndex": 1},
                    "playEvents": [{"isPitch": True}],
                },
            ]}},
        }

    def test_range_summary_preserves_a_single_date_mismatch(self):
        audit = build_audit(
            self.connection,
            self.start,
            self.end,
            fetch_json=self.fetcher,
            now=self.now,
        )

        self.assertEqual(audit["status"], "error")
        self.assertEqual(audit["assessment"], "audit_has_errors")
        self.assertEqual(audit["summary"]["status_counts"], {
            "pass": 1,
            "attention": 0,
            "error": 1,
        })
        self.assertEqual(audit["summary"]["official_final_games"], 2)
        self.assertEqual(audit["summary"]["official_pitch_events"], 6)
        self.assertEqual(audit["summary"]["raw_pitch_proxy_rows"], 6)
        self.assertEqual(audit["summary"]["silver_pitch_rows"], 5)
        self.assertEqual(audit["summary"]["raw_minus_official_pitch_events"], 0)
        self.assertEqual(audit["summary"]["silver_minus_official_pitch_events"], -1)
        self.assertEqual(audit["summary"]["raw_matching_dates"], 2)
        self.assertEqual(audit["summary"]["source_reconciled_dates"], 1)

        failing_day = audit["dates"][1]
        self.assertEqual(failing_day["official_date"], "2025-04-03")
        self.assertEqual(failing_day["status"], "error")
        self.assertEqual(
            failing_day["mismatches"]["missing_plate_appearances"],
            [{"game_pk": 2002, "at_bat_number": 2}],
        )
        self.assertEqual(failing_day["local_layers"]["raw_null_pitch_type_rows"], 1)

    def test_range_and_summary_contract_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "start_date must not be after end_date"):
            build_audit(
                self.connection,
                self.end,
                self.start,
                fetch_json=self.fetcher,
                now=self.now,
            )

        audit = build_audit(
            self.connection,
            self.start,
            self.start,
            fetch_json=self.fetcher,
            now=self.now,
        )
        self.assertEqual(audit["schema_version"], 1)
        self.assertEqual(audit["scope"]["start_date"], "2025-04-02")
        self.assertEqual(audit["scope"]["end_date"], "2025-04-02")
        self.assertEqual(audit["summary"]["dates_checked"], 1)
        self.assertIn("does not prove", audit["claim"]["limits"])
        self.assertIn("description", audit["method"]["raw_pitch_proxy"])
        self.assertEqual(audit["local_snapshot"], {
            "bronze.raw_statcast": {
                "min_game_date": "2025-04-02",
                "max_game_date": "2025-04-03",
                "rows": 7,
            },
            "silver.fact_pitch": {
                "min_game_date": "2025-04-02",
                "max_game_date": "2025-04-03",
                "rows": 5,
            },
        })

    def test_raw_proxy_mismatch_prevents_an_overall_pass(self):
        self.connection.execute("""
            DELETE FROM bronze.raw_statcast
            WHERE game_pk = 2001 AND description = 'ball'
        """)

        audit = build_audit(
            self.connection,
            self.start,
            self.start,
            fetch_json=self.fetcher,
            now=self.now,
        )

        self.assertEqual(audit["status"], "error")
        self.assertEqual(audit["summary"]["raw_mismatch_dates"], 1)
        self.assertEqual(audit["dates"][0]["status"], "error")
        self.assertEqual(
            audit["dates"][0]["assessment"],
            "raw_pitch_proxy_mismatch",
        )
        self.assertEqual(
            audit["dates"][0]["source_reconciliation"],
            {"status": "pass", "assessment": "source_reconciled"},
        )


class VersionedMlbSourceAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).resolve().parents[1]
            / "evidence"
            / "mlb-source-audit"
            / "2026-09-09_2026-09-20.json"
        )
        cls.audit = json.loads(path.read_text(encoding="utf-8"))

    def test_versioned_manifest_reconciles_its_daily_evidence(self):
        audit = self.audit
        rows = audit["dates"]
        summary = audit["summary"]

        self.assertEqual(audit["schema_version"], 1)
        self.assertEqual(audit["status"], "error")
        self.assertEqual(audit["assessment"], "audit_has_errors")
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["official_date"], "2026-09-09")
        self.assertEqual(rows[-1]["official_date"], "2026-09-20")
        self.assertEqual(
            summary["status_counts"],
            {
                name: Counter(row["status"] for row in rows)[name]
                for name in ("pass", "attention", "error")
            },
        )
        for metric in (
            "official_final_games",
            "official_plate_appearances",
            "official_pitch_plate_appearances",
            "official_pitch_events",
        ):
            self.assertEqual(
                summary[metric],
                sum(row["metrics"][metric] for row in rows),
            )
        self.assertEqual(
            summary["raw_pitch_proxy_rows"],
            sum(row["local_layers"]["raw_pitch_proxy_rows"] for row in rows),
        )
        self.assertEqual(
            summary["silver_pitch_rows"],
            sum(row["local_layers"]["silver_pitch_rows"] for row in rows),
        )

    def test_versioned_manifest_preserves_claim_boundaries_and_hashes(self):
        audit = self.audit
        summary = audit["summary"]
        self.assertEqual(summary["official_final_games"], 159)
        self.assertEqual(summary["official_plate_appearances"], 12_110)
        self.assertEqual(summary["official_pitch_plate_appearances"], 12_087)
        self.assertEqual(summary["official_pitch_events"], 46_843)
        self.assertEqual(summary["raw_pitch_proxy_rows"], 46_843)
        self.assertEqual(summary["silver_pitch_rows"], 46_821)
        self.assertEqual(summary["raw_matching_dates"], 12)
        self.assertEqual(summary["source_reconciled_dates"], 7)
        self.assertIn("does not prove", audit["claim"]["limits"])
        self.assertEqual(audit["local_snapshot"], {
            "bronze.raw_statcast": {
                "min_game_date": "2025-03-18",
                "max_game_date": "2026-09-22",
                "rows": 1_408_305,
            },
            "silver.fact_pitch": {
                "min_game_date": "2025-03-18",
                "max_game_date": "2026-09-22",
                "rows": 1_403_065,
            },
        })

        digest = re.compile(r"[0-9a-f]{64}")
        for row in audit["dates"]:
            self.assertIsNotNone(
                digest.fullmatch(row["sources"]["schedule_sha256"])
            )
            feed_hashes = row["sources"]["game_feed_sha256"]
            self.assertEqual(
                len(feed_hashes),
                row["metrics"]["official_final_games"],
            )
            self.assertTrue(all(digest.fullmatch(value) for value in feed_hashes.values()))


if __name__ == "__main__":
    unittest.main()
