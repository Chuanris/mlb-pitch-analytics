with scoped_raw as (
    select
        concat(
            cast(game_pk as {{ dbt.type_string() }}), '-',
            cast(at_bat_number as {{ dbt.type_string() }}), '-',
            cast(pitch_number as {{ dbt.type_string() }})
        ) as pitch_id,
        game_pk,
        cast(game_date as date) as game_date,
        game_year as season,
        at_bat_number,
        pitch_number,
        inning,
        inning_topbot as inning_half,
        pitcher as pitcher_id,
        player_name as pitcher_name,
        case when inning_topbot = 'Top' then home_team else away_team end as pitcher_team,
        batter as batter_id,
        case when inning_topbot = 'Top' then away_team else home_team end as batter_team,
        stand as batter_stand,
        p_throws as pitcher_throws,
        pitch_type,
        pitch_name as raw_pitch_name,
        balls,
        strikes,
        description as pitch_description,
        events as plate_appearance_event,
        zone,
        release_speed,
        release_spin_rate,
        pfx_x as horizontal_movement,
        pfx_z as vertical_movement,
        launch_speed,
        estimated_woba_using_speedangle as estimated_woba,
        loaded_at_utc
    from {{ source('bronze', 'raw_statcast') }} as raw
    where game_type = 'R'
      and pitch_type is not null
      and game_pk is not null
      and at_bat_number is not null
      and pitch_number is not null
      and exists (
          select 1
          from {{ source('metadata', 'pipeline_ranges') }} as configured
          where raw.game_year = configured.season
            and cast(raw.game_date as date) between configured.start_date and configured.end_date
      )
)

select *
from scoped_raw
qualify row_number() over (
    partition by pitch_id
    order by loaded_at_utc desc
) = 1
