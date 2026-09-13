from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "database" / "mlb_pitch_analytics.duckdb"
DEFAULT_SQL_DIR = Path(__file__).resolve().parent / "sql"
DEFAULT_JSON_OUTPUT = Path(__file__).resolve().parent / "results" / "latest.json"
DEFAULT_MARKDOWN_OUTPUT = Path(__file__).resolve().parent / "results" / "latest.md"
DEFAULT_EXPLAIN_DIR = Path(__file__).resolve().parent / "results" / "explain"


@dataclass(frozen=True)
class QuerySpec:
    name: str
    filename: str
    workload: str


QUERY_SPECS = (
    QuerySpec("full_scan_aggregate", "01_full_scan_aggregate.sql", "scan + grouped aggregate"),
    QuerySpec("recent_filter_aggregate", "02_recent_filter_aggregate.sql", "selective date filter + aggregate"),
    QuerySpec("game_context_join", "03_game_context_join.sql", "fact-to-dimension hash join + aggregate"),
    QuerySpec("partitioned_window", "04_partitioned_window.sql", "grouped input + partitioned window"),
)


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def canonical_rows(rows: Iterable[Sequence[Any]]) -> bytes:
    normalized = []
    for row in rows:
        normalized.append(
            [
                value.isoformat()
                if isinstance(value, (date, datetime))
                else value
                for value in row
            ]
        )
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def result_signature(rows: Sequence[Sequence[Any]]) -> str:
    return hashlib.sha256(canonical_rows(rows)).hexdigest()


def load_queries(sql_dir: Path, cutoff_date: date) -> list[tuple[QuerySpec, str]]:
    queries = []
    for spec in QUERY_SPECS:
        sql = (sql_dir / spec.filename).read_text(encoding="utf-8")
        sql = sql.format(cutoff_date=cutoff_date.isoformat()).strip()
        if "{" in sql or "}" in sql:
            raise ValueError(f"Unresolved SQL template token in {spec.filename}")
        queries.append((spec, sql))
    return queries


def execute_materialized(connection: duckdb.DuckDBPyConnection, sql: str) -> tuple[float, list[tuple[Any, ...]]]:
    started = time.perf_counter_ns()
    rows = connection.execute(sql).fetchall()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return elapsed_ms, rows


def summarize_timings(milliseconds: Sequence[float]) -> dict[str, Any]:
    return {
        "runs_ms": [round(value, 3) for value in milliseconds],
        "min_ms": round(min(milliseconds), 3),
        "median_ms": round(statistics.median(milliseconds), 3),
        "p95_ms": round(percentile(milliseconds, 0.95), 3),
        "max_ms": round(max(milliseconds), 3),
    }


def database_profile(connection: duckdb.DuckDBPyConnection, database_path: Path) -> dict[str, Any]:
    row_count, first_date, last_date = connection.execute(
        "SELECT COUNT(*), MIN(game_date), MAX(game_date) FROM silver.fact_pitch"
    ).fetchone()
    context_rows = connection.execute("SELECT COUNT(*) FROM silver.fact_game_context").fetchone()[0]
    return {
        "database_file": database_path.name,
        "database_bytes": database_path.stat().st_size,
        "fact_pitch_rows": row_count,
        "fact_game_context_rows": context_rows,
        "first_game_date": first_date.isoformat(),
        "last_game_date": last_date.isoformat(),
    }


def extract_explain_plan(connection: duckdb.DuckDBPyConnection, sql: str) -> str:
    rows = connection.execute(f"EXPLAIN ANALYZE {sql}").fetchall()
    return "\n".join(str(row[-1]) for row in rows)


def run_benchmark(
    database_path: Path,
    sql_dir: Path = DEFAULT_SQL_DIR,
    thread_counts: Sequence[int] = (1, 2, 4, 8),
    repetitions: int = 5,
    warmups: int = 1,
    capture_explain: bool = True,
) -> tuple[dict[str, Any], dict[str, str]]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    resolved_threads = sorted(set(thread_counts))
    if not resolved_threads or any(value < 1 for value in resolved_threads):
        raise ValueError("thread counts must be positive integers")
    if not database_path.is_file():
        raise FileNotFoundError(f"DuckDB database not found: {database_path}")

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        profile = database_profile(connection, database_path)
        last_date = date.fromisoformat(profile["last_game_date"])
        cutoff_date = last_date - timedelta(days=29)
        recent_filter_rows = connection.execute(
            "SELECT COUNT(*) FROM silver.fact_pitch WHERE game_date >= ?",
            [cutoff_date],
        ).fetchone()[0]
        profile["recent_filter_input_rows"] = recent_filter_rows
        profile["recent_filter_selectivity_pct"] = round(
            recent_filter_rows / profile["fact_pitch_rows"] * 100,
            3,
        )
        queries = load_queries(sql_dir, cutoff_date)
        results: list[dict[str, Any]] = []
        expected_signatures: dict[str, tuple[int, str]] = {}

        for spec, sql in queries:
            for threads in resolved_threads:
                connection.execute(f"SET threads TO {threads}")
                first_observed_ms, first_rows = execute_materialized(connection, sql)
                for _ in range(warmups):
                    execute_materialized(connection, sql)

                timings = []
                measured_rows: list[tuple[Any, ...]] = []
                for _ in range(repetitions):
                    elapsed_ms, measured_rows = execute_materialized(connection, sql)
                    timings.append(elapsed_ms)

                first_signature = result_signature(first_rows)
                measured_signature = result_signature(measured_rows)
                if first_signature != measured_signature or len(first_rows) != len(measured_rows):
                    raise RuntimeError(f"Non-deterministic result within {spec.name} at {threads} threads")

                signature_key = (len(measured_rows), measured_signature)
                expected = expected_signatures.setdefault(spec.name, signature_key)
                if signature_key != expected:
                    raise RuntimeError(f"Result mismatch across thread counts for {spec.name}")

                summary = summarize_timings(timings)
                summary.update(
                    {
                        "query": spec.name,
                        "workload": spec.workload,
                        "threads": threads,
                        "first_observed_ms": round(first_observed_ms, 3),
                        "result_rows": len(measured_rows),
                        "result_sha256": measured_signature,
                    }
                )
                results.append(summary)

        one_thread_medians = {
            row["query"]: row["median_ms"] for row in results if row["threads"] == 1
        }
        for row in results:
            baseline = one_thread_medians.get(row["query"])
            row["speedup_vs_1_thread"] = (
                round(baseline / row["median_ms"], 3)
                if baseline is not None and row["median_ms"] > 0
                else None
            )

        plans: dict[str, str] = {}
        explain_threads = max(resolved_threads)
        if capture_explain:
            connection.execute(f"SET threads TO {explain_threads}")
            for spec, sql in queries:
                plans[spec.name] = extract_explain_plan(connection, sql)

        report = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "methodology": {
                "timer": "time.perf_counter_ns wall-clock time",
                "materialization": "Each query is fully fetched into Python.",
                "first_observed": "Recorded separately and not used for speedup claims; it is not a cold-cache guarantee.",
                "warmups_per_configuration": warmups,
                "measured_repetitions_per_configuration": repetitions,
                "summary_statistic": "Median; p95 is linearly interpolated over measured repetitions.",
                "correctness_gate": "Result row count and SHA-256 must match across all thread counts.",
                "recent_filter_cutoff_inclusive": cutoff_date.isoformat(),
            },
            "environment": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "duckdb_version": duckdb.__version__,
                "logical_cpu_count": os.cpu_count(),
                "thread_counts": resolved_threads,
                "explain_analyze_threads": explain_threads if capture_explain else None,
            },
            "dataset": profile,
            "results": results,
        }
        return report, plans
    finally:
        connection.close()


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    method = report["methodology"]
    environment = report["environment"]
    lines = [
        "# DuckDB SQL performance benchmark",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        "This snapshot is machine-specific evidence from a local analytical database. It is not a distributed MPP benchmark.",
        "",
        "## Environment and data",
        "",
        f"- DuckDB `{environment['duckdb_version']}` on `{environment['platform']}`",
        f"- Python `{environment['python_version']}`; {environment['logical_cpu_count']} logical CPUs visible",
        f"- Database: `{dataset['database_file']}` ({dataset['database_bytes']:,} bytes)",
        f"- `silver.fact_pitch`: {dataset['fact_pitch_rows']:,} rows, {dataset['first_game_date']} through {dataset['last_game_date']}",
        f"- `silver.fact_game_context`: {dataset['fact_game_context_rows']:,} rows",
        f"- Recent-filter cutoff: `{method['recent_filter_cutoff_inclusive']}` (inclusive)",
        f"- Recent-filter input: {dataset['recent_filter_input_rows']:,} rows ({dataset['recent_filter_selectivity_pct']:.3f}% of pitch facts)",
        "",
        "## Results",
        "",
        "| Query | Workload | Threads | Median ms | p95 ms | Speedup vs 1 thread | Result rows |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["results"]:
        speedup = row["speedup_vs_1_thread"]
        speedup_text = f"{speedup:.3f}x" if speedup is not None else "n/a"
        lines.append(
            f"| `{row['query']}` | {row['workload']} | {row['threads']} | "
            f"{row['median_ms']:.3f} | {row['p95_ms']:.3f} | {speedup_text} | {row['result_rows']:,} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundaries",
            "",
            "- Median warm-run wall-clock latency is the comparison metric; `first_observed_ms` is retained in JSON but is not called cold-cache latency.",
            "- The date-filter query demonstrates predicate selectivity in this DuckDB file; it does not claim physical partition pruning.",
            "- More threads can be slower for small or coordination-heavy queries. Report the observed result rather than assuming linear scaling.",
            "- Timings include complete result materialization into Python and will vary with hardware, cache state, background load and DuckDB version.",
            "- Every query's row count and SHA-256 matched across thread counts during this run.",
            "",
            "See `docs/SQL_PERFORMANCE.md` for the reproducible command, query rationale and interview framing.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    report: dict[str, Any],
    plans: dict[str, str],
    json_output: Path,
    markdown_output: Path,
    explain_dir: Path,
) -> None:
    explain_files: dict[str, str] = {}
    if plans:
        explain_dir.mkdir(parents=True, exist_ok=True)
        for name, plan in plans.items():
            destination = explain_dir / f"{name}.txt"
            destination.write_text(plan.rstrip() + "\n", encoding="utf-8")
            explain_files[name] = destination.relative_to(ROOT).as_posix()
    report["explain_analyze_files"] = explain_files

    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_output.write_text(render_markdown(report), encoding="utf-8")


def default_thread_counts() -> list[int]:
    logical_cpus = os.cpu_count() or 1
    return [value for value in (1, 2, 4, 8) if value <= logical_cpus] or [1]


def parse_thread_counts(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("threads must be comma-separated integers") from error
    if not values or any(item < 1 for item in values):
        raise argparse.ArgumentTypeError("threads must contain positive integers")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark representative DuckDB analytical SQL workloads.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--sql-dir", type=Path, default=DEFAULT_SQL_DIR)
    parser.add_argument("--threads", type=parse_thread_counts, default=default_thread_counts())
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--explain-dir", type=Path, default=DEFAULT_EXPLAIN_DIR)
    parser.add_argument("--no-explain", action="store_true")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use 1-2 threads, two repetitions, no warm-up and skip EXPLAIN ANALYZE.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    threads = args.threads
    repetitions = args.repetitions
    warmups = args.warmups
    capture_explain = not args.no_explain
    if args.quick:
        threads = [value for value in (1, 2) if value <= (os.cpu_count() or 1)] or [1]
        repetitions = 2
        warmups = 0
        capture_explain = False

    json_output = args.json_output or (
        Path(__file__).resolve().parent / "results" / "quick.json"
        if args.quick
        else DEFAULT_JSON_OUTPUT
    )
    markdown_output = args.markdown_output or (
        Path(__file__).resolve().parent / "results" / "quick.md"
        if args.quick
        else DEFAULT_MARKDOWN_OUTPUT
    )

    report, plans = run_benchmark(
        database_path=args.database.resolve(),
        sql_dir=args.sql_dir.resolve(),
        thread_counts=threads,
        repetitions=repetitions,
        warmups=warmups,
        capture_explain=capture_explain,
    )
    write_outputs(
        report,
        plans,
        json_output.resolve(),
        markdown_output.resolve(),
        args.explain_dir.resolve(),
    )
    print(f"Wrote {json_output} and {markdown_output}")
    print(
        f"Verified {len(QUERY_SPECS)} queries across {len(threads)} thread settings "
        "with matching result checksums."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
