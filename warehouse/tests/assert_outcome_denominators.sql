select *
from {{ ref('mart_pitcher_pitch_type') }}
where whiff_count > swing_count
   or chase_count > out_of_zone_pitch_count
   or measured_batted_ball_count > batted_ball_count
   or hard_hit_count > measured_batted_ball_count
