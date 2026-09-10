{{ config(enabled=target.type == 'duckdb') }}

with expected as (
    select
        pitcher_id,
        batter_stand,
        pitch_type,
        pitch_count,
        swing_count,
        whiff_count,
        out_of_zone_pitch_count,
        chase_count,
        batted_ball_count,
        measured_batted_ball_count
    from {{ source('legacy_gold', 'pitcher_pitch_type_summary') }}
),
actual as (
    select
        pitcher_id,
        batter_stand,
        pitch_type,
        pitch_count,
        swing_count,
        whiff_count,
        out_of_zone_pitch_count,
        chase_count,
        batted_ball_count,
        measured_batted_ball_count
    from {{ ref('mart_pitcher_pitch_type') }}
),
differences as (
    (select * from expected except distinct select * from actual)
    union all
    (select * from actual except distinct select * from expected)
)

select * from differences
