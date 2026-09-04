CREATE OR REPLACE TABLE gold.pitcher_pitch_type_summary AS
SELECT
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family,
    COUNT(*) AS pitch_count,
    SUM(swing_flag) AS swing_count,
    SUM(whiff_flag) AS whiff_count,
    SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END) AS out_of_zone_pitch_count,
    SUM(chase_flag) AS chase_count,
    SUM(batted_ball_flag) AS batted_ball_count,
    SUM(hard_hit_flag) AS hard_hit_count,
    AVG(release_speed) AS avg_velocity,
    AVG(release_spin_rate) AS avg_spin_rate,
    AVG(horizontal_movement) AS avg_horizontal_movement,
    AVG(vertical_movement) AS avg_vertical_movement,
    SUM(in_zone_flag)::DOUBLE / COUNT(*) AS zone_rate,
    SUM(swing_flag)::DOUBLE / COUNT(*) AS swing_rate,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate,
    AVG(CASE WHEN batted_ball_flag = 1 THEN launch_speed END) AS avg_exit_velocity,
    SUM(hard_hit_flag)::DOUBLE / NULLIF(SUM(batted_ball_flag), 0) AS hard_hit_rate,
    AVG(CASE WHEN batted_ball_flag = 1 THEN estimated_woba END) AS avg_estimated_woba
FROM silver.fact_pitch
GROUP BY
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family;

CREATE OR REPLACE TABLE gold.count_strategy_summary AS
SELECT
    pitcher_id,
    pitcher_name,
    pitcher_team,
    batter_stand,
    count_state,
    pitch_type,
    pitch_name,
    COUNT(*) AS pitch_count,
    SUM(swing_flag) AS swing_count,
    SUM(whiff_flag) AS whiff_count,
    SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END) AS out_of_zone_pitch_count,
    SUM(chase_flag) AS chase_count,
    COUNT(*)::DOUBLE
        / SUM(COUNT(*)) OVER (
            PARTITION BY pitcher_id, batter_stand, count_state
        ) AS usage_rate_within_count,
    AVG(release_speed) AS avg_velocity,
    SUM(in_zone_flag)::DOUBLE / COUNT(*) AS zone_rate,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate
FROM silver.fact_pitch
GROUP BY
    pitcher_id,
    pitcher_name,
    pitcher_team,
    batter_stand,
    count_state,
    pitch_type,
    pitch_name;

CREATE OR REPLACE TABLE gold.pitcher_month_summary AS
SELECT
    DATE_TRUNC('month', game_date)::DATE AS month,
    pitcher_id,
    pitcher_name,
    pitcher_team,
    COUNT(*) AS pitch_count,
    SUM(swing_flag) AS swing_count,
    SUM(whiff_flag) AS whiff_count,
    SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END) AS out_of_zone_pitch_count,
    SUM(chase_flag) AS chase_count,
    SUM(batted_ball_flag) AS batted_ball_count,
    SUM(hard_hit_flag) AS hard_hit_count,
    AVG(release_speed) AS avg_velocity,
    SUM(in_zone_flag)::DOUBLE / COUNT(*) AS zone_rate,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate,
    SUM(hard_hit_flag)::DOUBLE / NULLIF(SUM(batted_ball_flag), 0) AS hard_hit_rate
FROM silver.fact_pitch
GROUP BY
    DATE_TRUNC('month', game_date)::DATE,
    pitcher_id,
    pitcher_name,
    pitcher_team;

CREATE OR REPLACE TABLE gold.tableau_pitch_detail AS
SELECT
    pitch_id,
    game_date,
    game_pk,
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family,
    balls,
    strikes,
    count_state,
    result_group,
    release_speed,
    release_spin_rate,
    horizontal_movement,
    vertical_movement,
    plate_x,
    plate_z,
    zone,
    in_zone_flag,
    swing_flag,
    whiff_flag,
    chase_flag,
    batted_ball_flag,
    launch_speed,
    launch_angle,
    hard_hit_flag,
    estimated_woba
FROM silver.fact_pitch;

-- Reusable post-release pitch features. Only binary eligibility/label flags are
-- retained here; result text, launch metrics, estimated wOBA, and other
-- same-pitch outcomes remain outside the model feature layer.
CREATE OR REPLACE TABLE gold.pitch_model_features AS
WITH sequenced AS (
    SELECT
        pitch_id,
        game_pk,
        game_date,
        season,
        at_bat_number,
        pitch_number,
        pitcher_id,
        batter_id,
        pitcher_team,
        batter_team,
        pitcher_throws,
        batter_stand,
        pitch_type,
        pitch_family,
        balls,
        strikes,
        count_state,
        inning,
        inning_half,
        outs_when_up,
        runner_on_first_flag,
        runner_on_second_flag,
        runner_on_third_flag,
        batter_score_diff,
        times_through_order,
        pitcher_days_rest,
        batter_days_rest,
        pitcher_age,
        batter_age,
        tracking_regime,
        context.game_datetime_utc,
        context.game_datetime_local,
        context.local_start_hour,
        context.local_start_hour_sin,
        context.local_start_hour_cos,
        context.local_day_of_week,
        context.local_month,
        context.weekend_flag,
        context.day_night,
        context.venue_id,
        context.venue_name,
        context.time_zone_id,
        context.latitude AS venue_latitude,
        context.longitude AS venue_longitude,
        context.elevation_ft,
        context.roof_type,
        context.turf_type,
        context.temperature_f,
        context.weather_condition,
        context.wind_speed_mph,
        context.wind_direction,
        context.wind_out_flag,
        context.wind_in_flag,
        context.crosswind_flag,
        context.indoor_flag,
        release_speed,
        effective_speed,
        release_spin_rate,
        spin_axis,
        release_pos_x,
        release_pos_y,
        release_pos_z,
        release_extension,
        arm_angle,
        horizontal_movement,
        vertical_movement,
        plate_x,
        plate_z,
        strike_zone_top,
        strike_zone_bottom,
        normalized_plate_z,
        in_zone_flag,
        swing_flag,
        whiff_flag,
        batted_ball_flag,
        hard_hit_flag,
        ROW_NUMBER() OVER (
            PARTITION BY game_pk, pitcher_id
            ORDER BY at_bat_number, pitch_number
        ) AS pitcher_pitch_number_in_game,
        LAG(pitch_number) OVER plate_appearance_sequence AS previous_pitch_number,
        LAG(pitch_type) OVER plate_appearance_sequence AS previous_pitch_type,
        LAG(pitch_family) OVER plate_appearance_sequence AS previous_pitch_family,
        LAG(release_speed) OVER plate_appearance_sequence AS previous_release_speed,
        LAG(plate_x) OVER plate_appearance_sequence AS previous_plate_x,
        LAG(plate_z) OVER plate_appearance_sequence AS previous_plate_z,
        release_speed - LAG(release_speed) OVER plate_appearance_sequence
            AS release_speed_change,
        plate_x - LAG(plate_x) OVER plate_appearance_sequence AS plate_x_change,
        plate_z - LAG(plate_z) OVER plate_appearance_sequence AS plate_z_change
    FROM silver.fact_pitch AS pitch
    LEFT JOIN silver.fact_game_context AS context USING (game_pk)
    WINDOW plate_appearance_sequence AS (
        PARTITION BY game_pk, at_bat_number
        ORDER BY pitch_number
    )
)
SELECT *
FROM sequenced;

-- Pregame rolling form is calculated only from eligible events that occurred
-- before the current game's first eligible event. The snapshot is then shared
-- by every eligible pitch in that player-game, so the current game can never
-- leak into its own features.
CREATE OR REPLACE TABLE gold.training_pitch_whiff AS
WITH eligible AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS pitcher_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY batter_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS batter_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, pitch_type, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS pitcher_pitch_type_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY batter_id, pitch_type, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS batter_pitch_type_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, batter_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS matchup_game_event_number
    FROM gold.pitch_model_features
    WHERE swing_flag = 1
),
history AS (
    SELECT
        *,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 200 PRECEDING AND 1 PRECEDING
        ) AS pitcher_swings_prior_200,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 200 PRECEDING AND 1 PRECEDING
        ) AS pitcher_whiff_rate_prior_200_swings,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_swings_prior_30d,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_whiff_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_swings_prior_14d,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_whiff_rate_prior_14d,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING
        ) AS batter_swings_prior_50,
        AVG(whiff_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING
        ) AS batter_whiff_rate_prior_50_swings,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_swings_prior_30d,
        AVG(whiff_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_whiff_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_swings_prior_14d,
        AVG(whiff_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_whiff_rate_prior_14d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 100 PRECEDING AND 1 PRECEDING
        ) AS pitcher_pitch_type_swings_prior_100,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 100 PRECEDING AND 1 PRECEDING
        ) AS pitcher_pitch_type_whiff_rate_prior_100_swings,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_pitch_type_swings_prior_30d,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_pitch_type_whiff_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS batter_pitch_type_swings_prior_30,
        AVG(whiff_flag) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS batter_pitch_type_whiff_rate_prior_30_swings,
        COUNT(*) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_pitch_type_swings_prior_30d,
        AVG(whiff_flag) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_pitch_type_whiff_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS matchup_swings_prior_30,
        AVG(whiff_flag) OVER (
            PARTITION BY pitcher_id, batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS matchup_whiff_rate_prior_30_swings
    FROM eligible
),
pitcher_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        pitcher_swings_prior_200,
        pitcher_whiff_rate_prior_200_swings,
        pitcher_swings_prior_30d,
        pitcher_whiff_rate_prior_30d,
        pitcher_swings_prior_14d,
        pitcher_whiff_rate_prior_14d
    FROM history
    WHERE pitcher_game_event_number = 1
),
batter_game_history AS (
    SELECT
        game_pk,
        batter_id,
        batter_swings_prior_50,
        batter_whiff_rate_prior_50_swings,
        batter_swings_prior_30d,
        batter_whiff_rate_prior_30d,
        batter_swings_prior_14d,
        batter_whiff_rate_prior_14d
    FROM history
    WHERE batter_game_event_number = 1
),
pitcher_pitch_type_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        pitch_type,
        pitcher_pitch_type_swings_prior_100,
        pitcher_pitch_type_whiff_rate_prior_100_swings,
        pitcher_pitch_type_swings_prior_30d,
        pitcher_pitch_type_whiff_rate_prior_30d
    FROM history
    WHERE pitcher_pitch_type_game_event_number = 1
),
batter_pitch_type_game_history AS (
    SELECT
        game_pk,
        batter_id,
        pitch_type,
        batter_pitch_type_swings_prior_30,
        batter_pitch_type_whiff_rate_prior_30_swings,
        batter_pitch_type_swings_prior_30d,
        batter_pitch_type_whiff_rate_prior_30d
    FROM history
    WHERE batter_pitch_type_game_event_number = 1
),
matchup_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        batter_id,
        matchup_swings_prior_30,
        matchup_whiff_rate_prior_30_swings
    FROM history
    WHERE matchup_game_event_number = 1
)
SELECT
    eligible.* EXCLUDE (
        swing_flag, whiff_flag, batted_ball_flag, hard_hit_flag,
        pitcher_game_event_number, batter_game_event_number,
        pitcher_pitch_type_game_event_number,
        batter_pitch_type_game_event_number,
        matchup_game_event_number
    ),
    pitcher_history.pitcher_swings_prior_200,
    pitcher_history.pitcher_whiff_rate_prior_200_swings,
    pitcher_history.pitcher_swings_prior_30d,
    pitcher_history.pitcher_whiff_rate_prior_30d,
    pitcher_history.pitcher_swings_prior_14d,
    pitcher_history.pitcher_whiff_rate_prior_14d,
    batter_history.batter_swings_prior_50,
    batter_history.batter_whiff_rate_prior_50_swings,
    batter_history.batter_swings_prior_30d,
    batter_history.batter_whiff_rate_prior_30d,
    batter_history.batter_swings_prior_14d,
    batter_history.batter_whiff_rate_prior_14d,
    pitcher_pitch_type_history.pitcher_pitch_type_swings_prior_100,
    pitcher_pitch_type_history.pitcher_pitch_type_whiff_rate_prior_100_swings,
    pitcher_pitch_type_history.pitcher_pitch_type_swings_prior_30d,
    pitcher_pitch_type_history.pitcher_pitch_type_whiff_rate_prior_30d,
    batter_pitch_type_history.batter_pitch_type_swings_prior_30,
    batter_pitch_type_history.batter_pitch_type_whiff_rate_prior_30_swings,
    batter_pitch_type_history.batter_pitch_type_swings_prior_30d,
    batter_pitch_type_history.batter_pitch_type_whiff_rate_prior_30d,
    matchup_history.matchup_swings_prior_30,
    matchup_history.matchup_whiff_rate_prior_30_swings,
    eligible.whiff_flag AS target_whiff
FROM eligible
JOIN pitcher_game_history AS pitcher_history USING (game_pk, pitcher_id)
JOIN batter_game_history AS batter_history USING (game_pk, batter_id)
JOIN pitcher_pitch_type_game_history AS pitcher_pitch_type_history USING (game_pk, pitcher_id, pitch_type)
JOIN batter_pitch_type_game_history AS batter_pitch_type_history USING (game_pk, batter_id, pitch_type)
JOIN matchup_game_history AS matchup_history USING (game_pk, pitcher_id, batter_id);

CREATE OR REPLACE TABLE gold.training_pitch_hard_hit AS
WITH eligible AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS pitcher_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY batter_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS batter_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, pitch_type, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS pitcher_pitch_type_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY batter_id, pitch_type, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS batter_pitch_type_game_event_number,
        ROW_NUMBER() OVER (
            PARTITION BY pitcher_id, batter_id, game_pk
            ORDER BY at_bat_number, pitch_number, pitch_id
        ) AS matchup_game_event_number
    FROM gold.pitch_model_features
    WHERE batted_ball_flag = 1
),
history AS (
    SELECT
        *,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 200 PRECEDING AND 1 PRECEDING
        ) AS pitcher_batted_balls_prior_200,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 200 PRECEDING AND 1 PRECEDING
        ) AS pitcher_hard_hit_rate_allowed_prior_200_batted_balls,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_batted_balls_prior_30d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_hard_hit_rate_allowed_prior_30d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_batted_balls_prior_14d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_hard_hit_rate_allowed_prior_14d,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING
        ) AS batter_batted_balls_prior_50,
        AVG(hard_hit_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING
        ) AS batter_hard_hit_rate_prior_50_batted_balls,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_batted_balls_prior_30d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_hard_hit_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_batted_balls_prior_14d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY batter_id
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_hard_hit_rate_prior_14d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 100 PRECEDING AND 1 PRECEDING
        ) AS pitcher_pitch_type_batted_balls_prior_100,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 100 PRECEDING AND 1 PRECEDING
        ) AS pitcher_pitch_type_hard_hit_rate_allowed_prior_100_batted_balls,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_pitch_type_batted_balls_prior_30d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS pitcher_pitch_type_hard_hit_rate_allowed_prior_30d,
        COUNT(*) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS batter_pitch_type_batted_balls_prior_30,
        AVG(hard_hit_flag) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
        ) AS batter_pitch_type_hard_hit_rate_prior_30_batted_balls,
        COUNT(*) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_pitch_type_batted_balls_prior_30d,
        AVG(hard_hit_flag) OVER (
            PARTITION BY batter_id, pitch_type
            ORDER BY game_datetime_utc
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING
        ) AS batter_pitch_type_hard_hit_rate_prior_30d,
        COUNT(*) OVER (
            PARTITION BY pitcher_id, batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS matchup_batted_balls_prior_20,
        AVG(hard_hit_flag) OVER (
            PARTITION BY pitcher_id, batter_id
            ORDER BY game_datetime_utc, game_pk, at_bat_number, pitch_number, pitch_id
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS matchup_hard_hit_rate_prior_20_batted_balls
    FROM eligible
),
pitcher_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        pitcher_batted_balls_prior_200,
        pitcher_hard_hit_rate_allowed_prior_200_batted_balls,
        pitcher_batted_balls_prior_30d,
        pitcher_hard_hit_rate_allowed_prior_30d,
        pitcher_batted_balls_prior_14d,
        pitcher_hard_hit_rate_allowed_prior_14d
    FROM history
    WHERE pitcher_game_event_number = 1
),
batter_game_history AS (
    SELECT
        game_pk,
        batter_id,
        batter_batted_balls_prior_50,
        batter_hard_hit_rate_prior_50_batted_balls,
        batter_batted_balls_prior_30d,
        batter_hard_hit_rate_prior_30d,
        batter_batted_balls_prior_14d,
        batter_hard_hit_rate_prior_14d
    FROM history
    WHERE batter_game_event_number = 1
),
pitcher_pitch_type_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        pitch_type,
        pitcher_pitch_type_batted_balls_prior_100,
        pitcher_pitch_type_hard_hit_rate_allowed_prior_100_batted_balls,
        pitcher_pitch_type_batted_balls_prior_30d,
        pitcher_pitch_type_hard_hit_rate_allowed_prior_30d
    FROM history
    WHERE pitcher_pitch_type_game_event_number = 1
),
batter_pitch_type_game_history AS (
    SELECT
        game_pk,
        batter_id,
        pitch_type,
        batter_pitch_type_batted_balls_prior_30,
        batter_pitch_type_hard_hit_rate_prior_30_batted_balls,
        batter_pitch_type_batted_balls_prior_30d,
        batter_pitch_type_hard_hit_rate_prior_30d
    FROM history
    WHERE batter_pitch_type_game_event_number = 1
),
matchup_game_history AS (
    SELECT
        game_pk,
        pitcher_id,
        batter_id,
        matchup_batted_balls_prior_20,
        matchup_hard_hit_rate_prior_20_batted_balls
    FROM history
    WHERE matchup_game_event_number = 1
)
SELECT
    eligible.* EXCLUDE (
        swing_flag, whiff_flag, batted_ball_flag, hard_hit_flag,
        pitcher_game_event_number, batter_game_event_number,
        pitcher_pitch_type_game_event_number,
        batter_pitch_type_game_event_number,
        matchup_game_event_number
    ),
    pitcher_history.pitcher_batted_balls_prior_200,
    pitcher_history.pitcher_hard_hit_rate_allowed_prior_200_batted_balls,
    pitcher_history.pitcher_batted_balls_prior_30d,
    pitcher_history.pitcher_hard_hit_rate_allowed_prior_30d,
    pitcher_history.pitcher_batted_balls_prior_14d,
    pitcher_history.pitcher_hard_hit_rate_allowed_prior_14d,
    batter_history.batter_batted_balls_prior_50,
    batter_history.batter_hard_hit_rate_prior_50_batted_balls,
    batter_history.batter_batted_balls_prior_30d,
    batter_history.batter_hard_hit_rate_prior_30d,
    batter_history.batter_batted_balls_prior_14d,
    batter_history.batter_hard_hit_rate_prior_14d,
    pitcher_pitch_type_history.pitcher_pitch_type_batted_balls_prior_100,
    pitcher_pitch_type_history.pitcher_pitch_type_hard_hit_rate_allowed_prior_100_batted_balls,
    pitcher_pitch_type_history.pitcher_pitch_type_batted_balls_prior_30d,
    pitcher_pitch_type_history.pitcher_pitch_type_hard_hit_rate_allowed_prior_30d,
    batter_pitch_type_history.batter_pitch_type_batted_balls_prior_30,
    batter_pitch_type_history.batter_pitch_type_hard_hit_rate_prior_30_batted_balls,
    batter_pitch_type_history.batter_pitch_type_batted_balls_prior_30d,
    batter_pitch_type_history.batter_pitch_type_hard_hit_rate_prior_30d,
    matchup_history.matchup_batted_balls_prior_20,
    matchup_history.matchup_hard_hit_rate_prior_20_batted_balls,
    eligible.hard_hit_flag AS target_hard_hit
FROM eligible
JOIN pitcher_game_history AS pitcher_history USING (game_pk, pitcher_id)
JOIN batter_game_history AS batter_history USING (game_pk, batter_id)
JOIN pitcher_pitch_type_game_history AS pitcher_pitch_type_history USING (game_pk, pitcher_id, pitch_type)
JOIN batter_pitch_type_game_history AS batter_pitch_type_history USING (game_pk, batter_id, pitch_type)
JOIN matchup_game_history AS matchup_history USING (game_pk, pitcher_id, batter_id);
