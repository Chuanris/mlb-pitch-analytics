"""Verify BigQuery row contracts and record query-cost/performance evidence."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import time

from google.cloud import bigquery


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
EXPECTED_COUNTS = {
    "raw_statcast": 12,
    "stg_statcast": 9,
    "int_pitch_outcomes": 9,
    "mart_pitcher_pitch_type": 5,
    "mart_count_strategy": 9,
}


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} contains unsupported characters: {value!r}")
    return value


def dry_run_bytes(
    client: bigquery.Client,
    query: str,
    parameters: list[bigquery.ScalarQueryParameter] | None,
    location: str,
) -> int:
    config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        query_parameters=parameters or [],
    )
    job = client.query(query, job_config=config, location=location)
    return int(job.total_bytes_processed or 0)


def verify(args: argparse.Namespace) -> dict[str, object]:
    project = validate_identifier(args.project, "project")
    prefix = validate_identifier(args.dataset_prefix, "dataset_prefix")
    client = bigquery.Client(project=project, location=args.location)

    silver_dataset = f"{prefix}_silver"
    gold_dataset = f"{prefix}_gold"
    outcomes_table_id = f"{project}.{silver_dataset}.int_pitch_outcomes"
    outcomes_table = client.get_table(outcomes_table_id)

    partition_field = (
        outcomes_table.time_partitioning.field
        if outcomes_table.time_partitioning is not None
        else None
    )
    clustering_fields = list(outcomes_table.clustering_fields or [])
    if partition_field != "game_date":
        raise AssertionError(f"Expected game_date partition, found {partition_field!r}")
    if clustering_fields != ["pitcher_id", "pitch_type"]:
        raise AssertionError(
            "Expected pitcher_id,pitch_type clustering, found "
            + repr(clustering_fields)
        )

    counts_query = f"""
    select
      (select count(*) from `{project}.bronze.raw_statcast`) as raw_statcast,
      (select count(*) from `{project}.{silver_dataset}.stg_statcast`) as stg_statcast,
      (select count(*) from `{outcomes_table_id}`) as int_pitch_outcomes,
      (select count(*) from `{project}.{gold_dataset}.mart_pitcher_pitch_type`) as mart_pitcher_pitch_type,
      (select count(*) from `{project}.{gold_dataset}.mart_count_strategy`) as mart_count_strategy
    """
    count_row = next(iter(client.query(counts_query, location=args.location).result()))
    counts = {key: int(count_row[key]) for key in EXPECTED_COUNTS}
    if counts != EXPECTED_COUNTS:
        raise AssertionError(f"Unexpected fixture counts: {counts}; expected {EXPECTED_COUNTS}")

    aggregate = f"""
    select pitcher_id, pitch_type, count(*) as pitch_count
    from `{outcomes_table_id}`
    where game_date between @start_date and @end_date
    group by pitcher_id, pitch_type
    order by pitcher_id, pitch_type
    """
    aggregate_unbounded = f"""
    select pitcher_id, pitch_type, count(*) as pitch_count
    from `{outcomes_table_id}`
    group by pitcher_id, pitch_type
    order by pitcher_id, pitch_type
    """
    parameters = [
        bigquery.ScalarQueryParameter("start_date", "DATE", date(2025, 4, 2)),
        bigquery.ScalarQueryParameter("end_date", "DATE", date(2025, 4, 2)),
    ]
    bounded_bytes = dry_run_bytes(client, aggregate, parameters, args.location)
    unbounded_bytes = dry_run_bytes(client, aggregate_unbounded, None, args.location)

    config = bigquery.QueryJobConfig(
        use_query_cache=False,
        maximum_bytes_billed=args.maximum_bytes_billed,
        query_parameters=parameters,
        labels={"workload": "portfolio-proof", "component": "dbt-benchmark"},
    )
    started = time.perf_counter()
    job = client.query(aggregate, job_config=config, location=args.location)
    rows = list(job.result())
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "location": args.location,
        "fixture_counts": counts,
        "physical_design": {
            "table": outcomes_table_id,
            "partition_field": partition_field,
            "clustering_fields": clustering_fields,
        },
        "benchmark": {
            "date_filter": {"start": "2025-04-02", "end": "2025-04-02"},
            "bounded_dry_run_bytes": bounded_bytes,
            "unbounded_dry_run_bytes": unbounded_bytes,
            "bytes_avoided_by_filter": max(unbounded_bytes - bounded_bytes, 0),
            "actual_bytes_processed": int(job.total_bytes_processed or 0),
            "actual_bytes_billed": int(job.total_bytes_billed or 0),
            "slot_millis": int(job.slot_millis or 0),
            "cache_hit": bool(job.cache_hit),
            "elapsed_ms_client_observed": elapsed_ms,
            "result_rows": len(rows),
            "maximum_bytes_billed": args.maximum_bytes_billed,
            "job_id": job.job_id,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset-prefix", default="dbt_mlb")
    parser.add_argument("--location", default="US")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-bytes-billed", type=int, default=100_000_000)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    report = verify(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
