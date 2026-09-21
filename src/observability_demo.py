"""Run a credential-free demonstration of the recent-partition contract."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from src.observability import recent_partition_result


POLICY = {
    "recent_partition_lookback_dates": 14,
    "recent_partition_minimum_baseline_dates": 1,
    "minimum_pitches_per_game_ratio": 0.65,
    "maximum_pitches_per_game_ratio": 1.35,
}


def _pitches(game_pk: int, game_date: str, count: int) -> list[tuple[str, int, str]]:
    return [
        (f"{game_pk}:{pitch_number}", game_pk, game_date)
        for pitch_number in range(1, count + 1)
    ]


def _evaluate(games, pitches):
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE SCHEMA metadata; CREATE SCHEMA silver")
        connection.execute("""
            CREATE TABLE metadata.pipeline_ranges (
                start_date DATE,
                end_date DATE
            )
        """)
        connection.execute(
            "INSERT INTO metadata.pipeline_ranges VALUES (DATE '2025-04-01', DATE '2025-04-02')"
        )
        connection.execute("""
            CREATE TABLE silver.fact_game_context (
                game_pk BIGINT,
                official_date DATE,
                game_status VARCHAR
            )
        """)
        connection.execute("""
            CREATE TABLE silver.fact_pitch (
                pitch_id VARCHAR,
                game_pk BIGINT,
                game_date DATE
            )
        """)
        connection.executemany(
            "INSERT INTO silver.fact_game_context VALUES (?, CAST(? AS DATE), ?)",
            games,
        )
        connection.executemany(
            "INSERT INTO silver.fact_pitch VALUES (?, ?, CAST(? AS DATE))",
            pitches,
        )
        return recent_partition_result(
            connection,
            POLICY,
            datetime(2025, 4, 10, tzinfo=timezone.utc),
        )


def run_demo() -> dict:
    """Return three deterministic outcomes without reading or writing project data."""
    baseline_game = (1001, "2025-04-01", "Final")
    completed_game = (2001, "2025-04-02", "Final")
    active_game = (2002, "2025-04-02", "In Progress")
    baseline_pitches = _pitches(1001, "2025-04-01", 300)
    completed_pitches = _pitches(2001, "2025-04-02", 300)
    active_pitches = _pitches(2002, "2025-04-02", 50)
    fixtures = [
        (
            "healthy_complete_date",
            "pass",
            [baseline_game, completed_game],
            baseline_pitches + completed_pitches,
        ),
        (
            "unsettled_date",
            "attention",
            [baseline_game, completed_game, active_game],
            baseline_pitches + completed_pitches + active_pitches,
        ),
        (
            "missing_same_date_coverage",
            "error",
            [baseline_game, completed_game, active_game],
            baseline_pitches + active_pitches,
        ),
    ]
    scenarios = []
    for name, expected_status, games, pitches in fixtures:
        status, detail, action = _evaluate(games, pitches)
        scenarios.append({
            "scenario": name,
            "expected_status": expected_status,
            "status": status,
            "assessment": detail.get("assessment"),
            "completed_games": detail.get("completed_games"),
            "pitch_games": detail.get("pitch_games"),
            "unsettled_games": detail.get("unsettled_games"),
            "ratio": detail.get("ratio"),
            "action": action,
        })
    return {
        "contract": "recent_partition_local_evidence_not_source_completeness",
        "verified": all(
            item["status"] == item["expected_status"]
            for item in scenarios
        ),
        "scenarios": scenarios,
    }


def main() -> int:
    result = run_demo()
    print(json.dumps(result, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
