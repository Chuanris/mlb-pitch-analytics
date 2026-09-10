{% if target.type == 'bigquery' %}
    {{ config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='pitch_id',
        on_schema_change='sync_all_columns',
        partition_by={"field": "game_date", "data_type": "date", "granularity": "day"},
        cluster_by=["pitcher_id", "pitch_type"]
    ) }}
{% else %}
    {{ config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='pitch_id',
        on_schema_change='sync_all_columns'
    ) }}
{% endif %}

with pitches as (
    select *
    from {{ ref('stg_statcast') }}
    {% if is_incremental() %}
    where game_date >= (
        select coalesce(max(game_date), cast('1900-01-01' as date))
        from {{ this }}
    )
    {% endif %}
)

select
    pitches.pitch_id,
    pitches.game_pk,
    pitches.game_date,
    pitches.season,
    pitches.at_bat_number,
    pitches.pitch_number,
    pitches.inning,
    pitches.inning_half,
    pitches.pitcher_id,
    pitches.pitcher_name,
    pitches.pitcher_team,
    pitches.batter_id,
    pitches.batter_team,
    pitches.batter_stand,
    pitches.pitcher_throws,
    pitches.pitch_type,
    coalesce(mapping.pitch_name_standard, pitches.raw_pitch_name, pitches.pitch_type) as pitch_name,
    coalesce(mapping.pitch_family, 'Other') as pitch_family,
    pitches.balls,
    pitches.strikes,
    case
        when pitches.balls = 0 and pitches.strikes = 0 then 'First Pitch'
        when pitches.strikes = 2 then 'Two Strikes'
        when pitches.strikes > pitches.balls then 'Pitcher Ahead'
        when pitches.balls > pitches.strikes then 'Hitter Ahead'
        else 'Even'
    end as count_state,
    pitches.pitch_description,
    pitches.plate_appearance_event,
    case when pitches.pitch_description in (
        'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
        'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
        'foul_bunt', 'missed_bunt', 'bunt_foul_tip'
    ) then 1 else 0 end as swing_flag,
    case when pitches.pitch_description in (
        'swinging_strike', 'swinging_strike_blocked', 'missed_bunt'
    ) then 1 else 0 end as whiff_flag,
    case when pitches.zone between 1 and 9 then 1 else 0 end as in_zone_flag,
    case
        when pitches.zone not between 1 and 9
         and pitches.pitch_description in (
            'swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip',
            'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
            'foul_bunt', 'missed_bunt', 'bunt_foul_tip'
         ) then 1 else 0
    end as chase_flag,
    case when pitches.pitch_description in (
        'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'
    ) then 1 else 0 end as batted_ball_flag,
    case
        when pitches.pitch_description in (
            'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'
        ) and pitches.launch_speed is null then null
        when pitches.pitch_description in (
            'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score'
        ) and pitches.launch_speed >= 95 then 1
        else 0
    end as hard_hit_flag,
    pitches.release_speed,
    pitches.release_spin_rate,
    pitches.horizontal_movement,
    pitches.vertical_movement,
    pitches.launch_speed,
    pitches.estimated_woba,
    pitches.loaded_at_utc
from pitches
left join {{ ref('pitch_type_mapping') }} as mapping
    on pitches.pitch_type = mapping.pitch_type
