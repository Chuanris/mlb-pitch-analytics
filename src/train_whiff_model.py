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
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from src.common import load_config, project_path


TARGET_COLUMN = "target_whiff"
IDENTIFIER_COLUMNS = [
    "pitch_id",
    "game_pk",
    "game_date",
    "season",
    "pitcher_id",
    "batter_id",
]
BASE_NUMERIC_FEATURES = [
    "balls",
    "strikes",
    "inning",
    "outs_when_up",
    "runner_on_first_flag",
    "runner_on_second_flag",
    "runner_on_third_flag",
    "batter_score_diff",
    "times_through_order",
    "pitcher_days_rest",
    "batter_days_rest",
    "pitcher_age",
    "batter_age",
    "pitcher_pitch_number_in_game",
    "release_speed",
    "effective_speed",
    "release_spin_rate",
    "spin_axis",
    "release_pos_x",
    "release_pos_y",
    "release_pos_z",
    "release_extension",
    "arm_angle",
    "horizontal_movement",
    "vertical_movement",
    "plate_x",
    "plate_z",
    "strike_zone_top",
    "strike_zone_bottom",
    "normalized_plate_z",
    "in_zone_flag",
    "previous_pitch_number",
    "previous_release_speed",
    "previous_plate_x",
    "previous_plate_z",
    "release_speed_change",
    "plate_x_change",
    "plate_z_change",
]
BASE_CATEGORICAL_FEATURES = [
    "pitch_type",
    "pitch_family",
    "pitcher_throws",
    "batter_stand",
    "count_state",
    "inning_half",
    "tracking_regime",
    "previous_pitch_type",
    "previous_pitch_family",
]
TIME_WEATHER_NUMERIC_FEATURES = [
    "local_start_hour_sin",
    "local_start_hour_cos",
    "weekend_flag",
    "venue_latitude",
    "venue_longitude",
    "elevation_ft",
    "temperature_f",
    "wind_speed_mph",
    "wind_out_flag",
    "wind_in_flag",
    "crosswind_flag",
    "indoor_flag",
]
TIME_WEATHER_CATEGORICAL_FEATURES = [
    "local_day_of_week",
    "local_month",
    "day_night",
    "venue_id",
    "time_zone_id",
    "roof_type",
    "turf_type",
    "weather_condition",
    "wind_direction",
]
WHIFF_ROLLING_NUMERIC_FEATURES = [
    "pitcher_swings_prior_200",
    "pitcher_whiff_rate_prior_200_swings",
    "pitcher_swings_prior_30d",
    "pitcher_whiff_rate_prior_30d",
    "batter_swings_prior_50",
    "batter_whiff_rate_prior_50_swings",
    "batter_swings_prior_30d",
    "batter_whiff_rate_prior_30d",
]
WHIFF_RECENT_FORM_NUMERIC_FEATURES = [
    "pitcher_swings_prior_14d",
    "pitcher_whiff_rate_prior_14d",
    "batter_swings_prior_14d",
    "batter_whiff_rate_prior_14d",
]
WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES = [
    "pitcher_pitch_type_swings_prior_100",
    "pitcher_pitch_type_whiff_rate_prior_100_swings",
    "pitcher_pitch_type_swings_prior_30d",
    "pitcher_pitch_type_whiff_rate_prior_30d",
    "batter_pitch_type_swings_prior_30",
    "batter_pitch_type_whiff_rate_prior_30_swings",
    "batter_pitch_type_swings_prior_30d",
    "batter_pitch_type_whiff_rate_prior_30d",
]
WHIFF_MATCHUP_NUMERIC_FEATURES = [
    "matchup_swings_prior_30",
    "matchup_whiff_rate_prior_30_swings",
]
NUMERIC_FEATURES = BASE_NUMERIC_FEATURES + TIME_WEATHER_NUMERIC_FEATURES
CATEGORICAL_FEATURES = BASE_CATEGORICAL_FEATURES + TIME_WEATHER_CATEGORICAL_FEATURES
ALL_NUMERIC_FEATURES = (
    NUMERIC_FEATURES
    + WHIFF_ROLLING_NUMERIC_FEATURES
    + WHIFF_RECENT_FORM_NUMERIC_FEATURES
    + WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
    + WHIFF_MATCHUP_NUMERIC_FEATURES
)
BASELINE_GROUP_COLUMNS = ["pitch_type", "balls", "strikes", "batter_stand"]
FORBIDDEN_LEAKAGE_COLUMNS = {
    "pitch_description",
    "plate_appearance_event",
    "launch_speed",
    "launch_angle",
    "bat_speed",
    "swing_length",
    "miss_distance",
    "estimated_woba",
    "delta_run_exp",
    "post_home_score",
    "post_away_score",
    "pitcher_days_until_next_game",
}


@dataclass(frozen=True)
class TimeSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    validation_start: pd.Timestamp
    test_start: pd.Timestamp


def assert_feature_contract(columns: list[str]) -> None:
    overlap = FORBIDDEN_LEAKAGE_COLUMNS.intersection(columns)
    if overlap:
        raise ValueError(f"Outcome or future columns cannot be model features: {sorted(overlap)}")
    duplicated = pd.Index(columns)[pd.Index(columns).duplicated()].tolist()
    if duplicated:
        raise ValueError(f"Duplicate model features: {duplicated}")


def make_time_split(frame: pd.DataFrame, boundaries: dict | None = None) -> TimeSplit:
    # Explicit calendar boundaries keep benchmark membership stable as data grows.
    if boundaries is None:
        boundaries = load_config("config/pipeline_config.json")["model_evaluation"]
    train_end, validation_start, test_start, test_end = (
        pd.Timestamp(boundaries[key]) for key in
        ("train_end", "validation_start", "test_start", "test_end")
    )
    if any(pd.isna(value) for value in (train_end, validation_start, test_start, test_end)) or not (
        train_end < validation_start < test_start <= test_end
    ):
        raise ValueError("Model evaluation requires train_end < validation_start < test_start <= test_end")
    data = frame.copy()
    data["game_date"] = pd.to_datetime(data["game_date"])
    train = data[data["game_date"] <= train_end].copy()
    validation = data[data["game_date"].between(validation_start, test_start, inclusive="left")].copy()
    test = data[data["game_date"].between(test_start, test_end)].copy()
    if train.empty or validation.empty or test.empty:
        raise ValueError("Chronological split produced an empty partition.")
    if train["game_date"].max() >= validation["game_date"].min():
        raise ValueError("Training data must end before validation data begins.")
    if validation["game_date"].max() >= test["game_date"].min():
        raise ValueError("Validation data must end before test data begins.")

    return TimeSplit(
        train=train,
        validation=validation,
        test=test,
        validation_start=validation["game_date"].min(),
        test_start=test_start,
    )


def limit_rows(frame: pd.DataFrame, limit: int | None, seed: int) -> pd.DataFrame:
    if not limit or len(frame) <= limit:
        return frame
    return frame.sample(n=limit, random_state=seed).sort_values("game_date").copy()


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


def probability_logit(predicted: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(predicted, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def fit_platt_calibrator(observed: pd.Series | np.ndarray, predicted: np.ndarray) -> LogisticRegression:
    calibrator = LogisticRegression(
        solver="lbfgs",
        C=1.0,
        max_iter=250,
        random_state=42,
    )
    calibrator.fit(probability_logit(predicted), np.asarray(observed, dtype=int))
    return calibrator


def apply_platt_calibrator(calibrator: LogisticRegression, predicted: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(probability_logit(predicted))[:, 1]


def build_logistic_pipeline(
    numeric_features: list[str],
    categorical_features: list[str],
) -> Pipeline:
    numeric = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            (
                "encode",
                OneHotEncoder(handle_unknown="ignore", min_frequency=100),
            ),
        ]
    )
    preprocessing = ColumnTransformer(
        [
            ("numeric", numeric, numeric_features),
            ("categorical", categorical, categorical_features),
        ]
    )
    return Pipeline(
        [
            ("preprocess", preprocessing),
            (
                "model",
                LogisticRegression(
                    solver="lbfgs",
                    max_iter=250,
                    random_state=42,
                ),
            ),
        ]
    )


def build_gradient_pipeline(
    numeric_features: list[str],
    categorical_features: list[str],
    **model_overrides,
) -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median"))])
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            (
                "encode",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    encoded_missing_value=-1,
                ),
            ),
        ]
    )
    preprocessing = ColumnTransformer(
        [
            ("numeric", numeric, numeric_features),
            ("categorical", categorical, categorical_features),
        ],
        sparse_threshold=0,
    )
    categorical_indices = list(
        range(len(numeric_features), len(numeric_features) + len(categorical_features))
    )
    model_parameters = {
        "learning_rate": 0.08,
        "max_iter": 160,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 100,
        "l2_regularization": 1.0,
        "categorical_features": categorical_indices,
        "random_state": 42,
    }
    model_parameters.update(model_overrides)
    return Pipeline(
        [
            ("preprocess", preprocessing),
            (
                "model",
                HistGradientBoostingClassifier(**model_parameters),
            ),
        ]
    )


def expected_calibration_error(
    observed: pd.Series | np.ndarray,
    predicted: np.ndarray,
    bins: int = 10,
) -> float:
    y = np.asarray(observed, dtype=float)
    p = np.asarray(predicted, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    assignments = np.clip(np.digitize(p, edges[1:-1], right=True), 0, bins - 1)
    total = len(y)
    error = 0.0
    for index in range(bins):
        mask = assignments == index
        if mask.any():
            error += mask.mean() * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(error if total else np.nan)


def evaluate_predictions(
    observed: pd.Series,
    predicted: np.ndarray,
) -> dict[str, float | int]:
    clipped = np.clip(np.asarray(predicted, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(observed, dtype=int)
    return {
        "rows": int(len(y)),
        "whiff_rate": float(y.mean()),
        "predicted_whiff_rate": float(clipped.mean()),
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
        .agg(rows=("observed", "size"), observed_rate=("observed", "mean"), predicted_rate=("predicted", "mean"))
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
        .agg(rows=("observed", "size"), observed_whiff_rate=("observed", "mean"), predicted_whiff_rate=("predicted", "mean"))
        .reset_index()
    )
    summary.insert(0, "split", split_name)
    summary.insert(0, "model", model_name)
    return summary.to_dict(orient="records")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and evaluate post-release pitch whiff-probability models."
    )
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument(
        "--max-rows-per-split",
        type=int,
        help="Optional deterministic cap for development runs; defaults to all rows.",
    )
    parser.add_argument("--skip-gradient", action="store_true")
    args = parser.parse_args()

    assert_feature_contract(ALL_NUMERIC_FEATURES + CATEGORICAL_FEATURES)
    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    model_dir = project_path(config["paths"]["outputs_dir"]) / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    selected_columns = IDENTIFIER_COLUMNS + ALL_NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET_COLUMN]
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        available_columns = {
            row[0]
            for row in connection.execute(
                "DESCRIBE gold.training_pitch_whiff"
            ).fetchall()
        }
        missing = sorted(set(selected_columns) - available_columns)
        if missing:
            raise ValueError(f"Training mart is missing required columns: {missing}")
        query = (
            "SELECT "
            + ", ".join(selected_columns)
            + " FROM gold.training_pitch_whiff "
            + "ORDER BY game_date, game_pk, pitch_id"
        )
        frame = connection.execute(query).fetchdf()
    finally:
        connection.close()

    split = make_time_split(frame, config["model_evaluation"])
    partitions = {
        "train": limit_rows(split.train, args.max_rows_per_split, 42),
        "validation": limit_rows(split.validation, args.max_rows_per_split, 43),
        "test": limit_rows(split.test, args.max_rows_per_split, 44),
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
        rolling_numeric = BASE_NUMERIC_FEATURES + WHIFF_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form"] = (
            build_gradient_pipeline(rolling_numeric, BASE_CATEGORICAL_FEATURES),
            rolling_numeric + BASE_CATEGORICAL_FEATURES,
        )
        recent_form_numeric = rolling_numeric + WHIFF_RECENT_FORM_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_recent"] = (
            build_gradient_pipeline(recent_form_numeric, BASE_CATEGORICAL_FEATURES),
            recent_form_numeric + BASE_CATEGORICAL_FEATURES,
        )
        rolling_weather_numeric = NUMERIC_FEATURES + WHIFF_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_time_weather"] = (
            build_gradient_pipeline(rolling_weather_numeric, CATEGORICAL_FEATURES),
            rolling_weather_numeric + CATEGORICAL_FEATURES,
        )
        pitch_type_numeric = rolling_numeric + WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_pitch_type"] = (
            build_gradient_pipeline(pitch_type_numeric, BASE_CATEGORICAL_FEATURES),
            pitch_type_numeric + BASE_CATEGORICAL_FEATURES,
        )
        matchup_numeric = rolling_numeric + WHIFF_MATCHUP_NUMERIC_FEATURES
        model_specs["hist_gradient_boosting_rolling_form_matchup"] = (
            build_gradient_pipeline(matchup_numeric, BASE_CATEGORICAL_FEATURES),
            matchup_numeric + BASE_CATEGORICAL_FEATURES,
        )
        pitch_type_matchup_numeric = (
            rolling_numeric
            + WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
            + WHIFF_MATCHUP_NUMERIC_FEATURES
        )
        model_specs["hist_gradient_boosting_rolling_form_pitch_type_matchup"] = (
            build_gradient_pipeline(pitch_type_matchup_numeric, BASE_CATEGORICAL_FEATURES),
            pitch_type_matchup_numeric + BASE_CATEGORICAL_FEATURES,
        )
        model_specs["hist_gradient_boosting_tuned_pitch_type_matchup"] = (
            build_gradient_pipeline(
                pitch_type_matchup_numeric,
                BASE_CATEGORICAL_FEATURES,
                learning_rate=0.06,
                max_iter=220,
                min_samples_leaf=80,
                l2_regularization=2.0,
            ),
            pitch_type_matchup_numeric + BASE_CATEGORICAL_FEATURES,
        )
        recent_pitch_type_matchup_numeric = (
            recent_form_numeric
            + WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES
            + WHIFF_MATCHUP_NUMERIC_FEATURES
        )
        model_specs["hist_gradient_boosting_rolling_form_recent_pitch_type_matchup"] = (
            build_gradient_pipeline(recent_pitch_type_matchup_numeric, BASE_CATEGORICAL_FEATURES),
            recent_pitch_type_matchup_numeric + BASE_CATEGORICAL_FEATURES,
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
    prediction_cache: dict[str, dict[str, np.ndarray]] = {}
    for split_name in ("validation", "test"):
        evaluation = partitions[split_name]
        predictions = {
            "smoothed_group_baseline": predict_baseline(baseline, evaluation),
            **{
                name: model.predict_proba(evaluation[feature_columns])[:, 1]
                for name, (model, feature_columns) in model_specs.items()
            },
        }
        prediction_cache[split_name] = predictions
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

    champion_base_model = min(metrics, key=lambda name: metrics[name]["validation"]["log_loss"])
    validation = partitions["validation"].reset_index(drop=True)
    calibration_cut = max(1, min(len(validation) - 1, int(len(validation) * 0.70)))
    calibration_train = validation.iloc[:calibration_cut]
    calibration_check = validation.iloc[calibration_cut:]
    validation_predictions = prediction_cache["validation"][champion_base_model]
    calibration_candidate = fit_platt_calibrator(
        calibration_train[TARGET_COLUMN],
        validation_predictions[:calibration_cut],
    )
    calibration_check_raw = validation_predictions[calibration_cut:]
    calibration_check_predicted = apply_platt_calibrator(
        calibration_candidate,
        calibration_check_raw,
    )
    raw_check_metrics = evaluate_predictions(
        calibration_check[TARGET_COLUMN],
        calibration_check_raw,
    )
    calibrated_check_metrics = evaluate_predictions(
        calibration_check[TARGET_COLUMN],
        calibration_check_predicted,
    )
    calibration_accepted = (
        calibrated_check_metrics["log_loss"] < raw_check_metrics["log_loss"]
        and calibrated_check_metrics["expected_calibration_error"]
        < raw_check_metrics["expected_calibration_error"]
    )
    calibration_name = f"{champion_base_model}_platt_calibrated"
    calibration_manifest = {
        "method": "platt_logistic_on_probability_logit",
        "base_model": champion_base_model,
        "selection_rule": "accepted only when chronological validation tail improves log loss and ECE",
        "fit_rows": int(len(calibration_train)),
        "check_rows": int(len(calibration_check)),
        "check_start": calibration_check["game_date"].min().date().isoformat(),
        "accepted": calibration_accepted,
        "raw_check_metrics": raw_check_metrics,
        "calibrated_check_metrics": calibrated_check_metrics,
    }
    probability_calibrator = None
    if calibration_accepted:
        probability_calibrator = fit_platt_calibrator(
            validation[TARGET_COLUMN],
            validation_predictions,
        )
        calibrated_test_predictions = apply_platt_calibrator(
            probability_calibrator,
            prediction_cache["test"][champion_base_model],
        )
        metrics[calibration_name] = {
            "validation_calibration_check": calibrated_check_metrics,
            "test": evaluate_predictions(partitions["test"][TARGET_COLUMN], calibrated_test_predictions),
        }
        calibration_output.extend(
            calibration_rows(
                calibration_name,
                "validation_calibration_check",
                calibration_check,
                calibration_check_predicted,
            )
        )
        calibration_output.extend(
            calibration_rows(
                calibration_name,
                "test",
                partitions["test"],
                calibrated_test_predictions,
            )
        )
        monthly_output.extend(
            monthly_rows(
                calibration_name,
                "test",
                partitions["test"],
                calibrated_test_predictions,
            )
        )
    champion = calibration_name if calibration_accepted else champion_base_model
    baseline_test_loss = metrics["smoothed_group_baseline"]["test"]["log_loss"]
    champion_test_loss = metrics[champion]["test"]["log_loss"]
    improvement = 100.0 * (baseline_test_loss - champion_test_loss) / baseline_test_loss
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
        "source_table": "gold.training_pitch_whiff",
        "prediction_horizon": "post_release_pitch_quality",
        "target": "whiff conditional on a recorded swing",
        "seasons": sorted(frame["season"].astype(int).unique().tolist()),
        "evaluation_boundaries": config["model_evaluation"],
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
            "rolling_form_numeric": WHIFF_ROLLING_NUMERIC_FEATURES,
            "recent_form_numeric": WHIFF_RECENT_FORM_NUMERIC_FEATURES,
            "pitch_type_rolling_numeric": WHIFF_PITCH_TYPE_ROLLING_NUMERIC_FEATURES,
            "matchup_numeric": WHIFF_MATCHUP_NUMERIC_FEATURES,
            "forbidden_leakage_columns": sorted(FORBIDDEN_LEAKAGE_COLUMNS),
        },
        "library_versions": {
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "champion": champion,
        "champion_base_model": champion_base_model,
        "probability_calibration": calibration_manifest,
        "champion_test_log_loss_improvement_pct_vs_baseline": improvement,
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
                "prediction_horizon": "post_release_pitch_quality",
            },
            model_dir / f"whiff_{name}.joblib",
        )
    calibrator_path = model_dir / "whiff_probability_calibrator.joblib"
    if probability_calibrator is not None:
        joblib.dump(
            {
                "calibrator": probability_calibrator,
                "base_model": champion_base_model,
                "fit_period": {
                    "start": validation["game_date"].min().date().isoformat(),
                    "end": validation["game_date"].max().date().isoformat(),
                },
                "method": "platt_logistic_on_probability_logit",
            },
            calibrator_path,
        )
    elif calibrator_path.exists():
        calibrator_path.unlink()
    (model_dir / "whiff_model_metrics.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    pd.DataFrame(calibration_output).to_csv(
        model_dir / "whiff_model_calibration.csv", index=False
    )
    pd.DataFrame(monthly_output).to_csv(
        model_dir / "whiff_model_monthly.csv", index=False
    )

    print(f"Champion: {champion}")
    for model_name, result in metrics.items():
        test_metrics = result["test"]
        print(
            f"{model_name:26} | test log_loss={test_metrics['log_loss']:.5f} | "
            f"brier={test_metrics['brier_score']:.5f} | "
            f"roc_auc={test_metrics['roc_auc']:.4f} | "
            f"ECE={test_metrics['expected_calibration_error']:.4f}"
        )
    print(f"Artifacts: {model_dir}")


if __name__ == "__main__":
    from src.artifact_lineage import run_versioned
    run_versioned("train_whiff_model", main)
