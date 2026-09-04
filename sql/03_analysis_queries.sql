-- Query 1: League pitch mix with basic outcome rates.
SELECT
    pitch_name,
    COUNT(*) AS pitch_count,
    COUNT(*)::DOUBLE / SUM(COUNT(*)) OVER () AS usage_rate,
    AVG(release_speed) AS avg_velocity,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate
FROM silver.fact_pitch
GROUP BY pitch_name
HAVING COUNT(*) >= 10
ORDER BY pitch_count DESC;

-- Query 2: How a pitcher's pitch mix changes by count state.
SELECT
    pitcher_name,
    count_state,
    pitch_name,
    pitch_count,
    usage_rate_within_count,
    whiff_rate,
    chase_rate
FROM gold.count_strategy_summary
WHERE pitcher_name = 'Glasnow, Tyler'
  AND pitch_count >= 5
ORDER BY count_state, usage_rate_within_count DESC;

-- Query 3: Rank pitch types within each pitcher using a window function.
WITH qualified AS (
    SELECT
        pitcher_name,
        pitcher_team,
        pitch_name,
        SUM(pitch_count) AS pitch_count,
        SUM(whiff_count)::DOUBLE / NULLIF(SUM(swing_count), 0) AS whiff_rate
    FROM gold.pitcher_pitch_type_summary
    GROUP BY pitcher_name, pitcher_team, pitch_name
    HAVING SUM(pitch_count) >= 20
), ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (
            PARTITION BY pitcher_name
            ORDER BY pitch_count DESC
        ) AS usage_rank
    FROM qualified
)
SELECT *
FROM ranked
WHERE usage_rank <= 3
ORDER BY pitcher_name, usage_rank;
