from __future__ import annotations

import unittest

import duckdb

from src.build_dashboard_snapshot import (
    PITCH_SUMMARY_SQL,
    compact_pitch_summary_rows,
    reviewed_rows,
)


class DashboardSnapshotCompactionTests(unittest.TestCase):
    def setUp(self):
        self.connection = duckdb.connect(":memory:")
        self.connection.execute(
            """
            CREATE TABLE fixture_pitch (
                season INTEGER,
                pitcher_id BIGINT,
                pitcher_name VARCHAR,
                pitcher_team VARCHAR,
                pitcher_throws VARCHAR,
                batter_stand VARCHAR,
                pitch_type VARCHAR,
                pitch_name VARCHAR,
                pitch_family VARCHAR,
                count_state VARCHAR,
                in_zone_flag INTEGER,
                swing_flag INTEGER,
                whiff_flag INTEGER,
                chase_flag INTEGER,
                batted_ball_flag INTEGER,
                hard_hit_flag INTEGER,
                release_speed DOUBLE,
                game_date DATE
            )
            """
        )
        self.connection.execute("CREATE SCHEMA silver")
        self.connection.execute("CREATE VIEW silver.fact_pitch AS SELECT * FROM fixture_pitch")
        self.connection.executemany(
            "INSERT INTO fixture_pitch VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (2026, 101, "One, Pitcher", "LAD", "R", "L", "FF", "4-Seam Fastball", "Fastball", "Even", 1, 1, 0, 0, 0, None, 95.0, "2026-04-01"),
                (2026, 101, "One, Pitcher", "LAD", "R", "L", "FF", "4-Seam Fastball", "Fastball", "Even", 0, 0, 0, 0, 0, None, None, "2026-04-02"),
                (2026, 202, "Two, Pitcher", "SEA", "L", "R", "SL", "Slider", "Breaking", "Ahead", 1, 1, 1, 0, 0, None, 85.0, "2026-04-02"),
                (2026, 303, "Three, Pitcher", "BOS", "R", "R", "KC", None, "Breaking", "Behind", 0, 0, 0, 0, 0, None, 80.0, "2026-04-03"),
            ],
        )

    def tearDown(self):
        self.connection.close()

    def test_summary_omits_redundant_pitch_code_and_sparse_zero_velocity_gaps(self):
        rows = compact_pitch_summary_rows(reviewed_rows(self.connection, PITCH_SUMMARY_SQL))
        by_pitcher = {row["pitcher_id"]: row for row in rows}

        missing_velocity = by_pitcher[101]
        self.assertNotIn("pitch_type", missing_velocity)
        self.assertNotIn("velocity_count", missing_velocity)
        self.assertEqual(missing_velocity["pitch_name"], "4-Seam Fastball")
        self.assertEqual(missing_velocity["pitch_count"], 2)
        self.assertEqual(missing_velocity["missing_velocity_count"], 1)
        self.assertEqual(missing_velocity["velocity_total"], 95.0)

        complete_velocity = by_pitcher[202]
        self.assertNotIn("missing_velocity_count", complete_velocity)
        self.assertEqual(complete_velocity["pitch_count"], 1)
        self.assertEqual(complete_velocity["velocity_total"], 85.0)

        missing_name = by_pitcher[303]
        self.assertEqual(missing_name["pitch_name"], "KC")
        self.assertNotIn("pitch_type", missing_name)


if __name__ == "__main__":
    unittest.main()
