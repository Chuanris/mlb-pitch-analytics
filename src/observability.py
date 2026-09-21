"""Persist local quality observations before returning a pipeline gate status."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import duckdb

from src.common import load_config, project_path, resolved_mode_ranges


def quality_results(connection, checks):
    results = []
    for name, sql, expected in checks:
        try:
            value = connection.execute(sql).fetchone()[0]
            passed = value is not None and bool(value) == expected
            results.append(dict(check_name=name, status="PASS" if passed else "FAIL",
                                observed=str(value), expected=str(expected)))
        except duckdb.Error as error:
            results.append(dict(check_name=name, status="FAIL",
                                observed=type(error).__name__, expected=str(expected)))
    return results


def recent_partition_result(connection, policy, now):
    """Compare the latest completed game date with recent completed-date rates."""
    lookback = policy["recent_partition_lookback_dates"]
    minimum_baseline = policy["recent_partition_minimum_baseline_dates"]
    lower = policy["minimum_pitches_per_game_ratio"]
    upper = policy["maximum_pitches_per_game_ratio"]
    instant = now if now.tzinfo is not None and now.utcoffset() is not None else now.replace(tzinfo=timezone.utc)
    los_angeles_today = instant.astimezone(ZoneInfo("America/Los_Angeles")).date()
    rows = connection.execute("""
        WITH candidate_games AS (
            SELECT DISTINCT context.game_pk, context.official_date AS game_date, context.game_status
            FROM silver.fact_game_context AS context
            WHERE context.official_date < ?
              AND EXISTS (
                  SELECT 1
                  FROM metadata.pipeline_ranges AS ranges
                  WHERE context.official_date BETWEEN ranges.start_date AND ranges.end_date
              )
        ), eligible_games AS (
            SELECT DISTINCT game_pk, game_date
            FROM candidate_games
            WHERE game_status IN ('Final', 'Game Over', 'Completed Early')
        ), date_statuses AS (
            SELECT game_date,
                   COUNT(DISTINCT game_pk) FILTER (
                       WHERE game_status IS NULL
                          OR game_status NOT IN ('Final', 'Game Over', 'Completed Early', 'Postponed')
                   ) AS unsettled_games
            FROM candidate_games
            GROUP BY game_date
        ), game_pitches AS (
            SELECT games.game_date,
                   games.game_pk,
                   COUNT(pitches.game_pk) AS pitch_rows
            FROM eligible_games AS games
            LEFT JOIN silver.fact_pitch AS pitches
              ON pitches.game_pk = games.game_pk
             AND pitches.game_date = games.game_date
            GROUP BY games.game_date, games.game_pk
        ), dates AS (
            SELECT game_date,
                   COUNT(*) AS completed_games,
                   COUNT(*) FILTER (WHERE pitch_rows > 0) AS pitch_games,
                   SUM(pitch_rows) AS pitch_rows,
                   MIN(pitch_rows) AS minimum_game_pitch_rows
            FROM game_pitches
            GROUP BY game_date
        )
        SELECT date_statuses.game_date, COALESCE(completed_games, 0),
               COALESCE(pitch_games, 0), COALESCE(pitch_rows, 0),
               minimum_game_pitch_rows, unsettled_games
        FROM date_statuses
        LEFT JOIN dates ON date_statuses.game_date = dates.game_date
        WHERE completed_games > 0 OR unsettled_games > 0
        ORDER BY date_statuses.game_date DESC
        LIMIT ?
    """, [los_angeles_today, lookback + 1]).fetchall()
    if not rows:
        return "bootstrap", dict(eligible_baseline_dates=0), "No completed game dates are available for comparison."

    latest_date, completed_games, pitch_games, pitch_rows, minimum_game_pitch_rows, unsettled_games = rows[0]
    latest_rate = pitch_rows / completed_games if completed_games else None
    eligible_baseline_rates = [
        row[3] / row[1]
        for row in rows[1:]
        if row[1] > 0 and row[2] == row[1] and row[5] == 0
    ]
    detail = dict(
        latest_evaluated_date=str(latest_date),
        latest_completed_date=str(latest_date) if completed_games else None,
        completed_games=completed_games,
        pitch_games=pitch_games,
        pitch_rows=pitch_rows,
        minimum_game_pitch_rows=minimum_game_pitch_rows,
        pitches_per_completed_game=latest_rate,
        game_coverage_ratio=pitch_games / completed_games if completed_games else None,
        unsettled_games=unsettled_games,
        eligible_baseline_dates=len(eligible_baseline_rates),
    )
    if pitch_games != completed_games:
        return "error", detail, "Inspect completed games with no same-date pitch rows before establishing a baseline."
    if unsettled_games:
        detail["assessment"] = "unknown_unsettled_date"
        return "attention", detail, "Wait for active or unknown game statuses to settle before assessing the date."
    if len(eligible_baseline_rates) < minimum_baseline:
        detail["assessment"] = "unknown_insufficient_baseline"
        return "attention", detail, "Not enough prior completed dates to establish a recent-partition baseline."

    baseline_median = statistics.median(eligible_baseline_rates)
    ratio = latest_rate / baseline_median if baseline_median else None
    minimum_game_ratio = minimum_game_pitch_rows / baseline_median if baseline_median else None
    detail.update(baseline_median_pitches_per_game=baseline_median, ratio=ratio,
                  minimum_game_ratio=minimum_game_ratio)
    passed = (ratio is not None and minimum_game_ratio is not None
              and lower <= ratio <= upper and minimum_game_ratio >= lower)
    if passed:
        return "pass", detail, ""
    detail["assessment"] = "volume_anomaly"
    return "attention", detail, "Review source and load reconciliation; pitch-volume bounds flag an anomaly but do not prove incompleteness."


def observe(config, policy, *, checks=(), now=None, history_path=None):
    """Read DuckDB, compare successful baselines, persist even failed observations."""
    now = now or datetime.now(timezone.utc)
    grace = policy["freshness_grace_days"]
    lower, upper = policy["minimum_row_ratio"], policy["maximum_row_ratio"]
    partition_lookback = policy["recent_partition_lookback_dates"]
    partition_minimum = policy["recent_partition_minimum_baseline_dates"]
    partition_lower = policy["minimum_pitches_per_game_ratio"]
    partition_upper = policy["maximum_pitches_per_game_ratio"]
    if (not isinstance(grace, int) or grace < 0 or not 0 < lower <= 1 <= upper
            or not isinstance(partition_lookback, int) or partition_lookback < 1
            or not isinstance(partition_minimum, int) or not 1 <= partition_minimum <= partition_lookback
            or not 0 < partition_lower <= 1 <= partition_upper):
        raise ValueError("Invalid freshness, volume or recent-partition policy")
    directory = project_path(config["paths"]["outputs_dir"]) / "observability"
    history_path = history_path or directory / "history.sqlite"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(run_id=str(uuid4()), checked_at_utc=now.isoformat(),
                  policy=policy, checks=[], quality_checks=[], metrics={})

    def add(name, status, detail, action=""):
        report["checks"].append(dict(check=name, status=status, detail=detail, action=action))

    # Scope includes path, configured ranges and policy; new scope starts a new baseline.
    scope = dict(database=str(project_path(config["paths"]["database"]).resolve()),
                 sample=config.get("sample"), full=config.get("full"), policy=policy)
    key = None
    with closing(sqlite3.connect(history_path, timeout=30)) as history, history:
        history.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, scope TEXT, status TEXT NOT NULL, payload TEXT NOT NULL)")
        history.execute("CREATE INDEX IF NOT EXISTS observations_scope ON observations(scope, status, id)")
        # Serialize baseline selection and append, including concurrent standalone runs.
        history.execute("BEGIN IMMEDIATE")
        try:
            with duckdb.connect(str(project_path(config["paths"]["database"])), read_only=True) as connection:
                mode = connection.execute("SELECT mode FROM metadata.dataset_version").fetchone()[0]
                scope["mode"] = mode
                key = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
                first = history.execute("SELECT payload FROM observations WHERE scope=? AND status='pass' ORDER BY id LIMIT 1", [key]).fetchone()
                previous = history.execute("SELECT payload FROM observations WHERE scope=? AND status='pass' ORDER BY id DESC LIMIT 1", [key]).fetchone()
                schema = connection.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='silver' AND table_name='fact_pitch' ORDER BY ordinal_position").fetchall()
                schema = [list(row) for row in schema]
                report["schema"] = schema
                if first:
                    baseline = json.loads(first[0])
                    same = schema == baseline["schema"]
                    add("schema_drift", "pass" if same else "error",
                        dict(baseline_run=baseline["run_id"], expected=baseline["schema"], observed=schema),
                        "Inspect the migration and downstream consumers; restore the schema or use a reviewed new history scope." if not same else "")
                else:
                    add("schema_drift", "bootstrap", "No successful baseline; first successful observation establishes it.")
                count, latest = connection.execute("SELECT COUNT(*), MAX(game_date) FROM silver.fact_pitch").fetchone()
                expected = max(r["end_date"] for r in resolved_mode_ranges(config, mode, today=now.date()))
                lag = (expected - latest).days if latest else None
                report["metrics"] = dict(mode=mode, rows=count, data_through=str(latest) if latest else None,
                                         expected_through=str(expected), lag_days=lag)
                invalid = latest is None or latest > now.date() or count == 0
                add("freshness", "error" if invalid else "attention" if lag > grace else "pass",
                    dict(report["metrics"]), "Check configured dates and the MLB calendar before refreshing; this is a calendar-age SLA.")
                if previous:
                    baseline = json.loads(previous[0])
                    ratio = count / baseline["metrics"]["rows"]
                    add("row_volume", "pass" if lower <= ratio <= upper else "error",
                        dict(ratio=ratio, previous_rows=baseline["metrics"]["rows"], rows=count,
                             baseline_run=baseline["run_id"]),
                        "Check truncated extraction, duplicate loading and intentional backfills before changing bounds.")
                else:
                    add("row_volume", "bootstrap", "No successful baseline; volume change cannot yet be assessed.")
                partition_status, partition_detail, partition_action = recent_partition_result(connection, policy, now)
                report["metrics"]["recent_partition"] = partition_detail
                add("recent_partition_completeness", partition_status, partition_detail, partition_action)
                report["quality_checks"] = quality_results(connection, checks)
                failures = [r["check_name"] for r in report["quality_checks"] if r["status"] == "FAIL"]
                add("data_quality", "error" if failures else "pass" if checks else "bootstrap",
                    dict(executed=len(checks), failed=failures), "Inspect the named SQL quality checks.")
        except (duckdb.Error, OSError, ValueError, KeyError, TypeError, IndexError) as error:
            add("collection", "error", type(error).__name__, "Inspect database availability, required tables and configuration.")
        statuses = {c["status"] for c in report["checks"]}
        report["status"] = "error" if "error" in statuses else "attention" if "attention" in statuses else "pass"
        report["exit_code"] = {"pass": 0, "attention": 1, "error": 2}[report["status"]]
        report["alerts"] = [c for c in report["checks"] if c["status"] in {"attention", "error"}]
        history.execute("INSERT INTO observations(scope,status,payload) VALUES (?,?,?)",
                        [key, report["status"], json.dumps(report)])
    directory.mkdir(parents=True, exist_ok=True)
    # Unique files preserve failures and retries; latest is an atomic convenience pointer.
    destination = directory / (report["run_id"] + ".json")
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary = directory / (report["run_id"] + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(directory / "latest.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--policy", default="config/observability.json")
    args = parser.parse_args()
    from src.validate_data import CHECKS
    report = observe(load_config(args.config), load_config(args.policy), checks=CHECKS)
    print(json.dumps(report, indent=2))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
