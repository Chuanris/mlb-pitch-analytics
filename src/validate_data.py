from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb

from src.common import load_config, project_path


CHECKS = [
    ("fact_has_rows", "SELECT COUNT(*) > 0 FROM silver.fact_pitch", True),
    (
        "pitch_id_is_unique",
        "SELECT COUNT(*) = COUNT(DISTINCT pitch_id) FROM silver.fact_pitch",
        True,
    ),
    (
        "required_ids_not_null",
        "SELECT COUNT(*) = 0 FROM silver.fact_pitch WHERE game_pk IS NULL OR pitcher_id IS NULL OR batter_id IS NULL",
        True,
    ),
    (
        "count_values_valid",
        "SELECT COUNT(*) = 0 FROM silver.fact_pitch WHERE balls NOT BETWEEN 0 AND 3 OR strikes NOT BETWEEN 0 AND 2",
        True,
    ),
    (
        "whiffs_do_not_exceed_swings",
        "SELECT SUM(whiff_flag) <= SUM(swing_flag) FROM silver.fact_pitch",
        True,
    ),
    (
        "chases_do_not_exceed_out_of_zone_pitches",
        "SELECT SUM(chase_flag) <= SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END) FROM silver.fact_pitch",
        True,
    ),
    (
        "hard_hits_do_not_exceed_batted_balls",
        "SELECT SUM(hard_hit_flag) <= SUM(batted_ball_flag) FROM silver.fact_pitch",
        True,
    ),
    (
        "velocity_range_reasonable",
        "SELECT COUNT(*) = 0 FROM silver.fact_pitch WHERE release_speed IS NOT NULL AND release_speed NOT BETWEEN 20 AND 110",
        True,
    ),
    (
        "configured_seasons_applied",
        """
        SELECT COUNT(*) = 0
        FROM silver.fact_pitch AS pitch
        WHERE NOT EXISTS (
            SELECT 1 FROM metadata.pipeline_ranges AS configured
            WHERE pitch.season = configured.season
        )
        """,
        True,
    ),
    (
        "configured_date_range_applied",
        """
        SELECT COUNT(*) = 0
        FROM silver.fact_pitch AS pitch
        WHERE NOT EXISTS (
            SELECT 1 FROM metadata.pipeline_ranges AS configured
            WHERE pitch.season = configured.season
              AND pitch.game_date BETWEEN configured.start_date AND configured.end_date
        )
        """,
        True,
    ),
    (
        "whiff_training_rows_match_swings",
        """
        SELECT
            (SELECT COUNT(*) FROM gold.training_pitch_whiff)
            =
            (SELECT SUM(swing_flag) FROM silver.fact_pitch)
        """,
        True,
    ),
    (
        "whiff_training_target_is_binary",
        "SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff WHERE target_whiff NOT IN (0, 1) OR target_whiff IS NULL",
        True,
    ),
    (
        "whiff_sequence_uses_prior_pitch_only",
        """
        SELECT COUNT(*) = 0
        FROM gold.training_pitch_whiff
        WHERE previous_pitch_number IS NOT NULL
          AND previous_pitch_number >= pitch_number
        """,
        True,
    ),
    (
        "whiff_training_excludes_outcome_columns",
        """
        SELECT COUNT(*) = 0
        FROM information_schema.columns
        WHERE table_schema = 'gold'
          AND table_name = 'training_pitch_whiff'
          AND column_name IN (
              'pitch_description', 'plate_appearance_event', 'launch_speed',
              'launch_angle', 'bat_speed', 'swing_length', 'miss_distance',
              'estimated_woba', 'delta_run_exp', 'post_home_score',
              'post_away_score', 'pitcher_days_until_next_game'
          )
        """,
        True,
    ),
    (
        "game_context_game_pk_is_unique",
        "SELECT COUNT(*) = COUNT(DISTINCT game_pk) FROM silver.fact_game_context",
        True,
    ),
    (
        "statcast_games_have_context",
        """
        SELECT COUNT(*) = 0
        FROM (SELECT DISTINCT game_pk FROM silver.fact_pitch) AS pitch_games
        LEFT JOIN silver.fact_game_context AS context USING (game_pk)
        WHERE context.game_pk IS NULL
        """,
        True,
    ),
    (
        "game_context_dates_match_statcast",
        """
        SELECT COUNT(*) = 0
        FROM silver.fact_pitch AS pitch
        JOIN silver.fact_game_context AS context USING (game_pk)
        WHERE pitch.game_date <> context.official_date
        """,
        True,
    ),
    (
        "model_weather_coverage_at_least_99_percent",
        """
        SELECT
            COUNT(temperature_f)::DOUBLE / COUNT(*) >= 0.99
            AND COUNT(wind_speed_mph)::DOUBLE / COUNT(*) >= 0.99
            AND COUNT(venue_id)::DOUBLE / COUNT(*) = 1.0
        FROM gold.training_pitch_whiff
        """,
        True,
    ),
    (
        "hard_hit_training_rows_match_batted_balls",
        """
        SELECT
            (SELECT COUNT(*) FROM gold.training_pitch_hard_hit)
            =
            (SELECT SUM(batted_ball_flag) FROM silver.fact_pitch)
        """,
        True,
    ),
    (
        "hard_hit_training_target_is_binary",
        """
        SELECT COUNT(*) = 0
        FROM gold.training_pitch_hard_hit
        WHERE target_hard_hit NOT IN (0, 1) OR target_hard_hit IS NULL
        """,
        True,
    ),
    (
        "hard_hit_training_excludes_contact_outcomes",
        """
        SELECT COUNT(*) = 0
        FROM information_schema.columns
        WHERE table_schema = 'gold'
          AND table_name = 'training_pitch_hard_hit'
          AND column_name IN (
              'launch_speed', 'launch_angle', 'bat_speed', 'swing_length',
              'miss_distance', 'estimated_woba', 'delta_run_exp',
              'pitch_description', 'plate_appearance_event'
          )
        """,
        True,
    ),
    (
        "whiff_rolling_features_are_pregame_constant",
        """
        SELECT COUNT(*) = 0
        FROM (
            SELECT game_pk, pitcher_id
            FROM gold.training_pitch_whiff
            GROUP BY game_pk, pitcher_id
            HAVING COUNT(DISTINCT pitcher_swings_prior_200) > 1
                OR COUNT(DISTINCT pitcher_whiff_rate_prior_200_swings) > 1
            UNION ALL
            SELECT game_pk, batter_id
            FROM gold.training_pitch_whiff
            GROUP BY game_pk, batter_id
            HAVING COUNT(DISTINCT batter_swings_prior_50) > 1
                OR COUNT(DISTINCT batter_whiff_rate_prior_50_swings) > 1
        ) AS changed_within_game
        """,
        True,
    ),
    (
        "hard_hit_rolling_features_are_pregame_constant",
        """
        SELECT COUNT(*) = 0
        FROM (
            SELECT game_pk, pitcher_id
            FROM gold.training_pitch_hard_hit
            GROUP BY game_pk, pitcher_id
            HAVING COUNT(DISTINCT pitcher_batted_balls_prior_200) > 1
                OR COUNT(DISTINCT pitcher_hard_hit_rate_allowed_prior_200_batted_balls) > 1
            UNION ALL
            SELECT game_pk, batter_id
            FROM gold.training_pitch_hard_hit
            GROUP BY game_pk, batter_id
            HAVING COUNT(DISTINCT batter_batted_balls_prior_50) > 1
                OR COUNT(DISTINCT batter_hard_hit_rate_prior_50_batted_balls) > 1
        ) AS changed_within_game
        """,
        True,
    ),
    (
        "rolling_event_counts_respect_windows",
        """
        SELECT
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff
             WHERE pitcher_swings_prior_200 NOT BETWEEN 0 AND 200
                OR batter_swings_prior_50 NOT BETWEEN 0 AND 50)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit
             WHERE pitcher_batted_balls_prior_200 NOT BETWEEN 0 AND 200
                OR batter_batted_balls_prior_50 NOT BETWEEN 0 AND 50)
        """,
        True,
    ),
    (
        "rolling_rates_are_valid_probabilities",
        """
        SELECT
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff
             WHERE pitcher_whiff_rate_prior_200_swings NOT BETWEEN 0 AND 1
                OR pitcher_whiff_rate_prior_14d NOT BETWEEN 0 AND 1
                OR pitcher_whiff_rate_prior_30d NOT BETWEEN 0 AND 1
                OR batter_whiff_rate_prior_50_swings NOT BETWEEN 0 AND 1
                OR batter_whiff_rate_prior_14d NOT BETWEEN 0 AND 1
                OR batter_whiff_rate_prior_30d NOT BETWEEN 0 AND 1)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit
             WHERE pitcher_hard_hit_rate_allowed_prior_200_batted_balls NOT BETWEEN 0 AND 1
                OR pitcher_hard_hit_rate_allowed_prior_14d NOT BETWEEN 0 AND 1
                OR pitcher_hard_hit_rate_allowed_prior_30d NOT BETWEEN 0 AND 1
                OR batter_hard_hit_rate_prior_50_batted_balls NOT BETWEEN 0 AND 1
                OR batter_hard_hit_rate_prior_14d NOT BETWEEN 0 AND 1
                OR batter_hard_hit_rate_prior_30d NOT BETWEEN 0 AND 1)
        """,
        True,
    ),
    (
        "rolling_history_excludes_first_observed_player_game",
        """
        WITH
        whiff_pitcher_first AS (
            SELECT pitcher_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_whiff GROUP BY pitcher_id
        ),
        whiff_batter_first AS (
            SELECT batter_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_whiff GROUP BY batter_id
        ),
        hard_hit_pitcher_first AS (
            SELECT pitcher_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_hard_hit GROUP BY pitcher_id
        ),
        hard_hit_batter_first AS (
            SELECT batter_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_hard_hit GROUP BY batter_id
        )
        SELECT
            (SELECT COUNT(*) = 0
             FROM gold.training_pitch_whiff AS training
             JOIN whiff_pitcher_first AS first USING (pitcher_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.pitcher_swings_prior_200 <> 0)
            AND
            (SELECT COUNT(*) = 0
             FROM gold.training_pitch_whiff AS training
             JOIN whiff_batter_first AS first USING (batter_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.batter_swings_prior_50 <> 0)
            AND
            (SELECT COUNT(*) = 0
             FROM gold.training_pitch_hard_hit AS training
             JOIN hard_hit_pitcher_first AS first USING (pitcher_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.pitcher_batted_balls_prior_200 <> 0)
            AND
            (SELECT COUNT(*) = 0
             FROM gold.training_pitch_hard_hit AS training
             JOIN hard_hit_batter_first AS first USING (batter_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.batter_batted_balls_prior_50 <> 0)
        """,
        True,
    ),
    (
        "pitch_type_and_matchup_features_are_pregame_constant",
        """
        SELECT COUNT(*) = 0
        FROM (
            SELECT game_pk, pitcher_id, pitch_type
            FROM gold.training_pitch_whiff
            GROUP BY game_pk, pitcher_id, pitch_type
            HAVING COUNT(DISTINCT pitcher_pitch_type_swings_prior_100) > 1
                OR COUNT(DISTINCT pitcher_pitch_type_whiff_rate_prior_100_swings) > 1
            UNION ALL
            SELECT game_pk, pitcher_id, batter_id
            FROM gold.training_pitch_whiff
            GROUP BY game_pk, pitcher_id, batter_id
            HAVING COUNT(DISTINCT matchup_swings_prior_30) > 1
                OR COUNT(DISTINCT matchup_whiff_rate_prior_30_swings) > 1
            UNION ALL
            SELECT game_pk, batter_id, pitch_type
            FROM gold.training_pitch_hard_hit
            GROUP BY game_pk, batter_id, pitch_type
            HAVING COUNT(DISTINCT batter_pitch_type_batted_balls_prior_30) > 1
                OR COUNT(DISTINCT batter_pitch_type_hard_hit_rate_prior_30_batted_balls) > 1
            UNION ALL
            SELECT game_pk, pitcher_id, batter_id
            FROM gold.training_pitch_hard_hit
            GROUP BY game_pk, pitcher_id, batter_id
            HAVING COUNT(DISTINCT matchup_batted_balls_prior_20) > 1
                OR COUNT(DISTINCT matchup_hard_hit_rate_prior_20_batted_balls) > 1
        ) AS changed_within_game
        """,
        True,
    ),
    (
        "pitch_type_and_matchup_windows_are_bounded",
        """
        SELECT
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff
             WHERE pitcher_pitch_type_swings_prior_100 NOT BETWEEN 0 AND 100
                OR batter_pitch_type_swings_prior_30 NOT BETWEEN 0 AND 30
                OR matchup_swings_prior_30 NOT BETWEEN 0 AND 30)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit
             WHERE pitcher_pitch_type_batted_balls_prior_100 NOT BETWEEN 0 AND 100
                OR batter_pitch_type_batted_balls_prior_30 NOT BETWEEN 0 AND 30
                OR matchup_batted_balls_prior_20 NOT BETWEEN 0 AND 20)
        """,
        True,
    ),
    (
        "pitch_type_and_matchup_rates_are_valid_probabilities",
        """
        SELECT
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff
             WHERE pitcher_pitch_type_whiff_rate_prior_100_swings NOT BETWEEN 0 AND 1
                OR pitcher_pitch_type_whiff_rate_prior_30d NOT BETWEEN 0 AND 1
                OR batter_pitch_type_whiff_rate_prior_30_swings NOT BETWEEN 0 AND 1
                OR batter_pitch_type_whiff_rate_prior_30d NOT BETWEEN 0 AND 1
                OR matchup_whiff_rate_prior_30_swings NOT BETWEEN 0 AND 1)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit
             WHERE pitcher_pitch_type_hard_hit_rate_allowed_prior_100_batted_balls NOT BETWEEN 0 AND 1
                OR pitcher_pitch_type_hard_hit_rate_allowed_prior_30d NOT BETWEEN 0 AND 1
                OR batter_pitch_type_hard_hit_rate_prior_30_batted_balls NOT BETWEEN 0 AND 1
                OR batter_pitch_type_hard_hit_rate_prior_30d NOT BETWEEN 0 AND 1
                OR matchup_hard_hit_rate_prior_20_batted_balls NOT BETWEEN 0 AND 1)
        """,
        True,
    ),
    (
        "pitch_type_and_matchup_history_excludes_first_group_game",
        """
        WITH
        whiff_pitch_type_first AS (
            SELECT pitcher_id, pitch_type, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_whiff GROUP BY pitcher_id, pitch_type
        ),
        whiff_matchup_first AS (
            SELECT pitcher_id, batter_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_whiff GROUP BY pitcher_id, batter_id
        ),
        hard_hit_pitch_type_first AS (
            SELECT batter_id, pitch_type, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_hard_hit GROUP BY batter_id, pitch_type
        ),
        hard_hit_matchup_first AS (
            SELECT pitcher_id, batter_id, MIN(game_datetime_utc) AS first_time
            FROM gold.training_pitch_hard_hit GROUP BY pitcher_id, batter_id
        )
        SELECT
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff AS training
             JOIN whiff_pitch_type_first AS first USING (pitcher_id, pitch_type)
             WHERE training.game_datetime_utc = first.first_time
               AND training.pitcher_pitch_type_swings_prior_100 <> 0)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_whiff AS training
             JOIN whiff_matchup_first AS first USING (pitcher_id, batter_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.matchup_swings_prior_30 <> 0)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit AS training
             JOIN hard_hit_pitch_type_first AS first USING (batter_id, pitch_type)
             WHERE training.game_datetime_utc = first.first_time
               AND training.batter_pitch_type_batted_balls_prior_30 <> 0)
            AND
            (SELECT COUNT(*) = 0 FROM gold.training_pitch_hard_hit AS training
             JOIN hard_hit_matchup_first AS first USING (pitcher_id, batter_id)
             WHERE training.game_datetime_utc = first.first_time
               AND training.matchup_batted_balls_prior_20 <> 0)
        """,
        True,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic data-quality checks.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(database_path), read_only=True)
    results = []
    for check_name, sql, expected in CHECKS:
        observed = connection.execute(sql).fetchone()[0]
        passed = bool(observed) == expected
        results.append(
            {
                "check_name": check_name,
                "status": "PASS" if passed else "FAIL",
                "observed": str(observed),
                "expected": str(expected),
            }
        )

    profile = connection.execute(
        """
        SELECT
            COUNT(*) AS pitch_rows,
            COUNT(DISTINCT game_pk) AS games,
            COUNT(DISTINCT pitcher_id) AS pitchers,
            MIN(game_date) AS first_game_date,
            MAX(game_date) AS last_game_date
        FROM silver.fact_pitch
        """
    ).fetchone()
    connection.close()

    report_path = outputs_dir / "data_quality_report.csv"
    with report_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["check_name", "status", "observed", "expected"])
        writer.writeheader()
        writer.writerows(results)

    print(
        "Profile | "
        f"pitches={profile[0]:,}, games={profile[1]:,}, pitchers={profile[2]:,}, "
        f"dates={profile[3]} to {profile[4]}"
    )
    for result in results:
        print(f"{result['status']:4} | {result['check_name']}")

    failed = [result for result in results if result["status"] == "FAIL"]
    if failed:
        raise SystemExit(f"Data-quality gate failed: {len(failed)} check(s).")


if __name__ == "__main__":
    main()
