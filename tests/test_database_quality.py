from __future__ import annotations

import unittest
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "database" / "mlb_pitch_analytics.duckdb"


class DatabaseQualityTests(unittest.TestCase):
    def test_unknown_exit_velocity_never_becomes_negative_training_label(self):
        unknown, mislabeled, leaked = self.connection.execute("""
            SELECT
                COUNT(*) FILTER (WHERE p.batted_ball_flag = 1 AND p.launch_speed IS NULL),
                COUNT(*) FILTER (WHERE p.batted_ball_flag = 1 AND p.launch_speed IS NULL AND p.hard_hit_flag IS NOT NULL),
                COUNT(*) FILTER (WHERE p.batted_ball_flag = 1 AND p.launch_speed IS NULL AND t.pitch_id IS NOT NULL)
            FROM silver.fact_pitch p LEFT JOIN gold.training_pitch_hard_hit t USING (pitch_id)
        """).fetchone()
        self.assertEqual(mislabeled, 0)
        self.assertEqual(leaked, 0)

    def test_summary_hard_hit_rates_use_measured_denominator(self):
        invalid = self.connection.execute("""
            SELECT COUNT(*) FROM gold.pitcher_pitch_type_summary
            WHERE measured_batted_ball_count > batted_ball_count
               OR ABS(hard_hit_rate - hard_hit_count::DOUBLE / NULLIF(measured_batted_ball_count, 0)) > 1e-12
               OR (measured_batted_ball_count = 0 AND hard_hit_rate IS NOT NULL)
        """).fetchone()[0]
        self.assertEqual(invalid, 0)

    @classmethod
    def setUpClass(cls):
        cls.connection = duckdb.connect(str(DATABASE_PATH), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_expected_layers_exist(self):
        tables = {
            tuple(row)
            for row in self.connection.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema IN ('bronze', 'silver', 'gold')
                """
            ).fetchall()
        }
        self.assertIn(("bronze", "raw_statcast"), tables)
        self.assertIn(("bronze", "raw_game_context"), tables)
        self.assertIn(("silver", "fact_pitch"), tables)
        self.assertIn(("silver", "fact_game_context"), tables)
        self.assertIn(("gold", "pitcher_pitch_type_summary"), tables)
        self.assertIn(("gold", "pitch_model_features"), tables)
        self.assertIn(("gold", "training_pitch_whiff"), tables)
        self.assertIn(("gold", "training_pitch_hard_hit"), tables)

    def test_pitch_id_is_unique(self):
        total, distinct_total = self.connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pitch_id) FROM silver.fact_pitch"
        ).fetchone()
        self.assertEqual(total, distinct_total)

    def test_rate_relationships(self):
        whiffs, swings, chases, out_of_zone, hard_hits, batted_balls = self.connection.execute(
            """
            SELECT
                SUM(whiff_flag),
                SUM(swing_flag),
                SUM(chase_flag),
                SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END),
                SUM(hard_hit_flag),
                SUM(batted_ball_flag)
            FROM silver.fact_pitch
            """
        ).fetchone()
        self.assertLessEqual(whiffs, swings)
        self.assertLessEqual(chases, out_of_zone)
        self.assertLessEqual(hard_hits, batted_balls)

    def test_fact_respects_runtime_config(self):
        outside_season, outside_dates = self.connection.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE NOT EXISTS (
                        SELECT 1 FROM metadata.pipeline_ranges AS configured
                        WHERE fact_pitch.season = configured.season
                    )
                ),
                COUNT(*) FILTER (
                    WHERE NOT EXISTS (
                        SELECT 1 FROM metadata.pipeline_ranges AS configured
                        WHERE fact_pitch.season = configured.season
                          AND fact_pitch.game_date BETWEEN configured.start_date AND configured.end_date
                    )
                )
            FROM silver.fact_pitch AS fact_pitch
            """
        ).fetchone()
        self.assertEqual(outside_season, 0)
        self.assertEqual(outside_dates, 0)

    def test_whiff_training_mart_matches_swing_denominator(self):
        training_rows, swing_rows = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM gold.training_pitch_whiff),
                (SELECT SUM(swing_flag) FROM silver.fact_pitch)
            """
        ).fetchone()
        self.assertEqual(training_rows, swing_rows)

    def test_whiff_training_mart_has_no_same_pitch_outcome_features(self):
        forbidden = {
            "pitch_description",
            "plate_appearance_event",
            "launch_speed",
            "launch_angle",
            "estimated_woba",
            "delta_run_exp",
        }
        columns = {
            row[0]
            for row in self.connection.execute(
                "DESCRIBE gold.training_pitch_whiff"
            ).fetchall()
        }
        self.assertFalse(columns.intersection(forbidden))

    def test_all_statcast_games_join_to_game_context_once(self):
        missing, duplicate_context = self.connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE context.game_pk IS NULL),
                (
                    SELECT COUNT(*) - COUNT(DISTINCT game_pk)
                    FROM silver.fact_game_context
                )
            FROM (SELECT DISTINCT game_pk FROM silver.fact_pitch) AS pitch_games
            LEFT JOIN silver.fact_game_context AS context USING (game_pk)
            """
        ).fetchone()
        self.assertEqual(missing, 0)
        self.assertEqual(duplicate_context, 0)

    def test_weather_and_time_feature_coverage(self):
        coverage = self.connection.execute(
            """
            SELECT
                COUNT(temperature_f)::DOUBLE / COUNT(*),
                COUNT(wind_speed_mph)::DOUBLE / COUNT(*),
                COUNT(local_start_hour)::DOUBLE / COUNT(*),
                COUNT(venue_id)::DOUBLE / COUNT(*)
            FROM gold.training_pitch_whiff
            """
        ).fetchone()
        self.assertGreaterEqual(coverage[0], 0.99)
        self.assertGreaterEqual(coverage[1], 0.99)
        self.assertEqual(coverage[2], 1.0)
        self.assertEqual(coverage[3], 1.0)

    def test_hard_hit_training_mart_matches_batted_ball_denominator(self):
        training_rows, batted_ball_rows = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM gold.training_pitch_hard_hit),
                (SELECT COUNT(*) FROM silver.fact_pitch WHERE batted_ball_flag = 1 AND hard_hit_flag IS NOT NULL)
            """
        ).fetchone()
        self.assertEqual(training_rows, batted_ball_rows)

    def test_hard_hit_training_mart_excludes_contact_outcomes(self):
        forbidden = {
            "launch_speed",
            "launch_angle",
            "bat_speed",
            "swing_length",
            "estimated_woba",
            "delta_run_exp",
        }
        columns = {
            row[0]
            for row in self.connection.execute(
                "DESCRIBE gold.training_pitch_hard_hit"
            ).fetchall()
        }
        self.assertFalse(columns.intersection(forbidden))

    def test_rolling_features_are_constant_within_player_game(self):
        whiff_changes, hard_hit_changes = self.connection.execute(
            """
            SELECT
                (
                    SELECT COUNT(*) FROM (
                        SELECT game_pk, pitcher_id
                        FROM gold.training_pitch_whiff
                        GROUP BY game_pk, pitcher_id
                        HAVING COUNT(DISTINCT pitcher_swings_prior_200) > 1
                            OR COUNT(DISTINCT pitcher_whiff_rate_prior_200_swings) > 1
                            OR COUNT(DISTINCT pitcher_swings_prior_14d) > 1
                            OR COUNT(DISTINCT pitcher_whiff_rate_prior_14d) > 1
                    )
                ),
                (
                    SELECT COUNT(*) FROM (
                        SELECT game_pk, batter_id
                        FROM gold.training_pitch_hard_hit
                        GROUP BY game_pk, batter_id
                        HAVING COUNT(DISTINCT batter_batted_balls_prior_50) > 1
                            OR COUNT(DISTINCT batter_hard_hit_rate_prior_50_batted_balls) > 1
                            OR COUNT(DISTINCT batter_batted_balls_prior_14d) > 1
                            OR COUNT(DISTINCT batter_hard_hit_rate_prior_14d) > 1
                    )
                )
            """
        ).fetchone()
        self.assertEqual(whiff_changes, 0)
        self.assertEqual(hard_hit_changes, 0)

    def test_rolling_event_windows_are_bounded(self):
        invalid_whiff, invalid_hard_hit = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM gold.training_pitch_whiff
                 WHERE pitcher_swings_prior_200 NOT BETWEEN 0 AND 200
                    OR batter_swings_prior_50 NOT BETWEEN 0 AND 50),
                (SELECT COUNT(*) FROM gold.training_pitch_hard_hit
                 WHERE pitcher_batted_balls_prior_200 NOT BETWEEN 0 AND 200
                    OR batter_batted_balls_prior_50 NOT BETWEEN 0 AND 50)
            """
        ).fetchone()
        self.assertEqual(invalid_whiff, 0)
        self.assertEqual(invalid_hard_hit, 0)

    def test_first_observed_game_has_no_player_history(self):
        invalid = self.connection.execute(
            """
            WITH
            whiff_first AS (
                SELECT pitcher_id, MIN(game_datetime_utc) AS first_time
                FROM gold.training_pitch_whiff GROUP BY pitcher_id
            ),
            hard_hit_first AS (
                SELECT batter_id, MIN(game_datetime_utc) AS first_time
                FROM gold.training_pitch_hard_hit GROUP BY batter_id
            )
            SELECT
                (SELECT COUNT(*) FROM gold.training_pitch_whiff AS training
                 JOIN whiff_first AS first USING (pitcher_id)
                 WHERE training.game_datetime_utc = first.first_time
                   AND training.pitcher_swings_prior_200 <> 0)
                +
                (SELECT COUNT(*) FROM gold.training_pitch_hard_hit AS training
                 JOIN hard_hit_first AS first USING (batter_id)
                 WHERE training.game_datetime_utc = first.first_time
                   AND training.batter_batted_balls_prior_50 <> 0)
            """
        ).fetchone()[0]
        self.assertEqual(invalid, 0)

    def test_pitch_type_and_matchup_windows_are_bounded(self):
        invalid_whiff, invalid_hard_hit = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM gold.training_pitch_whiff
                 WHERE pitcher_pitch_type_swings_prior_100 NOT BETWEEN 0 AND 100
                    OR batter_pitch_type_swings_prior_30 NOT BETWEEN 0 AND 30
                    OR matchup_swings_prior_30 NOT BETWEEN 0 AND 30),
                (SELECT COUNT(*) FROM gold.training_pitch_hard_hit
                 WHERE pitcher_pitch_type_batted_balls_prior_100 NOT BETWEEN 0 AND 100
                    OR batter_pitch_type_batted_balls_prior_30 NOT BETWEEN 0 AND 30
                    OR matchup_batted_balls_prior_20 NOT BETWEEN 0 AND 20)
            """
        ).fetchone()
        self.assertEqual(invalid_whiff, 0)
        self.assertEqual(invalid_hard_hit, 0)

    def test_pitch_type_and_matchup_features_are_constant_within_game(self):
        invalid = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM (
                    SELECT game_pk, pitcher_id, pitch_type
                    FROM gold.training_pitch_whiff
                    GROUP BY game_pk, pitcher_id, pitch_type
                    HAVING COUNT(DISTINCT pitcher_pitch_type_swings_prior_100) > 1
                        OR COUNT(DISTINCT pitcher_pitch_type_whiff_rate_prior_100_swings) > 1
                ))
                +
                (SELECT COUNT(*) FROM (
                    SELECT game_pk, pitcher_id, batter_id
                    FROM gold.training_pitch_hard_hit
                    GROUP BY game_pk, pitcher_id, batter_id
                    HAVING COUNT(DISTINCT matchup_batted_balls_prior_20) > 1
                        OR COUNT(DISTINCT matchup_hard_hit_rate_prior_20_batted_balls) > 1
                ))
            """
        ).fetchone()[0]
        self.assertEqual(invalid, 0)


if __name__ == "__main__":
    unittest.main()
