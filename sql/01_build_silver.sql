CREATE OR REPLACE TABLE silver.dim_pitch_type AS
SELECT *
FROM (
    VALUES
        ('FF', '4-Seam Fastball', 'Fastball'),
        ('SI', 'Sinker', 'Fastball'),
        ('FC', 'Cutter', 'Fastball'),
        ('SL', 'Slider', 'Breaking'),
        ('ST', 'Sweeper', 'Breaking'),
        ('CU', 'Curveball', 'Breaking'),
        ('KC', 'Knuckle Curve', 'Breaking'),
        ('SV', 'Slurve', 'Breaking'),
        ('CH', 'Changeup', 'Offspeed'),
        ('FS', 'Split-Finger', 'Offspeed'),
        ('FO', 'Forkball', 'Offspeed'),
        ('KN', 'Knuckleball', 'Other'),
        ('EP', 'Eephus', 'Other'),
        ('PO', 'Pitchout', 'Other')
) AS mapping(pitch_type, pitch_name_standard, pitch_family);

CREATE OR REPLACE TABLE silver.fact_pitch AS
WITH cleaned AS (
    SELECT
        CONCAT(
            CAST(game_pk AS VARCHAR), '-',
            CAST(at_bat_number AS VARCHAR), '-',
            CAST(pitch_number AS VARCHAR)
        ) AS pitch_id,
        CAST(game_pk AS BIGINT) AS game_pk,
        CAST(game_date AS DATE) AS game_date,
        CAST(game_year AS INTEGER) AS season,
        CAST(at_bat_number AS INTEGER) AS at_bat_number,
        CAST(pitch_number AS INTEGER) AS pitch_number,
        CAST(inning AS INTEGER) AS inning,
        CAST(inning_topbot AS VARCHAR) AS inning_half,
        CAST(pitcher AS BIGINT) AS pitcher_id,
        CAST(player_name AS VARCHAR) AS pitcher_name,
        CASE WHEN inning_topbot = 'Top' THEN home_team ELSE away_team END AS pitcher_team,
        CAST(batter AS BIGINT) AS batter_id,
        CASE WHEN inning_topbot = 'Top' THEN away_team ELSE home_team END AS batter_team,
        CAST(stand AS VARCHAR) AS batter_stand,
        CAST(p_throws AS VARCHAR) AS pitcher_throws,
        CAST(pitch_type AS VARCHAR) AS pitch_type,
        COALESCE(mapping.pitch_name_standard, CAST(raw.pitch_name AS VARCHAR), CAST(pitch_type AS VARCHAR)) AS pitch_name,
        COALESCE(mapping.pitch_family, 'Other') AS pitch_family,
        CAST(balls AS INTEGER) AS balls,
        CAST(strikes AS INTEGER) AS strikes,
        CASE
            WHEN balls = 0 AND strikes = 0 THEN 'First Pitch'
            WHEN strikes = 2 THEN 'Two Strikes'
            WHEN strikes > balls THEN 'Pitcher Ahead'
            WHEN balls > strikes THEN 'Hitter Ahead'
            ELSE 'Even'
        END AS count_state,
        CAST(description AS VARCHAR) AS pitch_description,
        CAST(events AS VARCHAR) AS plate_appearance_event,
        CASE
            WHEN description IN (
                'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
                'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
                'foul_bunt', 'missed_bunt', 'bunt_foul_tip'
            ) THEN 1 ELSE 0
        END AS swing_flag,
        CASE
            WHEN description IN ('swinging_strike', 'swinging_strike_blocked', 'missed_bunt')
            THEN 1 ELSE 0
        END AS whiff_flag,
        CASE WHEN zone BETWEEN 1 AND 9 THEN 1 ELSE 0 END AS in_zone_flag,
        CASE
            WHEN zone NOT BETWEEN 1 AND 9
             AND description IN (
                'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
                'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
                'foul_bunt', 'missed_bunt', 'bunt_foul_tip'
             ) THEN 1 ELSE 0
        END AS chase_flag,
        CASE
            WHEN description IN ('hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score')
            THEN 1 ELSE 0
        END AS batted_ball_flag,
        CASE
            WHEN description IN ('hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score')
             AND launch_speed IS NULL THEN NULL
            WHEN description IN ('hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score')
             AND launch_speed >= 95 THEN 1 ELSE 0
        END AS hard_hit_flag,
        CASE
            WHEN description IN ('swinging_strike', 'swinging_strike_blocked', 'missed_bunt') THEN 'Whiff'
            WHEN description IN ('called_strike') THEN 'Called Strike'
            WHEN description IN ('foul', 'foul_tip', 'foul_bunt', 'bunt_foul_tip') THEN 'Foul'
            WHEN description IN ('hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score') THEN 'In Play'
            WHEN description IN ('ball', 'blocked_ball', 'pitchout', 'hit_by_pitch') THEN 'Ball'
            ELSE 'Other'
        END AS result_group,
        CAST(release_speed AS DOUBLE) AS release_speed,
        CAST(effective_speed AS DOUBLE) AS effective_speed,
        CAST(release_spin_rate AS DOUBLE) AS release_spin_rate,
        CAST(spin_axis AS DOUBLE) AS spin_axis,
        CAST(release_pos_x AS DOUBLE) AS release_pos_x,
        CAST(release_pos_y AS DOUBLE) AS release_pos_y,
        CAST(release_pos_z AS DOUBLE) AS release_pos_z,
        CAST(release_extension AS DOUBLE) AS release_extension,
        CAST(arm_angle AS DOUBLE) AS arm_angle,
        CAST(pfx_x AS DOUBLE) AS horizontal_movement,
        CAST(pfx_z AS DOUBLE) AS vertical_movement,
        CAST(plate_x AS DOUBLE) AS plate_x,
        CAST(plate_z AS DOUBLE) AS plate_z,
        CAST(sz_top AS DOUBLE) AS strike_zone_top,
        CAST(sz_bot AS DOUBLE) AS strike_zone_bottom,
        CASE
            WHEN sz_top > sz_bot THEN (plate_z - sz_bot) / (sz_top - sz_bot)
            ELSE NULL
        END::DOUBLE AS normalized_plate_z,
        CAST(zone AS INTEGER) AS zone,
        CAST(outs_when_up AS INTEGER) AS outs_when_up,
        CASE WHEN on_1b IS NOT NULL THEN 1 ELSE 0 END AS runner_on_first_flag,
        CASE WHEN on_2b IS NOT NULL THEN 1 ELSE 0 END AS runner_on_second_flag,
        CASE WHEN on_3b IS NOT NULL THEN 1 ELSE 0 END AS runner_on_third_flag,
        CAST(bat_score - fld_score AS INTEGER) AS batter_score_diff,
        CAST(n_thruorder_pitcher AS INTEGER) AS times_through_order,
        CAST(pitcher_days_since_prev_game AS DOUBLE) AS pitcher_days_rest,
        CAST(batter_days_since_prev_game AS DOUBLE) AS batter_days_rest,
        CAST(age_pit AS DOUBLE) AS pitcher_age,
        CAST(age_bat AS DOUBLE) AS batter_age,
        CASE
            WHEN game_year >= 2026 THEN '2026_ABS_ALIGNMENT'
            ELSE 'PRE_2026_TRACKING'
        END AS tracking_regime,
        CAST(launch_speed AS DOUBLE) AS launch_speed,
        CAST(launch_angle AS DOUBLE) AS launch_angle,
        CAST(estimated_woba_using_speedangle AS DOUBLE) AS estimated_woba,
        CAST(home_team AS VARCHAR) AS home_team,
        CAST(away_team AS VARCHAR) AS away_team,
        CAST(game_type AS VARCHAR) AS game_type,
        CAST(source_start_date AS DATE) AS source_start_date,
        CAST(source_end_date AS DATE) AS source_end_date,
        CAST(loaded_at_utc AS VARCHAR) AS loaded_at_utc
    FROM bronze.raw_statcast AS raw
    LEFT JOIN silver.dim_pitch_type AS mapping USING (pitch_type)
    WHERE game_type = 'R'
      AND EXISTS (
          SELECT 1
          FROM metadata.pipeline_ranges AS configured
          WHERE CAST(raw.game_year AS INTEGER) = configured.season
            AND CAST(raw.game_date AS DATE) BETWEEN configured.start_date AND configured.end_date
      )
      AND pitch_type IS NOT NULL
      AND game_pk IS NOT NULL
      AND at_bat_number IS NOT NULL
      AND pitch_number IS NOT NULL
)
SELECT *
FROM cleaned
QUALIFY ROW_NUMBER() OVER (PARTITION BY pitch_id ORDER BY loaded_at_utc DESC) = 1;
