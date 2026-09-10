CREATE SCHEMA IF NOT EXISTS operational;

CREATE TABLE IF NOT EXISTS operational.ingestion_runs (
    run_id UUID PRIMARY KEY,
    workflow VARCHAR(32) NOT NULL,
    source_start_date DATE NOT NULL,
    source_end_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    rows_received BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    CONSTRAINT ingestion_runs_workflow_check
        CHECK (workflow IN ('sample', 'daily', 'retrain', 'backfill')),
    CONSTRAINT ingestion_runs_status_check
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT ingestion_runs_source_window_check
        CHECK (source_start_date <= source_end_date),
    CONSTRAINT ingestion_runs_rows_received_check
        CHECK (rows_received >= 0),
    CONSTRAINT ingestion_runs_finished_state_check
        CHECK (
            (status = 'running' AND finished_at IS NULL)
            OR (status <> 'running' AND finished_at IS NOT NULL)
        )
);

CREATE TABLE IF NOT EXISTS operational.source_partitions (
    source_name VARCHAR(64) NOT NULL,
    partition_date DATE NOT NULL,
    object_uri TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    row_count BIGINT NOT NULL,
    run_id UUID NOT NULL REFERENCES operational.ingestion_runs(run_id),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_name, partition_date),
    CONSTRAINT source_partitions_source_name_check
        CHECK (length(btrim(source_name)) > 0),
    CONSTRAINT source_partitions_object_uri_check
        CHECK (length(btrim(object_uri)) > 0),
    CONSTRAINT source_partitions_sha256_check
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT source_partitions_row_count_check
        CHECK (row_count >= 0)
);

CREATE TABLE IF NOT EXISTS operational.forecast_requests (
    request_id UUID PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    game_pk BIGINT NOT NULL,
    pitcher_id BIGINT NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    requested_by VARCHAR(64) NOT NULL DEFAULT 'pipeline',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT forecast_requests_idempotency_key_check
        CHECK (length(btrim(idempotency_key)) > 0),
    CONSTRAINT forecast_requests_game_pk_check CHECK (game_pk > 0),
    CONSTRAINT forecast_requests_pitcher_id_check CHECK (pitcher_id > 0),
    CONSTRAINT forecast_requests_model_version_check
        CHECK (length(btrim(model_version)) > 0),
    CONSTRAINT forecast_requests_status_check
        CHECK (status IN ('pending', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS operational.forecast_results (
    request_id UUID PRIMARY KEY
        REFERENCES operational.forecast_requests(request_id) ON DELETE CASCADE,
    predicted_strikeouts NUMERIC(5, 2) NOT NULL,
    lower_bound SMALLINT NOT NULL,
    upper_bound SMALLINT NOT NULL,
    actual_strikeouts SMALLINT,
    outcome_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT forecast_results_prediction_check
        CHECK (predicted_strikeouts >= 0),
    CONSTRAINT forecast_results_interval_check
        CHECK (lower_bound >= 0 AND lower_bound <= upper_bound),
    CONSTRAINT forecast_results_actual_check
        CHECK (actual_strikeouts IS NULL OR actual_strikeouts >= 0),
    CONSTRAINT forecast_results_outcome_status_check
        CHECK (outcome_status IN ('pending', 'observed', 'excluded', 'invalid')),
    CONSTRAINT forecast_results_observed_value_check
        CHECK (
            (outcome_status = 'observed' AND actual_strikeouts IS NOT NULL)
            OR (outcome_status <> 'observed' AND actual_strikeouts IS NULL)
        )
);

CREATE TABLE IF NOT EXISTS operational.user_watchlists (
    user_id UUID NOT NULL,
    pitcher_id BIGINT NOT NULL,
    label VARCHAR(16) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, pitcher_id),
    CONSTRAINT user_watchlists_pitcher_id_check CHECK (pitcher_id > 0),
    CONSTRAINT user_watchlists_label_check
        CHECK (label IN ('available', 'roster', 'watchlist', 'unavailable'))
);

CREATE INDEX IF NOT EXISTS ingestion_runs_status_started_idx
    ON operational.ingestion_runs (status, started_at DESC);

CREATE INDEX IF NOT EXISTS source_partitions_date_idx
    ON operational.source_partitions (partition_date DESC)
    INCLUDE (source_name, row_count, content_sha256);

CREATE INDEX IF NOT EXISTS forecast_requests_pitcher_game_idx
    ON operational.forecast_requests (pitcher_id, game_pk, requested_at DESC);

CREATE INDEX IF NOT EXISTS forecast_requests_pending_idx
    ON operational.forecast_requests (requested_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS user_watchlists_user_label_idx
    ON operational.user_watchlists (user_id, label);

