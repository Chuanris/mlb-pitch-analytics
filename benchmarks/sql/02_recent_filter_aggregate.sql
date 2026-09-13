SELECT
    pitcher_id,
    pitch_type,
    COUNT(*) AS pitch_count,
    SUM(swing_flag) AS swing_count,
    SUM(whiff_flag) AS whiff_count,
    ROUND(AVG(CAST(release_speed AS DECIMAL(10, 3))), 3) AS avg_release_speed
FROM silver.fact_pitch
WHERE game_date >= DATE '{cutoff_date}'
GROUP BY pitcher_id, pitch_type
ORDER BY pitcher_id, pitch_type;
