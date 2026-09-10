select 'pitcher_pitch_type.zone_rate' as metric, zone_rate as invalid_value
from {{ ref('mart_pitcher_pitch_type') }}
where zone_rate < 0 or zone_rate > 1

union all

select 'pitcher_pitch_type.whiff_rate', whiff_rate
from {{ ref('mart_pitcher_pitch_type') }}
where whiff_rate < 0 or whiff_rate > 1

union all

select 'pitcher_pitch_type.chase_rate', chase_rate
from {{ ref('mart_pitcher_pitch_type') }}
where chase_rate < 0 or chase_rate > 1

union all

select 'pitcher_pitch_type.hard_hit_rate', hard_hit_rate
from {{ ref('mart_pitcher_pitch_type') }}
where hard_hit_rate < 0 or hard_hit_rate > 1

union all

select 'count_strategy.usage_rate_within_count', usage_rate_within_count
from {{ ref('mart_count_strategy') }}
where usage_rate_within_count < 0 or usage_rate_within_count > 1
