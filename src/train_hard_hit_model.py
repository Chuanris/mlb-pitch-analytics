from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import duckdb
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from src.common import load_config, project_path
from src.train_whiff_model import (
    BASE_CATEGORICAL_FEATURES,
    BASE_NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    FORBIDDEN_LEAKAGE_COLUMNS,
    IDENTIFIER_COLUMNS,
    NUMERIC_FEATURES,
    TIME_WEATHER_CATEGORICAL_FEATURES,
    TIME_WEATHER_NUMERIC_FEATURES,
    assert_feature_contract,
    build_gradient_pipeline,
    build_logistic_pipeline,
    expected_calibration_error,
    limit_rows,
    make_time_split,
)


TARGET_COLUMN = "target_hard_hit"
SOURCE_TABLE = "gold.training_pitch_hard_hit"
BASELINE_GROUP_COLUMNS = ["pitch_type", "balls", "strikes", "batter_stand"]
HARD_HIT_ROLLING_NUMERIC_FEATURES = [
    "pitcher_batted_balls_prior_200",
    "pitcher_hard_hit_rate_allowed_prior_200_batted_balls",
    "pitcher_batted_balls_prior_30d",
    "pitcher_hard_hit_rate_allowed_prior_30d",
    "batter_batted_balls_prior_50",
    "batter_hard_hit_rate_prior_50_batted_balls",
    "batter_batted_balls_prior_30d",
    "batter_hard_hit_rate_prior_30d",
]
HARD_HIT_RECENT_FORM_NUMERIC_FEATURES = [
    "pitcher_batted_balls_prior_14d",
    "pitcher_hard_hit_rate_allowed_prior_14d",
    "batter_batted_balls_prior_14d",
    "batter_hard_hit_rate_prior_14d",
]
HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES = [
    "pitcher_pitch_type_batted_balls_prior_100",
    "pitcher_pitch_type_hard_hit_rate_allowed_prior_100_batted_balls",
    "pitcher_pitch_type_batted_balls_prior_30d",
    "pitcher_pitch_type_hard_hit_rate_allowed_prior_30d",
    "batter_pitch_type_batted_balls_prior_30",
    "batter_pitch_type_hard_hit_rate_prior_30_batted_balls",
    "batter_pitch_type_batted_balls_prior_30d",
    "batter_pitch_type_hard_hit_rate_prior_30d",
]
HARD_HIT_MATCHUP_NUMERIC_FEATURES = [
    "matchup_batted_balls_prior_20",
    "matchup_hard_hit_rate_prior_20_batted_balls",
]


def fit_baseline(train: pd.DataFrame, smoothing: float = 50.0) -> dict:
    prepared = train.copy()
    for column in BASELINE_GROUP_COLUMNS:
        prepared[column] = prepared[column].fillna("__MISSING__").astype(str)
    global_rate = float(prepared[TARGET_COLUMN].mean())
    grouped = (
        prepared.groupby(BASELINE_GROUP_COLUMNS, dropna=False)[TARGET_COLUMN]
        .agg(["sum", "count"])
        .reset_index()
    )
    grouped["prediction"] = (
        grouped["sum"] + smoothing * global_rate
    ) / (grouped["count"] + smoothing)
    return {
        "global_rate": global_rate,
        "smoothing": smoothing,
        "groups": grouped[BASELINE_GROUP_COLUMNS + ["prediction"]],
    }


def predict_baseline(model: dict, frame: pd.DataFrame) -> np.ndarray:
    prepared = frame[BASELINE_GROUP_COLUMNS].copy()
    for column in BASELINE_GROUP_COLUMNS:
        prepared[column] = prepared[column].fillna("__MISSING__").astype(str)
    merged = prepared.merge(model["groups"], on=BASELINE_GROUP_COLUMNS, how="left")
    return merged["prediction"].fillna(model["global_rate"]).to_numpy(dtype=float)


def evaluate_predictions(
    observed: pd.Series,
    predicted: np.ndarray,
) -> dict[str, float | int]:
    clipped = np.clip(np.asarray(predicted, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(observed, dtype=int)
    return {
        "rows": int(len(y)),
        "hard_hit_rate": float(y.mean()),
        "predicted_hard_hit_rate": float(clipped.mean()),
        "log_loss": float(log_loss(y, clipped, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y, clipped)),
        "roc_auc": float(roc_auc_score(y, clipped)),
        "average_precision": float(average_precision_score(y, clipped)),
        "expected_calibration_error": expected_calibration_error(y, clipped),
    }


def calibration_rows(
    model_name: str,
    split_name: str,
    frame: pd.DataFrame,
    predicted: np.ndarray,
    bins: int = 10,
) -> list[dict]:
    scored = pd.DataFrame(
        {
            "observed": frame[TARGET_COLUMN].to_numpy(dtype=int),
            "predicted": np.asarray(predicted, dtype=float),
        }
    )
    scored["bin"] = pd.cut(
        scored["predicted"],
        bins=np.linspace(0, 1, bins + 1),
        labels=False,
        include_lowest=True,
    )
    summary = (
        scored.groupby("bin", observed=True)
        .agg(
            rows=("observed", "size"),
            observed_rate=("observed", "mean"),
            predicted_rate=("predicted", "mean"),
        )
        .reset_index()
    )
    summary.insert(0, "split", split_name)
    summary.insert(0, "model", model_name)
    return summary.to_dict(orient="records")


def monthly_rows(
    model_name: str,
    split_name: str,
    frame: pd.DataFrame,
    predicted: np.ndarray,
) -> list[dict]:
    scored = pd.DataFrame(
        {
            "month": pd.to_datetime(frame["game_date"]).dt.to_period("M").astype(str),
            "observed": frame[TARGET_COLUMN].to_numpy(dtype=int),
            "predicted": np.asarray(predicted, dtype=float),
        }
    )
    summary = (
        scored.groupby("month")
        .agg(
            rows=("observed", "size"),
            observed_hard_hit_rate=("observed", "mean"),
            predicted_hard_hit_rate=("predicted", "mean"),
        )
        .reset_index()
    )
    summary.insert(0, "split", split_name)
    summary.insert(0, "model", model_name)
    return summary.to_dict(orient="records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and evaluate hard-hit probability conditional on a batted ball."
    )
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--max-rows-per-split", type=int)
    parser.add_argument("--skip-gradient", action="store_true")
    args = parser.parse_args()

    all_numeric_features = (
        NUMERIC_FEATURES
        + HARD_HIT_ROLLING_NUMERIC_FEATURES
        + HARD_HIT_RECENT_FORM_NUMERIC_FEATURES
        + HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
        + HARD_HIT_MATCHUP_NUMERIC_FEATURES
    )
    assert_feature_contract(all_numeric_features + CATEGORICAL_FEATURES)
    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    model_dir = project_path(config["paths"]["outputs_dir"]) / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    selected_columns = IDENTIFIER_COLUMNS + all_numeric_features + CATEGORICAL_FEATURES + [TARGET_COLUMN]
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        available_columns = {
            row[0]
            for row in connection.execute(f"DESCRIBE {SOURCE_TABLE}").fetchall()
        }
        missing = sorted(set(selected_columns) - available_columns)
        if missing:
            raise ValueError(f"Hard-hit training mart is missing required columns: {missing}")
        query = (
            "SELECT "
            + ", ".join(selected_columns)
            + f" FROM {SOURCE_TABLE} ORDER BY game_date, game_pk, pitch_id"
        )
        frame = connection.execute(query).fetchdf()
    finally:
        connection.close()

    split = make_time_split(frame)
    partitions = {
        "train": limit_rows(split.train, args.max_rows_per_split, 52),
        "validation": limit_rows(split.validation, args.max_rows_per_split, 53),
        "test": limit_rows(split.test, args.max_rows_per_split, 54),
    }
    train = partitions["train"]
    baseline = fit_baseline(train)

    model_specs: dict[str, tuple[Pipeline, list[str]]] = {
        "logistic_regression": (
            build_logistic_pipeline(BASE_NUMERIC_FEATURES, BASE_CATEGORICAL_FEATURES),
            BASE_NUMERIC_FEATURES + BASE_CATEGORICAL_FEATURES,
        )
    }
    if not args.skip_gradient:
        model_specs["hist_gradient_boosting_base"] = (
            build_gradient_pipeline(BASE_NUMERIC_FEATURES, BASE_CATEGORICAL_FEATURES),
            BASE_NUMERIC_FEATURES + BASE_CATEGORICAL_FEATURES,
        )
        model_specs["hist_gradient_boosting_time_weather"] = (
            build_gradient_pipeline(NUMERIC_FEATURES, CATEGORICAL_FEATURES),
            NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        )
        rolling_numeric = BASE_NUMERIC_FEATURES + HARD_HIT_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form"] = (
            build_gradient_pipeline(rolling_numeric, BASE_CATEGORICAL_FEATURES),
            rolling_numeric + BASE_CATEGORICAL_FEATURES,
        )
        recent_form_numeric = rolling_numeric + HARD_HIT_RECENT_FORM_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_recent"] = (
            build_gradient_pipeline(recent_form_numeric, BASE_CATEGORICAL_FEATURES),
            recent_form_numeric + BASE_CATEGORICAL_FEATURES,
        )
        rolling_weather_numeric = NUMERIC_FEATURES + HARD_HIT_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_time_weather"] = (
            build_gradient_pipeline(rolling_weather_numeric, CATEGORICAL_FEATURES),
            rolling_weather_numeric + CATEGORICAL_FEATURES,
        )
        pitch_type_numeric = rolling_numeric + HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_pitch_type"] = (
            build_gradient_pipeline(pitch_type_numeric, BASE_CATEGORICAL_FEATURES),
            pitch_type_numeric + BASE_CATEGORICAL_FEATURES,
        )
        model_specs["hist_gradient_boosting_tuned_pitch_type"] = (
            build_gradient_pipeline(
                pitch_type_numeric,
                BASE_CATEGORICAL_FEATURES,
                learning_rate=0.06,
                max_iter=220,
                min_samples_leaf=80,
                l2_regularization=2.0,
            ),
            pitch_type_numeric + BASE_CATEGORICAL_FEATURES,
        )
        recent_pitch_type_numeric = (
            recent_form_numeric + HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
        )
        model_specs["hist_gradient_boosting_rolling_form_recent_pitch_type"] = (
            build_gradient_pipeline(recent_pitch_type_numeric, BASE_CATEGORICAL_FEATURES),
            recent_pitch_type_numeric + BASE_CATEGORICAL_FEATURES,
        )
        matchup_numeric = rolling_numeric + HARD_HIT_MATCHUP_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_matchup"] = (
            build_gradient_pipeline(matchup_numeric, BASE_CATEGORICAL_FEATURES),
            matchup_numeric + BASE_CATEGORICAL_FEATURES,
        )
        pitch_type_matchup_numeric = (
            rolling_numeric
            + HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
            + HARD_HIT_MATCHUP_NUMERIC_FEATURES
        )
        model_specs["hist_gradient_boosting_rolling_form_pitch_type_matchup"] = (
            build_gradient_pipeline(pitch_type_matchup_numeric, BASE_CATEGORICAL_FEATURES),
            pitch_type_matchup_numeric + BASE_CATEGORICAL_FEATURES,
        )

    print(
        "Time split | "
        f"train={train['game_date'].min().date()}..{train['game_date'].max().date()} ({len(train):,}), "
        f"validation={partitions['validation']['game_date'].min().date()}..{partitions['validation']['game_date'].max().date()} ({len(partitions['validation']):,}), "
        f"test={partitions['test']['game_date'].min().date()}..{partitions['test']['game_date'].max().date()} ({len(partitions['test']):,})"
    )
    for name, (model, feature_columns) in model_specs.items():
        print(f"Training {name}...", flush=True)
        model.fit(train[feature_columns], train[TARGET_COLUMN])

    metrics: dict[str, dict[str, dict]] = {
        "smoothed_group_baseline": {},
        **{name: {} for name in model_specs},
    }
    calibration_output: list[dict] = []
    monthly_output: list[dict] = []
    for split_name in ("validation", "test"):
        evaluation = partitions[split_name]
        predictions = {
            "smoothed_group_baseline": predict_baseline(baseline, evaluation),
            **{
                name: model.predict_proba(evaluation[feature_columns])[:, 1]
                for name, (model, feature_columns) in model_specs.items()
            },
        }
        for model_name, predicted in predictions.items():
            metrics[model_name][split_name] = evaluate_predictions(
                evaluation[TARGET_COLUMN], predicted
            )
            calibration_output.extend(
                calibration_rows(model_name, split_name, evaluation, predicted)
            )
            monthly_output.extend(
                monthly_rows(model_name, split_name, evaluation, predicted)
            )

    champion = min(metrics, key=lambda name: metrics[name]["validation"]["log_loss"])
    baseline_test_loss = metrics["smoothed_group_baseline"]["test"]["log_loss"]
    champion_test_loss = metrics[champion]["test"]["log_loss"]
    improvement = 100.0 * (baseline_test_loss - champion_test_loss) / baseline_test_loss
    weather_delta = (
        metrics["hist_gradient_boosting_time_weather"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_base"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    rolling_delta = (
        metrics["hist_gradient_boosting_rolling_form"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_base"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    rolling_weather_delta = (
        metrics["hist_gradient_boosting_rolling_form_time_weather"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_rolling_form"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    pitch_type_delta = (
        metrics["hist_gradient_boosting_rolling_form_pitch_type"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_rolling_form"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    matchup_delta = (
        metrics["hist_gradient_boosting_rolling_form_matchup"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_rolling_form"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    pitch_type_matchup_delta = (
        metrics["hist_gradient_boosting_rolling_form_pitch_type_matchup"]["test"]["log_loss"]
        - metrics["hist_gradient_boosting_rolling_form"]["test"]["log_loss"]
        if not args.skip_gradient
        else None
    )
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(database_path),
        "source_table": SOURCE_TABLE,
        "prediction_horizon": "post_release_contact_quality",
        "target": "hard hit at 95+ mph conditional on a batted ball",
        "seasons": sorted(frame["season"].astype(int).unique().tolist()),
        "split": {
            "train_end": train["game_date"].max().date().isoformat(),
            "validation_start": partitions["validation"]["game_date"].min().date().isoformat(),
            "validation_end": partitions["validation"]["game_date"].max().date().isoformat(),
            "test_start": partitions["test"]["game_date"].min().date().isoformat(),
            "test_end": partitions["test"]["game_date"].max().date().isoformat(),
        },
        "features": {
            "base_numeric": BASE_NUMERIC_FEATURES,
            "base_categorical": BASE_CATEGORICAL_FEATURES,
            "time_weather_numeric": TIME_WEATHER_NUMERIC_FEATURES,
            "time_weather_categorical": TIME_WEATHER_CATEGORICAL_FEATURES,
            "rolling_form_numeric": HARD_HIT_ROLLING_NUMERIC_FEATURES,
            "recent_form_numeric": HARD_HIT_RECENT_FORM_NUMERIC_FEATURES,
            "pitch_type_rolling_numeric": HARD_HIT_PITCH_TYPE_ROLLING_NUMERIC_FEATURES,
            "matchup_numeric": HARD_HIT_MATCHUP_NUMERIC_FEATURES,
            "forbidden_leakage_columns": sorted(FORBIDDEN_LEAKAGE_COLUMNS),
        },
        "library_versions": {
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "champion": champion,
        "champion_test_log_loss_improvement_pct_vs_baseline": improvement,
        "time_weather_test_log_loss_delta_vs_base": weather_delta,
        "rolling_form_test_log_loss_delta_vs_base": rolling_delta,
        "rolling_form_time_weather_test_log_loss_delta_vs_rolling_form": rolling_weather_delta,
        "pitch_type_test_log_loss_delta_vs_rolling_form": pitch_type_delta,
        "matchup_test_log_loss_delta_vs_rolling_form": matchup_delta,
        "pitch_type_matchup_test_log_loss_delta_vs_rolling_form": pitch_type_matchup_delta,
        "metrics": metrics,
    }

    for name, (model, feature_columns) in model_specs.items():
        joblib.dump(
            {
                "pipeline": model,
                "features": feature_columns,
                "trained_through": train["game_date"].max().date().isoformat(),
                "prediction_horizon": "post_release_contact_quality",
            },
            model_dir / f"hard_hit_{name}.joblib",
        )
    (model_dir / "hard_hit_model_metrics.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    pd.DataFrame(calibration_output).to_csv(
        model_dir / "hard_hit_model_calibration.csv", index=False
    )
    pd.DataFrame(monthly_output).to_csv(
        model_dir / "hard_hit_model_monthly.csv", index=False
    )

    print(f"Champion: {champion}")
    for model_name, result in metrics.items():
        test_metrics = result["test"]
        print(
            f"{model_name:38} | test log_loss={test_metrics['log_loss']:.5f} | "
            f"brier={test_metrics['brier_score']:.5f} | "
            f"roc_auc={test_metrics['roc_auc']:.4f} | "
            f"ECE={test_metrics['expected_calibration_error']:.4f}"
        )
    print(f"Artifacts: {model_dir}")


if __name__ == "__main__":
    main()
