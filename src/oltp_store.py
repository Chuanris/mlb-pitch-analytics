from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "oltp" / "migrations"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FINAL_INGESTION_STATUSES = {"succeeded", "failed", "cancelled"}
OUTCOME_STATUSES = {"pending", "observed", "excluded", "invalid"}


def database_url_from_env(variable: str = "MLB_OLTP_DATABASE_URL") -> str:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise RuntimeError(
            f"Set {variable} to a PostgreSQL connection URL. "
            "See docs/OLTP.md for the local setup."
        )
    return value


def connect_postgres(database_url: str):
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL support is optional. Install requirements-oltp.txt first."
        ) from error
    return psycopg.connect(database_url, autocommit=True)


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise FileNotFoundError(f"No PostgreSQL migrations found in {directory}")
    return files


def split_sql_statements(sql: str) -> Iterable[str]:
    """Split the deliberately simple DDL migrations into executable statements."""
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            yield statement


def apply_migrations(connection: Any, directory: Path = MIGRATIONS_DIR) -> list[str]:
    connection.execute("CREATE SCHEMA IF NOT EXISTS operational")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS operational.schema_migrations (
            migration_id VARCHAR(128) PRIMARY KEY,
            content_sha256 CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied: list[str] = []
    for path in migration_files(directory):
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        row = connection.execute(
            "SELECT content_sha256 FROM operational.schema_migrations WHERE migration_id = %s",
            (path.name,),
        ).fetchone()
        if row:
            if row[0] != checksum:
                raise RuntimeError(
                    f"Applied migration changed on disk: {path.name}. "
                    "Create a new numbered migration instead of editing history."
                )
            continue
        with connection.transaction():
            for statement in split_sql_statements(sql):
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO operational.schema_migrations (migration_id, content_sha256)
                VALUES (%s, %s)
                """,
                (path.name, checksum),
            )
        applied.append(path.name)
    return applied


def normalize_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError("content_sha256 must contain exactly 64 hexadecimal characters")
    return normalized


def start_ingestion_run(
    connection: Any,
    workflow: str,
    source_start_date: date,
    source_end_date: date,
    run_id: UUID | None = None,
) -> UUID:
    if source_start_date > source_end_date:
        raise ValueError("source_start_date must not be after source_end_date")
    identifier = run_id or uuid4()
    connection.execute(
        """
        INSERT INTO operational.ingestion_runs (
            run_id, workflow, source_start_date, source_end_date
        ) VALUES (%s, %s, %s, %s)
        """,
        (identifier, workflow, source_start_date, source_end_date),
    )
    return identifier


def finish_ingestion_run(
    connection: Any,
    run_id: UUID,
    status: str,
    rows_received: int,
    error_message: str | None = None,
) -> None:
    if status not in FINAL_INGESTION_STATUSES:
        raise ValueError(f"Final ingestion status must be one of {sorted(FINAL_INGESTION_STATUSES)}")
    if rows_received < 0:
        raise ValueError("rows_received must not be negative")
    row = connection.execute(
        """
        UPDATE operational.ingestion_runs
        SET status = %s,
            rows_received = %s,
            error_message = %s,
            finished_at = CURRENT_TIMESTAMP
        WHERE run_id = %s AND status = 'running'
        RETURNING run_id
        """,
        (status, rows_received, error_message, run_id),
    ).fetchone()
    if not row:
        raise KeyError(f"No running ingestion run found for {run_id}")


def upsert_source_partition(
    connection: Any,
    *,
    source_name: str,
    partition_date: date,
    object_uri: str,
    content_sha256: str,
    row_count: int,
    run_id: UUID,
) -> None:
    if row_count < 0:
        raise ValueError("row_count must not be negative")
    checksum = normalize_sha256(content_sha256)
    connection.execute(
        """
        INSERT INTO operational.source_partitions (
            source_name, partition_date, object_uri, content_sha256, row_count, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_name, partition_date) DO UPDATE
        SET object_uri = EXCLUDED.object_uri,
            content_sha256 = EXCLUDED.content_sha256,
            row_count = EXCLUDED.row_count,
            run_id = EXCLUDED.run_id,
            observed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (source_name, partition_date, object_uri, checksum, row_count, run_id),
    )


def get_or_create_forecast_request(
    connection: Any,
    *,
    idempotency_key: str,
    game_pk: int,
    pitcher_id: int,
    model_version: str,
    requested_by: str = "pipeline",
) -> UUID:
    key = idempotency_key.strip()
    if not key or len(key) > 128:
        raise ValueError("idempotency_key must contain 1 to 128 characters")
    request_id = uuid4()
    row = connection.execute(
        """
        INSERT INTO operational.forecast_requests AS existing (
            request_id, idempotency_key, game_pk, pitcher_id, model_version, requested_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO UPDATE
        SET updated_at = existing.updated_at
        RETURNING request_id
        """,
        (request_id, key, game_pk, pitcher_id, model_version, requested_by),
    ).fetchone()
    return UUID(str(row[0]))


def record_forecast_result(
    connection: Any,
    *,
    request_id: UUID,
    predicted_strikeouts: float,
    lower_bound: int,
    upper_bound: int,
    outcome_status: str = "pending",
    actual_strikeouts: int | None = None,
) -> None:
    if outcome_status not in OUTCOME_STATUSES:
        raise ValueError(f"outcome_status must be one of {sorted(OUTCOME_STATUSES)}")
    with connection.transaction():
        connection.execute(
            """
            UPDATE operational.forecast_requests
            SET status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE request_id = %s
            """,
            (request_id,),
        )
        connection.execute(
            """
            INSERT INTO operational.forecast_results (
                request_id, predicted_strikeouts, lower_bound, upper_bound,
                actual_strikeouts, outcome_status
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (request_id) DO UPDATE
            SET predicted_strikeouts = EXCLUDED.predicted_strikeouts,
                lower_bound = EXCLUDED.lower_bound,
                upper_bound = EXCLUDED.upper_bound,
                actual_strikeouts = EXCLUDED.actual_strikeouts,
                outcome_status = EXCLUDED.outcome_status,
                recorded_at = CURRENT_TIMESTAMP
            """,
            (
                request_id,
                predicted_strikeouts,
                lower_bound,
                upper_bound,
                actual_strikeouts,
                outcome_status,
            ),
        )


def summarize_store(connection: Any) -> dict[str, int]:
    names = (
        "ingestion_runs",
        "source_partitions",
        "forecast_requests",
        "forecast_results",
        "user_watchlists",
    )
    return {
        name: int(connection.execute(f"SELECT COUNT(*) FROM operational.{name}").fetchone()[0])
        for name in names
    }


def run_demo(connection: Any) -> dict[str, Any]:
    applied = apply_migrations(connection)
    today = date.today()
    run_id = start_ingestion_run(connection, "sample", today, today)
    upsert_source_partition(
        connection,
        source_name="statcast",
        partition_date=today,
        object_uri=f"file:///data/raw/statcast_{today}_{today}.parquet",
        content_sha256="0" * 64,
        row_count=100,
        run_id=run_id,
    )
    key = f"demo:{run_id}"
    first = get_or_create_forecast_request(
        connection,
        idempotency_key=key,
        game_pk=1,
        pitcher_id=1,
        model_version="demo-v1",
    )
    second = get_or_create_forecast_request(
        connection,
        idempotency_key=key,
        game_pk=1,
        pitcher_id=1,
        model_version="demo-v1",
    )
    if first != second:
        raise RuntimeError("Idempotency check created more than one forecast request")
    record_forecast_result(
        connection,
        request_id=first,
        predicted_strikeouts=5.5,
        lower_bound=3,
        upper_bound=8,
    )
    finish_ingestion_run(connection, run_id, "succeeded", rows_received=100)
    return {
        "applied_migrations": applied,
        "run_id": str(run_id),
        "idempotent_request_id": str(first),
        "table_counts": summarize_store(connection),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operate the optional PostgreSQL OLTP store.")
    parser.add_argument("command", choices=("migrate", "demo", "status"))
    parser.add_argument("--database-url-env", default="MLB_OLTP_DATABASE_URL")
    args = parser.parse_args(argv)
    database_url = database_url_from_env(args.database_url_env)
    connection = connect_postgres(database_url)
    try:
        if args.command == "migrate":
            result: Any = {"applied_migrations": apply_migrations(connection)}
        elif args.command == "demo":
            result = run_demo(connection)
        else:
            result = summarize_store(connection)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

