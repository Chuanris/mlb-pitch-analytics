select
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family,
    count(*) as pitch_count,
    sum(swing_flag) as swing_count,
    sum(whiff_flag) as whiff_count,
    sum(case when in_zone_flag = 0 then 1 else 0 end) as out_of_zone_pitch_count,
    sum(chase_flag) as chase_count,
    sum(batted_ball_flag) as batted_ball_count,
    sum(case when batted_ball_flag = 1 and hard_hit_flag is not null then 1 else 0 end)
        as measured_batted_ball_count,
    sum(hard_hit_flag) as hard_hit_count,
    avg(release_speed) as avg_velocity,
    avg(release_spin_rate) as avg_spin_rate,
    avg(horizontal_movement) as avg_horizontal_movement,
    avg(vertical_movement) as avg_vertical_movement,
    {{ safe_divide('sum(in_zone_flag)', 'count(*)') }} as zone_rate,
    {{ safe_divide('sum(swing_flag)', 'count(*)') }} as swing_rate,
    {{ safe_divide('sum(whiff_flag)', 'sum(swing_flag)') }} as whiff_rate,
    {{ safe_divide('sum(chase_flag)', 'sum(case when in_zone_flag = 0 then 1 else 0 end)') }} as chase_rate,
    avg(case when batted_ball_flag = 1 then launch_speed end) as avg_exit_velocity,
    {{ safe_divide(
        'sum(hard_hit_flag)',
        'sum(case when batted_ball_flag = 1 and hard_hit_flag is not null then 1 else 0 end)'
    ) }} as hard_hit_rate,
    avg(case when batted_ball_flag = 1 then estimated_woba end) as avg_estimated_woba
from {{ ref('int_pitch_outcomes') }}
group by
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family
