WITH pitcher_date AS (
    SELECT
        pitcher_id,
        game_date,
        COUNT(*) AS pitch_count,
        SUM(whiff_flag) AS whiff_count
    FROM silver.fact_pitch
    GROUP BY pitcher_id, game_date
)
SELECT
    pitcher_id,
    game_date,
    pitch_count,
    whiff_count,
    SUM(pitch_count) OVER (
        PARTITION BY pitcher_id
        ORDER BY game_date
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ) AS rolling_10_date_pitch_count,
    SUM(whiff_count) OVER (
        PARTITION BY pitcher_id
        ORDER BY game_date
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    ) AS rolling_10_date_whiff_count
FROM pitcher_date
ORDER BY pitcher_id, game_date;
