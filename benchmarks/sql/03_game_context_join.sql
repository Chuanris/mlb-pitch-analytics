SELECT
    context.venue_id,
    context.day_night,
    pitch.pitch_type,
    COUNT(*) AS pitch_count,
    SUM(pitch.swing_flag) AS swing_count,
    SUM(pitch.whiff_flag) AS whiff_count
FROM silver.fact_pitch AS pitch
JOIN silver.fact_game_context AS context USING (game_pk)
GROUP BY context.venue_id, context.day_night, pitch.pitch_type
ORDER BY context.venue_id, context.day_night, pitch.pitch_type;
