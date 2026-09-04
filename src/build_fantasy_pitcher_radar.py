from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.common import load_config, project_path


WINDOW_MINIMUMS = {
    7: {"pitches": 50, "batters_faced": 10, "expected_swings": 10, "expected_batted_balls": 5},
    14: {"pitches": 80, "batters_faced": 18, "expected_swings": 18, "expected_batted_balls": 8},
    30: {"pitches": 150, "batters_faced": 35, "expected_swings": 35, "expected_batted_balls": 15},
}

PROFILE_WEIGHTS = {
    "roto_balance": {
        "label": "Roto balance",
        "expected_whiff_percentile": 0.25,
        "expected_hard_hit_suppression_percentile": 0.25,
        "k_minus_bb_percentile": 0.25,
        "chase_percentile": 0.15,
        "walk_suppression_percentile": 0.10,
    },
    "strikeout_upside": {
        "label": "Strikeout upside",
        "expected_whiff_percentile": 0.40,
        "expected_hard_hit_suppression_percentile": 0.05,
        "k_minus_bb_percentile": 0.30,
        "chase_percentile": 0.20,
        "walk_suppression_percentile": 0.05,
    },
    "ratio_protection": {
        "label": "Ratio protection",
        "expected_whiff_percentile": 0.15,
        "expected_hard_hit_suppression_percentile": 0.35,
        "k_minus_bb_percentile": 0.20,
        "chase_percentile": 0.10,
        "walk_suppression_percentile": 0.20,
    },
}


def safe_rate(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator > 0))


def load_predictions(prediction_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for target_key in ("whiff", "hard_hit"):
        frame = pd.read_parquet(prediction_dir / f"{target_key}_test_predictions.parquet")
        frame["game_date"] = pd.to_datetime(frame["game_date"])
        frames[target_key] = frame
    return frames


def period_pitcher_metrics(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    query = """
        SELECT
            pitcher_id,
            ARG_MAX(pitcher_name, game_date) AS pitcher_name,
            ARG_MAX(pitcher_team, game_date) AS pitcher_team,
            COUNT(DISTINCT game_pk)::BIGINT AS games,
            COUNT(*)::BIGINT AS pitches,
            COUNT(plate_appearance_event) FILTER (
                WHERE plate_appearance_event <> 'truncated_pa'
            )::BIGINT AS batters_faced,
            SUM(CASE WHEN plate_appearance_event IN ('strikeout', 'strikeout_double_play') THEN 1 ELSE 0 END)::BIGINT AS strikeouts,
            SUM(CASE WHEN plate_appearance_event = 'walk' THEN 1 ELSE 0 END)::BIGINT AS walks,
            SUM(CASE WHEN plate_appearance_event IN ('single', 'double', 'triple', 'home_run') THEN 1 ELSE 0 END)::BIGINT AS hits_allowed,
            SUM(CASE WHEN plate_appearance_event = 'home_run' THEN 1 ELSE 0 END)::BIGINT AS home_runs_allowed,
            SUM(swing_flag)::BIGINT AS swings,
            SUM(whiff_flag)::BIGINT AS whiffs,
            SUM(chase_flag)::BIGINT AS chases,
            SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END)::BIGINT AS out_of_zone_pitches,
            SUM(batted_ball_flag)::BIGINT AS batted_balls,
            SUM(hard_hit_flag)::BIGINT AS hard_hits,
            AVG(release_speed) AS avg_velocity,
            MIN(game_date) AS first_game_date,
            MAX(game_date) AS last_game_date
        FROM silver.fact_pitch
        WHERE game_date BETWEEN ? AND ?
        GROUP BY pitcher_id
    """
    return connection.execute(query, [start_date, end_date]).fetchdf()


def period_expected_metrics(
    predictions: dict[str, pd.DataFrame],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    whiff = predictions["whiff"]
    whiff = whiff[whiff["game_date"].between(start, end)]
    whiff = (
        whiff.groupby("pitcher_id")
        .agg(
            expected_swings=("predicted_probability", "size"),
            expected_whiff_rate=("predicted_probability", "mean"),
        )
        .reset_index()
    )
    hard_hit = predictions["hard_hit"]
    hard_hit = hard_hit[hard_hit["game_date"].between(start, end)]
    hard_hit = (
        hard_hit.groupby("pitcher_id")
        .agg(
            expected_batted_balls=("predicted_probability", "size"),
            expected_hard_hit_rate=("predicted_probability", "mean"),
        )
        .reset_index()
    )
    return whiff.merge(hard_hit, on="pitcher_id", how="outer")


def qualify_and_score(
    metrics: pd.DataFrame,
    expected: pd.DataFrame,
    window_days: int,
) -> pd.DataFrame:
    frame = metrics.merge(expected, on="pitcher_id", how="left")
    minimums = WINDOW_MINIMUMS[window_days]
    frame = frame[
        (frame["pitches"] >= minimums["pitches"])
        & (frame["batters_faced"] >= minimums["batters_faced"])
        & (frame["expected_swings"] >= minimums["expected_swings"])
        & (frame["expected_batted_balls"] >= minimums["expected_batted_balls"])
    ].copy()

    frame["strikeout_rate"] = safe_rate(frame["strikeouts"], frame["batters_faced"])
    frame["walk_rate"] = safe_rate(frame["walks"], frame["batters_faced"])
    frame["k_minus_bb_rate"] = frame["strikeout_rate"] - frame["walk_rate"]
    frame["whiff_rate"] = safe_rate(frame["whiffs"], frame["swings"])
    frame["chase_rate"] = safe_rate(frame["chases"], frame["out_of_zone_pitches"])
    frame["hard_hit_rate_allowed"] = safe_rate(frame["hard_hits"], frame["batted_balls"])
    frame["traffic_rate"] = safe_rate(
        frame["hits_allowed"] + frame["walks"], frame["batters_faced"]
    )
    frame["pitches_per_game"] = safe_rate(frame["pitches"], frame["games"])
    frame["role_hint"] = np.select(
        [frame["pitches_per_game"] >= 50, frame["pitches_per_game"] >= 30],
        ["Starter workload", "Multi-inning workload"],
        default="Relief workload",
    )

    frame["expected_whiff_percentile"] = frame["expected_whiff_rate"].rank(
        method="average", pct=True
    )
    frame["expected_hard_hit_suppression_percentile"] = frame[
        "expected_hard_hit_rate"
    ].rank(method="average", pct=True, ascending=False)
    frame["k_minus_bb_percentile"] = frame["k_minus_bb_rate"].rank(
        method="average", pct=True
    )
    frame["chase_percentile"] = frame["chase_rate"].rank(
        method="average", pct=True
    )
    frame["walk_suppression_percentile"] = frame["walk_rate"].rank(
        method="average", pct=True, ascending=False
    )
    return frame


def add_profile_scores(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for profile_key, profile in PROFILE_WEIGHTS.items():
        scored = frame.copy()
        score = pd.Series(0.0, index=scored.index)
        for column, weight in profile.items():
            if column == "label":
                continue
            score = score + scored[column] * float(weight)
        scored["profile_key"] = profile_key
        scored["profile"] = profile["label"]
        scored["fantasy_signal"] = (100.0 * score).round(1)
        rows.append(scored)
    return pd.concat(rows, ignore_index=True)


def decision_label(score: float, change: float | None) -> str:
    if score >= 80 and change is not None and change >= 5:
        return "High-skill, rising"
    if score >= 80:
        return "High-skill"
    if score >= 65 and change is not None and change >= 5:
        return "Trending stream"
    if score >= 65:
        return "Streaming watch"
    return "Monitor"


def trend_status(change: float | None) -> str:
    if change is None:
        return "Newly qualified"
    if change >= 5:
        return "Rising"
    if change <= -5:
        return "Cooling"
    return "Stable"


def research_action(
    score: float,
    change: float | None,
    role_hint: str,
    underlying_skill_gap_pp: float,
) -> str:
    if score >= 80 and change is not None and change >= 5:
        return "Check availability"
    if score >= 80:
        return "Roster fit review"
    if role_hint == "Starter workload" and score >= 65:
        return "Streaming review"
    if score >= 60 and underlying_skill_gap_pp >= 3:
        return "Buy-low review"
    return "Monitor"


def build_window_rows(
    connection: duckdb.DuckDBPyConnection,
    predictions: dict[str, pd.DataFrame],
    data_through: date,
    window_days: int,
) -> pd.DataFrame:
    current_start = data_through - timedelta(days=window_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=window_days - 1)

    current = qualify_and_score(
        period_pitcher_metrics(connection, current_start, data_through),
        period_expected_metrics(predictions, current_start, data_through),
        window_days,
    )
    previous = qualify_and_score(
        period_pitcher_metrics(connection, previous_start, previous_end),
        period_expected_metrics(predictions, previous_start, previous_end),
        window_days,
    )
    current = add_profile_scores(current)
    previous = add_profile_scores(previous)[
        ["pitcher_id", "profile_key", "fantasy_signal"]
    ].rename(columns={"fantasy_signal": "previous_signal"})
    current = current.merge(previous, on=["pitcher_id", "profile_key"], how="left")
    current["signal_change"] = current["fantasy_signal"] - current["previous_signal"]
    current["expected_whiff_gap_pp"] = 100.0 * (
        current["expected_whiff_rate"] - current["whiff_rate"]
    )
    current["expected_hard_hit_suppression_gap_pp"] = 100.0 * (
        current["hard_hit_rate_allowed"] - current["expected_hard_hit_rate"]
    )
    current["underlying_skill_gap_pp"] = 0.5 * (
        current["expected_whiff_gap_pp"]
        + current["expected_hard_hit_suppression_gap_pp"]
    )
    minimums = WINDOW_MINIMUMS[window_days]
    current["sample_strength_multiple"] = pd.concat(
        [
            current["pitches"] / minimums["pitches"],
            current["batters_faced"] / minimums["batters_faced"],
            current["expected_swings"] / minimums["expected_swings"],
            current["expected_batted_balls"] / minimums["expected_batted_balls"],
        ],
        axis=1,
    ).min(axis=1)
    current["sample_strength"] = np.select(
        [
            current["sample_strength_multiple"] >= 2.0,
            current["sample_strength_multiple"] >= 1.35,
        ],
        ["Established sample", "Solid sample"],
        default="Qualified sample",
    )
    current["rank"] = current.groupby("profile_key")["fantasy_signal"].rank(
        method="first", ascending=False
    ).astype(int)
    normalized_changes = [
        None if pd.isna(change) else float(change) for change in current["signal_change"]
    ]
    current["trend_status"] = [trend_status(change) for change in normalized_changes]
    current["decision_label"] = [
        decision_label(score, change)
        for score, change in zip(current["fantasy_signal"], normalized_changes)
    ]
    current["research_action"] = [
        research_action(score, change, role_hint, skill_gap)
        for score, change, role_hint, skill_gap in zip(
            current["fantasy_signal"],
            normalized_changes,
            current["role_hint"],
            current["underlying_skill_gap_pp"],
        )
    ]
    current["window_days"] = window_days
    current["window_label"] = f"Last {window_days} days"
    current["window_start"] = current_start
    current["window_end"] = data_through
    current["previous_window_start"] = previous_start
    current["previous_window_end"] = previous_end
    current["minimum_pitches"] = WINDOW_MINIMUMS[window_days]["pitches"]
    return current.sort_values(["profile_key", "rank"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build recent-form fantasy pitching decision-support rankings."
    )
    parser.add_argument("--config", default="config/pipeline_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    prediction_dir = outputs_dir / "predictions"
    fantasy_dir = outputs_dir / "fantasy"
    fantasy_dir.mkdir(parents=True, exist_ok=True)
    predictions = load_predictions(prediction_dir)

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        data_through = connection.execute(
            "SELECT MAX(game_date) FROM silver.fact_pitch"
        ).fetchone()[0]
        windows = [
            build_window_rows(connection, predictions, data_through, window_days)
            for window_days in (7, 14, 30)
        ]
    finally:
        connection.close()

    frame = pd.concat(windows, ignore_index=True)
    frame.to_csv(fantasy_dir / "pitcher_fantasy_radar.csv", index=False)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_through": data_through.isoformat(),
        "population": "MLB pitchers meeting target-specific recent workload and model-score minimums",
        "purpose": "skills-based fantasy pitching decision support; not projected fantasy points",
        "profiles": PROFILE_WEIGHTS,
        "window_minimums": WINDOW_MINIMUMS,
        "rows": int(len(frame)),
        "limitations": [
            "Does not include roster availability, probable starts, opponent schedules, wins, saves, earned runs, or innings-pitched scoring.",
            "Role hint is inferred from recent pitches per game and is not an official roster designation.",
            "Whiff expectation is conditional on swings and hard-hit expectation is conditional on batted-ball events.",
            "Research actions are deterministic review prompts, not transaction, start/sit, or outcome guarantees.",
            "The underlying skill gap averages two conditional expected-versus-observed rate gaps and should be treated as a research flag, not a calibrated regression forecast.",
        ],
    }
    (fantasy_dir / "fantasy_radar_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Fantasy pitcher radar: {len(frame):,} rows through {data_through} -> {fantasy_dir}"
    )


if __name__ == "__main__":
    main()
