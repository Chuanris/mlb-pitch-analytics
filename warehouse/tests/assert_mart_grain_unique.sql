with duplicates as (
    select
        pitcher_id,
        pitcher_name,
        pitcher_team,
        pitcher_throws,
        batter_stand,
        pitch_type,
        pitch_name,
        pitch_family,
        count(*) as row_count
    from {{ ref('mart_pitcher_pitch_type') }}
    group by
        pitcher_id,
        pitcher_name,
        pitcher_team,
        pitcher_throws,
        batter_stand,
        pitch_type,
        pitch_name,
        pitch_family
    having count(*) > 1
)

select * from duplicates
