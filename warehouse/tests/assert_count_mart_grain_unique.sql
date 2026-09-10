with duplicates as (
    select
        pitcher_id,
        pitcher_name,
        pitcher_team,
        batter_stand,
        count_state,
        pitch_type,
        pitch_name,
        count(*) as row_count
    from {{ ref('mart_count_strategy') }}
    group by
        pitcher_id,
        pitcher_name,
        pitcher_team,
        batter_stand,
        count_state,
        pitch_type,
        pitch_name
    having count(*) > 1
)

select * from duplicates
