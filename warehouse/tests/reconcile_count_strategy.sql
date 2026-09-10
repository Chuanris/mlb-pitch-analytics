{{ config(enabled=target.type == 'duckdb') }}

with expected as (
    select
        pitcher_id,
        batter_stand,
        count_state,
        pitch_type,
        pitch_count,
        swing_count,
        whiff_count,
        out_of_zone_pitch_count,
        chase_count
    from {{ source('legacy_gold', 'count_strategy_summary') }}
),
actual as (
    select
        pitcher_id,
        batter_stand,
        count_state,
        pitch_type,
        pitch_count,
        swing_count,
        whiff_count,
        out_of_zone_pitch_count,
        chase_count
    from {{ ref('mart_count_strategy') }}
),
differences as (
    (select * from expected except distinct select * from actual)
    union all
    (select * from actual except distinct select * from expected)
)

select * from differences
