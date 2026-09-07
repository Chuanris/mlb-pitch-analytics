from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd

from src.common import load_config, project_path
from src.train_whiff_model import apply_platt_calibrator


@dataclass(frozen=True)
class TargetSpec:
    key: str
    label: str
    source_table: str
    target_column: str
    artifact_prefix: str
    denominator: str
    pitcher_minimum: int
    pitch_type_minimum: int
    higher_is_better: bool


TARGETS = {
    "whiff": TargetSpec(
        key="whiff",
        label="Whiff",
        source_table="gold.training_pitch_whiff",
        target_column="target_whiff",
        artifact_prefix="whiff",
        denominator="swings",
        pitcher_minimum=100,
        pitch_type_minimum=500,
        higher_is_better=True,
    ),
    "hard_hit": TargetSpec(
        key="hard_hit",
        label="Hard hit allowed",
        source_table="gold.training_pitch_hard_hit",
        target_column="target_hard_hit",
        artifact_prefix="hard_hit",
        denominator="batted-ball events",
        pitcher_minimum=50,
        pitch_type_minimum=200,
        higher_is_better=False,
    ),
}

OUTPUT_COLUMNS = [
    "target_key",
    "target",
    "denominator",
    "model",
    "pitch_id",
    "game_pk",
    "game_date",
    "season",
    "pitcher_id",
    "pitcher_name",
    "pitcher_team",
    "batter_id",
    "pitch_type",
    "pitch_name",
    "pitch_family",
    "count_state",
    "release_speed",
    "predicted_probability",
    "actual_event",
    "actual_minus_expected",
]


def load_manifest(model_dir: Path, spec: TargetSpec) -> dict:
    path = model_dir / f"{spec.artifact_prefix}_model_metrics.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_scoring_frame(
    connection: duckdb.DuckDBPyConnection,
    spec: TargetSpec,
    feature_columns: list[str],
    test_start: str,
    test_end: str,
) -> pd.DataFrame:
    metadata_columns = [
        "pitch_id",
        "game_pk",
        "game_date",
        "season",
        "pitcher_id",
        "pitcher_team",
        "batter_id",
        "pitch_type",
        "pitch_family",
        "count_state",
        "release_speed",
        spec.target_column,
    ]
    selected = list(dict.fromkeys(metadata_columns + feature_columns))
    selected_sql = ", ".join(f"training.{column}" for column in selected)
    query = f"""
        SELECT
            {selected_sql},
            fact.pitcher_name,
            COALESCE(fact.pitch_name, training.pitch_type) AS pitch_name
        FROM {spec.source_table} AS training
        LEFT JOIN silver.fact_pitch AS fact USING (pitch_id)
        WHERE training.game_date BETWEEN ? AND ?
        ORDER BY training.game_date, training.game_pk, training.pitch_id
    """
    return connection.execute(query, [test_start, test_end]).fetchdf()


def score_target(
    connection: duckdb.DuckDBPyConnection,
    model_dir: Path,
    spec: TargetSpec,
    recent_through: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    manifest = load_manifest(model_dir, spec)
    base_model = manifest.get("champion_base_model", manifest["champion"])
    artifact = joblib.load(model_dir / f"{spec.artifact_prefix}_{base_model}.joblib")
    features = artifact["features"]
    split = manifest["split"]
    start, end = split["test_start"], split["test_end"]
    if recent_through is not None:
        # Two 30-day windows support current/previous Fantasy comparisons. Never
        # score validation observations as independent recent monitoring data.
        end = recent_through
        start = max(start, (pd.Timestamp(end) - pd.Timedelta(days=59)).date().isoformat())
    frame = load_scoring_frame(
        connection,
        spec,
        features,
        start,
        end,
    )
    predicted = artifact["pipeline"].predict_proba(frame[features])[:, 1]
    if spec.key == "whiff" and manifest.get("probability_calibration", {}).get("accepted"):
        calibration_artifact = joblib.load(model_dir / "whiff_probability_calibrator.joblib")
        predicted = apply_platt_calibrator(calibration_artifact["calibrator"], predicted)

    scored = frame[
        [
            "pitch_id",
            "game_pk",
            "game_date",
            "season",
            "pitcher_id",
            "pitcher_name",
            "pitcher_team",
            "batter_id",
            "pitch_type",
            "pitch_name",
            "pitch_family",
            "count_state",
            "release_speed",
        ]
    ].copy()
    scored.insert(0, "model", manifest["champion"])
    scored.insert(0, "denominator", spec.denominator)
    scored.insert(0, "target", spec.label)
    scored.insert(0, "target_key", spec.key)
    scored["predicted_probability"] = np.clip(predicted, 1e-6, 1 - 1e-6)
    scored["actual_event"] = frame[spec.target_column].astype(int)
    scored["actual_minus_expected"] = (
        scored["actual_event"] - scored["predicted_probability"]
    )
    scored["pitcher_name"] = scored["pitcher_name"].fillna(
        scored["pitcher_id"].map(lambda value: f"Pitcher {value}")
    )
    scored["pitch_name"] = scored["pitch_name"].fillna(scored["pitch_type"])
    return scored[OUTPUT_COLUMNS], manifest


def most_common_value(values: pd.Series) -> str | None:
    usable = values.dropna().astype(str)
    if usable.empty:
        return None
    return usable.value_counts().index[0]


def leaderboard_rows(
    scored: pd.DataFrame,
    spec: TargetSpec,
    entity_type: str,
    minimum_sample: int,
) -> pd.DataFrame:
    if entity_type == "Pitcher":
        group_columns = ["pitcher_id", "pitcher_name"]
        label_column = "pitcher_name"
    elif entity_type == "Pitch type":
        group_columns = ["pitch_type", "pitch_name"]
        label_column = "pitch_name"
    else:
        raise ValueError(f"Unsupported leaderboard entity: {entity_type}")

    grouped = (
        scored.groupby(group_columns, dropna=False)
        .agg(
            sample_size=("actual_event", "size"),
            predicted_rate=("predicted_probability", "mean"),
            observed_rate=("actual_event", "mean"),
            avg_release_speed=("release_speed", "mean"),
            first_game_date=("game_date", "min"),
            last_game_date=("game_date", "max"),
            pitcher_count=("pitcher_id", "nunique"),
            team=("pitcher_team", most_common_value),
        )
        .reset_index()
    )
    grouped = grouped[grouped["sample_size"] >= minimum_sample].copy()
    overall = float(scored["predicted_probability"].mean())
    grouped["actual_minus_expected_pp"] = (
        grouped["observed_rate"] - grouped["predicted_rate"]
    ) * 100.0
    direction = 1.0 if spec.higher_is_better else -1.0
    grouped["model_edge_pp"] = direction * (
        grouped["predicted_rate"] - overall
    ) * 100.0
    grouped = grouped.sort_values(
        ["model_edge_pp", "sample_size"], ascending=[False, False]
    ).reset_index(drop=True)
    grouped["rank"] = np.arange(1, len(grouped) + 1)
    grouped.insert(0, "entity_label", grouped[label_column])
    grouped.insert(0, "entity_type", entity_type)
    grouped.insert(0, "target", spec.label)
    grouped.insert(0, "target_key", spec.key)
    grouped["denominator"] = spec.denominator
    grouped["minimum_sample"] = minimum_sample
    grouped["overall_predicted_rate"] = overall
    grouped["performance_direction"] = (
        "Higher expected whiff is better"
        if spec.higher_is_better
        else "Lower expected hard-hit allowed is better"
    )
    if entity_type == "Pitcher":
        pitch_counts = (
            scored.groupby(["pitcher_id", "pitch_name"], dropna=False)
            .size()
            .rename("rows")
            .reset_index()
            .sort_values(["pitcher_id", "rows", "pitch_name"], ascending=[True, False, True])
            .drop_duplicates("pitcher_id")
            .rename(columns={"pitch_name": "primary_pitch"})
        )
        grouped = grouped.merge(
            pitch_counts[["pitcher_id", "primary_pitch"]], on="pitcher_id", how="left"
        )
    else:
        grouped["primary_pitch"] = grouped["pitch_name"]
        grouped["team"] = None
    return grouped[
        [
            "target_key",
            "target",
            "entity_type",
            "entity_label",
            "rank",
            "team",
            "primary_pitch",
            "sample_size",
            "denominator",
            "predicted_rate",
            "observed_rate",
            "actual_minus_expected_pp",
            "model_edge_pp",
            "overall_predicted_rate",
            "avg_release_speed",
            "pitcher_count",
            "minimum_sample",
            "performance_direction",
            "first_game_date",
            "last_game_date",
        ]
    ]


def build_leaderboards(scored_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for target_key, scored in scored_frames.items():
        spec = TARGETS[target_key]
        rows.append(
            leaderboard_rows(scored, spec, "Pitcher", spec.pitcher_minimum)
        )
        rows.append(
            leaderboard_rows(scored, spec, "Pitch type", spec.pitch_type_minimum)
        )
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score untouched-test pitches with the validation-selected champion models."
    )
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--recent-only", action="store_true", help="Reuse the frozen model release and benchmark; refresh recent scores only.")
    parser.add_argument(
        "--target", choices=["all", *TARGETS], default="all",
        help="Target to score; defaults to both whiff and hard-hit models.",
    )
    args = parser.parse_args()
    if args.recent_only and args.target != "all":
        parser.error("--recent-only requires --target all")

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    model_dir = outputs_dir / "models"
    prediction_dir = outputs_dir / "predictions"
    prediction_dir.mkdir(parents=True, exist_ok=True)
    requested = list(TARGETS) if args.target == "all" else [args.target]
    release = None
    if args.recent_only:
        from src.model_release import verify_release
        release = verify_release(config)

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        scored_frames = {} if args.recent_only else {
            target_key: score_target(connection, model_dir, TARGETS[target_key])[0]
            for target_key in requested
        }
        data_through = str(connection.execute("SELECT MAX(game_date) FROM silver.fact_pitch").fetchone()[0])
        recent_frames = {
            key: score_target(connection, model_dir, TARGETS[key], recent_through=data_through)[0]
            for key in requested
        }
    finally:
        connection.close()

    for target_key, scored in scored_frames.items():
        scored.to_parquet(
            prediction_dir / f"{target_key}_test_predictions.parquet", index=False
        )
    for target_key in requested:
        recent_frames[target_key].to_parquet(
            prediction_dir / f"{target_key}_recent_predictions.parquet", index=False
        )

    if args.recent_only:
        leaderboards = None
    elif set(scored_frames) == set(TARGETS):
        leaderboards = build_leaderboards(scored_frames)
        leaderboards.to_csv(prediction_dir / "model_leaderboards.csv", index=False)
    else:
        leaderboards = pd.concat(
            [
                leaderboard_rows(
                    scored_frames[key], TARGETS[key], "Pitcher", TARGETS[key].pitcher_minimum
                )
                for key in requested
            ],
            ignore_index=True,
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "untouched chronological test windows",
        "recent_monitoring": {
            "scope": "post-release scores for the latest 60 calendar days, after validation only; separate from benchmark metrics",
            "data_through": data_through,
            "rows": {key: len(frame) for key, frame in recent_frames.items()},
        },
        "targets": release["benchmark_targets"] if release else {
            key: {
                "rows": int(len(scored)),
                "start": scored["game_date"].min().date().isoformat(),
                "end": scored["game_date"].max().date().isoformat(),
                "model": scored["model"].iloc[0],
                "denominator": TARGETS[key].denominator,
            }
            for key, scored in scored_frames.items()
        },
        "leaderboard_rows": release["leaderboard_rows"] if release else int(len(leaderboards)),
        "workflow": "daily" if args.recent_only else "retrain",
        "model_training_dataset": release["dataset"] if release else None,
    }
    (prediction_dir / "prediction_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    details = ", ".join(
        f"{key}={len(scored):,}" for key, scored in recent_frames.items()
    )
    print(f"Recent scored pitches: {details}; benchmark leaderboard rows={manifest['leaderboard_rows']:,}")
    print(f"Artifacts: {prediction_dir}")


if __name__ == "__main__":
    from src.artifact_lineage import run_versioned
    run_versioned("score_pitch_models", main)
