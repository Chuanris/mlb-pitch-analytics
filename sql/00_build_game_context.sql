CREATE OR REPLACE TABLE silver.dim_venue AS
SELECT
    CAST(venue_id AS BIGINT) AS venue_id,
    CAST(venue_name AS VARCHAR) AS venue_name,
    CAST(city AS VARCHAR) AS city,
    CAST(state AS VARCHAR) AS state,
    CAST(country AS VARCHAR) AS country,
    CAST(latitude AS DOUBLE) AS latitude,
    CAST(longitude AS DOUBLE) AS longitude,
    CAST(azimuth_angle AS DOUBLE) AS azimuth_angle,
    CAST(elevation_ft AS DOUBLE) AS elevation_ft,
    CAST(time_zone_id AS VARCHAR) AS time_zone_id,
    CAST(roof_type AS VARCHAR) AS roof_type,
    CAST(turf_type AS VARCHAR) AS turf_type,
    CAST(source_url AS VARCHAR) AS source_url,
    CAST(loaded_at_utc AS VARCHAR) AS loaded_at_utc
FROM bronze.raw_venue
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY venue_id
    ORDER BY loaded_at_utc DESC
) = 1;

CREATE OR REPLACE TABLE silver.fact_game_context AS
SELECT
    CAST(context.game_pk AS BIGINT) AS game_pk,
    CAST(context.official_date AS DATE) AS official_date,
    CAST(context.game_status AS VARCHAR) AS game_status,
    CAST(context.game_datetime_utc AS TIMESTAMPTZ) AS game_datetime_utc,
    CAST(context.game_datetime_local AS VARCHAR) AS game_datetime_local,
    CAST(context.local_start_hour AS DOUBLE) AS local_start_hour,
    SIN(2 * PI() * CAST(context.local_start_hour AS DOUBLE) / 24.0) AS local_start_hour_sin,
    COS(2 * PI() * CAST(context.local_start_hour AS DOUBLE) / 24.0) AS local_start_hour_cos,
    CAST(context.local_day_of_week AS INTEGER) AS local_day_of_week,
    CAST(context.local_month AS INTEGER) AS local_month,
    CAST(context.weekend_flag AS INTEGER) AS weekend_flag,
    CAST(context.day_night AS VARCHAR) AS day_night,
    CAST(context.venue_id AS BIGINT) AS venue_id,
    CAST(context.venue_name AS VARCHAR) AS venue_name,
    venue.time_zone_id,
    venue.latitude,
    venue.longitude,
    venue.elevation_ft,
    venue.roof_type,
    venue.turf_type,
    CAST(context.temperature_f AS DOUBLE) AS temperature_f,
    CAST(context.weather_condition AS VARCHAR) AS weather_condition,
    CAST(context.wind_speed_mph AS DOUBLE) AS wind_speed_mph,
    CAST(context.wind_direction AS VARCHAR) AS wind_direction,
    CAST(context.wind_out_flag AS INTEGER) AS wind_out_flag,
    CAST(context.wind_in_flag AS INTEGER) AS wind_in_flag,
    CAST(context.crosswind_flag AS INTEGER) AS crosswind_flag,
    CAST(context.indoor_flag AS INTEGER) AS indoor_flag,
    CAST(context.source_url AS VARCHAR) AS source_url,
    CAST(context.source_start_date AS DATE) AS source_start_date,
    CAST(context.source_end_date AS DATE) AS source_end_date,
    CAST(context.loaded_at_utc AS VARCHAR) AS loaded_at_utc
FROM bronze.raw_game_context AS context
LEFT JOIN silver.dim_venue AS venue USING (venue_id)
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY context.game_pk
    ORDER BY context.loaded_at_utc DESC
) = 1;
