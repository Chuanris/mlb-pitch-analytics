from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.common import (
    configured_game_context_paths,
    configured_partition_paths,
    empty_partition_marker,
    load_config,
    project_path,
    resolved_mode_ranges,
)


def execute_sql_file(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    connection.execute(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build bronze, silver, and gold DuckDB layers.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    args = parser.parse_args()

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    expected_files = configured_partition_paths(config, args.mode)
    missing_files = [
        path for path in expected_files
        if not path.is_file() and not empty_partition_marker(path).is_file()
    ]
    if missing_files:
        formatted = "\n".join(f"- {path}" for path in missing_files)
        raise FileNotFoundError(
            f"Missing {len(missing_files)} expected {args.mode} partition(s):\n{formatted}\n"
            f"Run extraction for --mode {args.mode} first."
        )
    parquet_files = [path for path in expected_files if path.is_file()]
    if not parquet_files:
        raise FileNotFoundError(f"No non-empty {args.mode} Parquet partitions are available.")

    expected_context_files = configured_game_context_paths(config, args.mode)
    missing_context_files = [path for path in expected_context_files if not path.is_file()]
    if missing_context_files:
        formatted = "\n".join(f"- {path}" for path in missing_context_files)
        raise FileNotFoundError(
            f"Missing {len(missing_context_files)} expected game-context partition(s):\n{formatted}\n"
            f"Run game-context extraction for --mode {args.mode} first."
        )
    venue_path = project_path(config["paths"]["venue_reference"])
    if not venue_path.is_file():
        raise FileNotFoundError(f"Missing MLB venue reference: {venue_path}")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        connection.execute("CREATE SCHEMA IF NOT EXISTS silver")
        connection.execute("CREATE SCHEMA IF NOT EXISTS gold")
        connection.execute("CREATE SCHEMA IF NOT EXISTS metadata")

        ranges = resolved_mode_ranges(config, args.mode)
        connection.execute(
            """
            CREATE OR REPLACE TABLE metadata.pipeline_config AS
            SELECT
                ?::VARCHAR AS mode,
                ?::INTEGER AS start_season,
                ?::INTEGER AS end_season,
                ?::DATE AS start_date,
                ?::DATE AS end_date,
                ?::INTEGER AS range_count
            """,
            [
                args.mode,
                min(item["season"] for item in ranges),
                max(item["season"] for item in ranges),
                min(item["start_date"] for item in ranges),
                max(item["end_date"] for item in ranges),
                len(ranges),
            ],
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE metadata.pipeline_ranges (
                season INTEGER,
                start_date DATE,
                end_date DATE,
                chunk_days INTEGER,
                latest_complete_day BOOLEAN
            )
            """
        )
        connection.executemany(
            "INSERT INTO metadata.pipeline_ranges VALUES (?, ?, ?, ?, ?)",
            [
                [
                    item["season"], item["start_date"], item["end_date"],
                    item["chunk_days"], item["latest_complete_day"],
                ]
                for item in ranges
            ],
        )

        escaped_paths = [str(path).replace("'", "''") for path in parquet_files]
        parquet_list = ", ".join(f"'{path}'" for path in escaped_paths)
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.raw_statcast AS
            SELECT *
            FROM read_parquet([{parquet_list}], union_by_name = true)
            """
        )

        escaped_context_paths = [str(path).replace("'", "''") for path in expected_context_files]
        context_list = ", ".join(f"'{path}'" for path in escaped_context_paths)
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.raw_game_context AS
            SELECT *
            FROM read_parquet([{context_list}], union_by_name = true)
            """
        )
        escaped_venue_path = str(venue_path).replace("'", "''")
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE bronze.raw_venue AS
            SELECT *
            FROM read_parquet('{escaped_venue_path}')
            """
        )

        sql_dir = project_path("sql")
        execute_sql_file(connection, sql_dir / "00_build_game_context.sql")
        execute_sql_file(connection, sql_dir / "01_build_silver.sql")
        execute_sql_file(connection, sql_dir / "02_build_gold.sql")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata.pipeline_runs (
                run_at_utc TIMESTAMP,
                raw_file_count INTEGER,
                raw_row_count BIGINT,
                fact_pitch_row_count BIGINT
            )
            """
        )
        raw_rows = connection.execute("SELECT COUNT(*) FROM bronze.raw_statcast").fetchone()[0]
        fact_rows = connection.execute("SELECT COUNT(*) FROM silver.fact_pitch").fetchone()[0]
        connection.execute(
            """
            INSERT INTO metadata.pipeline_runs (
                run_at_utc, raw_file_count, raw_row_count, fact_pitch_row_count
            ) VALUES (?, ?, ?, ?)
            """,
            [datetime.now(timezone.utc), len(parquet_files), raw_rows, fact_rows],
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    print(f"Database built: {database_path}")
    print(
        f"Mode: {args.mode} | Seasons: {ranges[0]['season']}-{ranges[-1]['season']} | "
        f"Raw partitions: {len(parquet_files)}"
    )
    print(f"Raw rows: {raw_rows:,} | Regular-season pitch rows: {fact_rows:,}")


if __name__ == "__main__":
    main()
