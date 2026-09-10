select
    pitcher_id,
    pitcher_name,
    pitcher_team,
    batter_stand,
    count_state,
    pitch_type,
    pitch_name,
    count(*) as pitch_count,
    sum(swing_flag) as swing_count,
    sum(whiff_flag) as whiff_count,
    sum(case when in_zone_flag = 0 then 1 else 0 end) as out_of_zone_pitch_count,
    sum(chase_flag) as chase_count,
    {{ safe_divide(
        'count(*)',
        'sum(count(*)) over (partition by pitcher_id, batter_stand, count_state)'
    ) }} as usage_rate_within_count,
    avg(release_speed) as avg_velocity,
    {{ safe_divide('sum(in_zone_flag)', 'count(*)') }} as zone_rate,
    {{ safe_divide('sum(whiff_flag)', 'sum(swing_flag)') }} as whiff_rate,
    {{ safe_divide('sum(chase_flag)', 'sum(case when in_zone_flag = 0 then 1 else 0 end)') }} as chase_rate
from {{ ref('int_pitch_outcomes') }}
group by
    pitcher_id,
    pitcher_name,
    pitcher_team,
    batter_stand,
    count_state,
    pitch_type,
    pitch_name
