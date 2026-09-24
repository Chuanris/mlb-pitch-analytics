"""Build a compact, versionable MLB source-to-target reconciliation manifest."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import duckdb

from src.common import load_config, project_path
from src.reconcile_mlb_source import (
    SourceUnavailableError,
    fetch_json as fetch_official_json,
    reconcile_date,
    write_output,
)


def _utc_instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _date_sequence(start_date: date, end_date: date) -> list[date]:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    return [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]


def _local_layer_metrics(connection, day: date) -> dict:
    raw = connection.execute("""
        SELECT
            COUNT(DISTINCT game_pk),
            COUNT(*),
            COUNT(*) FILTER (
                WHERE description NOT IN ('automatic_ball', 'automatic_strike')
            ),
            COUNT(*) FILTER (WHERE pitch_type IS NULL)
        FROM bronze.raw_statcast
        WHERE game_type = 'R' AND CAST(game_date AS DATE) = ?
    """, [day]).fetchone()
    silver = connection.execute("""
        SELECT COUNT(DISTINCT game_pk), COUNT(*)
        FROM silver.fact_pitch
        WHERE CAST(game_date AS DATE) = ?
    """, [day]).fetchone()
    return {
        "raw_games": int(raw[0]),
        "raw_regular_season_rows": int(raw[1]),
        "raw_pitch_proxy_rows": int(raw[2]),
        "raw_null_pitch_type_rows": int(raw[3]),
        "silver_pitch_games": int(silver[0]),
        "silver_pitch_rows": int(silver[1]),
    }


def _local_snapshot(connection) -> dict:
    raw = connection.execute("""
        SELECT MIN(CAST(game_date AS DATE)), MAX(CAST(game_date AS DATE)), COUNT(*)
        FROM bronze.raw_statcast
        WHERE game_type = 'R'
    """).fetchone()
    silver = connection.execute("""
        SELECT MIN(CAST(game_date AS DATE)), MAX(CAST(game_date AS DATE)), COUNT(*)
        FROM silver.fact_pitch
    """).fetchone()
    return {
        "bronze.raw_statcast": {
            "min_game_date": str(raw[0]) if raw[0] is not None else None,
            "max_game_date": str(raw[1]) if raw[1] is not None else None,
            "rows": int(raw[2]),
        },
        "silver.fact_pitch": {
            "min_game_date": str(silver[0]) if silver[0] is not None else None,
            "max_game_date": str(silver[1]) if silver[1] is not None else None,
            "rows": int(silver[2]),
        },
    }


def _reconciliation_failure(day: date, checked_at: datetime, error: Exception) -> dict:
    source_unavailable = isinstance(error, SourceUnavailableError)
    return {
        "checked_at_utc": checked_at.isoformat(),
        "official_date": day.isoformat(),
        "status": "attention" if source_unavailable else "error",
        "assessment": (
            "unknown_source_unavailable"
            if source_unavailable
            else "reconciliation_failure"
        ),
        "metrics": {},
        "mismatches": {},
        "sources": {},
        "detail": f"{type(error).__name__}: {error}",
    }


def build_audit(
    connection,
    start_date: date,
    end_date: date,
    *,
    fetch_json: Callable[[str], dict] = fetch_official_json,
    now: datetime | None = None,
) -> dict:
    """Reconcile an inclusive date range and retain daily failures in one manifest."""
    days = _date_sequence(start_date, end_date)
    checked_at = _utc_instant(now)
    daily_results = []

    for day in days:
        try:
            result = reconcile_date(
                connection,
                day,
                fetch_json=fetch_json,
                now=checked_at,
            )
        except (SourceUnavailableError, duckdb.Error, ValueError) as error:
            result = _reconciliation_failure(day, checked_at, error)

        local_layers = _local_layer_metrics(connection, day)
        metrics = result.get("metrics") or {}
        official_pitch_events = metrics.get("official_pitch_events")
        raw_matches = (
            local_layers["raw_pitch_proxy_rows"] == official_pitch_events
            if official_pitch_events is not None
            else None
        )
        audit_status = result["status"]
        audit_assessment = result["assessment"]
        if audit_status == "pass" and raw_matches is False:
            audit_status = "error"
            audit_assessment = "raw_pitch_proxy_mismatch"
        daily_results.append({
            "official_date": day.isoformat(),
            "checked_at_utc": result["checked_at_utc"],
            "status": audit_status,
            "assessment": audit_assessment,
            "source_reconciliation": {
                "status": result["status"],
                "assessment": result["assessment"],
            },
            "metrics": metrics,
            "local_layers": local_layers,
            "raw_matches_official_pitch_events": raw_matches,
            "mismatches": result.get("mismatches") or {},
            "sources": result.get("sources") or {},
            **({"detail": result["detail"]} if result.get("detail") else {}),
        })

    status_counts = Counter(row["status"] for row in daily_results)
    if status_counts["error"]:
        status, assessment = "error", "audit_has_errors"
    elif status_counts["attention"]:
        status, assessment = "attention", "audit_incomplete"
    else:
        status, assessment = "pass", "source_reconciled_all_dates"

    def metric_total(name: str) -> int:
        return sum(int(row["metrics"].get(name, 0) or 0) for row in daily_results)

    def layer_total(name: str) -> int:
        return sum(int(row["local_layers"][name]) for row in daily_results)

    official_pitch_events = metric_total("official_pitch_events")
    raw_pitch_rows = layer_total("raw_pitch_proxy_rows")
    silver_pitch_rows = layer_total("silver_pitch_rows")
    summary = {
        "dates_checked": len(daily_results),
        "status_counts": {
            name: status_counts[name] for name in ("pass", "attention", "error")
        },
        "official_final_games": metric_total("official_final_games"),
        "official_plate_appearances": metric_total("official_plate_appearances"),
        "official_pitch_plate_appearances": metric_total(
            "official_pitch_plate_appearances"
        ),
        "official_pitch_events": official_pitch_events,
        "raw_pitch_proxy_rows": raw_pitch_rows,
        "silver_pitch_rows": silver_pitch_rows,
        "raw_minus_official_pitch_events": raw_pitch_rows - official_pitch_events,
        "silver_minus_official_pitch_events": (
            silver_pitch_rows - official_pitch_events
        ),
        "raw_matching_dates": sum(
            row["raw_matches_official_pitch_events"] is True
            for row in daily_results
        ),
        "raw_mismatch_dates": sum(
            row["raw_matches_official_pitch_events"] is False
            for row in daily_results
        ),
        "source_reconciled_dates": sum(
            row["source_reconciliation"]["assessment"] == "source_reconciled"
            for row in daily_results
        ),
    }

    return {
        "schema_version": 1,
        "generated_at_utc": checked_at.isoformat(),
        "status": status,
        "assessment": assessment,
        "scope": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "game_type": "regular_season",
            "date_semantics": "MLB officialDate",
        },
        "local_snapshot": _local_snapshot(connection),
        "claim": {
            "establishes": (
                "For each listed date, the manifest records whether local game coverage "
                "and per-plate-appearance pitch counts agreed with the official MLB "
                "schedule and live feeds at check time."
            ),
            "limits": (
                "Count agreement does not prove event-level semantic equivalence, "
                "season-wide completeness, upstream correctness or immutability, or "
                "an independent audit of MLB."
            ),
        },
        "method": {
            "official": (
                "Regular-season Final games from the MLB schedule, then isPitch=true "
                "events grouped by game_pk and at_bat_number from each live feed."
            ),
            "raw_pitch_proxy": (
                "Regular-season bronze.raw_statcast rows with a non-null description "
                "other than automatic_ball or automatic_strike; this operational proxy "
                "has no independent cross-source event identifier."
            ),
            "silver": (
                "silver.fact_pitch rows compared with official feeds by game_pk, "
                "game_date and at_bat_number."
            ),
        },
        "summary": summary,
        "dates": daily_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    database = project_path(config["paths"]["database"])
    with duckdb.connect(str(database), read_only=True) as connection:
        audit = build_audit(connection, args.start_date, args.end_date)

    write_output(project_path(args.output), audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass" else 1 if audit["status"] == "attention" else 2


if __name__ == "__main__":
    raise SystemExit(main())
