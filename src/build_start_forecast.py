"""Pregame strikeout baselines, chronological evaluation, and immutable forecasts.

The retrospective population is observed first pitchers in completed games, not
historical probable-starter announcements. Same-day outcomes never enter features.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import duckdb
import numpy as np
import pandas as pd

from src.artifact_lineage import dataset_identity
from src.common import load_config, project_path


MODELS = ("league_mean", "recent_starts", "workload_opponent")
APPEARANCES_SQL = """
WITH ordered AS (
    SELECT *, FIRST_VALUE(pitcher_id) OVER (
        PARTITION BY game_pk, pitcher_team ORDER BY at_bat_number, pitch_number
    ) AS first_pitcher
    FROM silver.fact_pitch
), appearances AS (
    SELECT game_pk, game_date, pitcher_id, pitcher_team,
           ANY_VALUE(pitcher_name) AS pitcher_name,
           ANY_VALUE(batter_team) AS opponent_team,
           BOOL_OR(pitcher_id = first_pitcher) AS is_starter,
           COUNT(*) AS pitches,
           COUNT(*) FILTER (WHERE plate_appearance_event IS NOT NULL
                             AND plate_appearance_event <> 'truncated_pa') AS batters_faced,
           SUM(CASE WHEN plate_appearance_event IN ('strikeout', 'strikeout_double_play') THEN 1 ELSE 0 END) AS strikeouts
    FROM ordered GROUP BY game_pk, game_date, pitcher_id, pitcher_team
)
SELECT a.*, c.game_datetime_utc FROM appearances a
JOIN silver.fact_game_context c USING (game_pk)
WHERE c.game_status IN ('Final','Game Over','Completed Early')
ORDER BY game_date, game_pk, pitcher_id
"""


def learn_priors(appearances: pd.DataFrame, train_end: str) -> dict:
    train = appearances[pd.to_datetime(appearances.game_date) <= pd.Timestamp(train_end)]
    starts = train[train.is_starter]
    if starts.empty or starts.batters_faced.sum() <= 0:
        raise ValueError("No completed training starts for the pregame baseline")
    return {"start_bf": float(starts.batters_faced.mean()),
            "start_k": float(starts.strikeouts.mean()),
            "start_k_rate": float(starts.strikeouts.sum() / starts.batters_faced.sum()),
            "opponent_k_rate": float(train.strikeouts.sum() / train.batters_faced.sum())}


class PregameHistory:
    def __init__(self, priors: dict):
        self.priors = priors
        self.starts = defaultdict(lambda: deque(maxlen=5))
        self.opponents = defaultdict(deque)
        self.data_through = None

    def features(self, pitcher_id: int, opponent_team: str, game_date) -> dict:
        date = pd.Timestamp(game_date)
        # Filter explicitly as a second safeguard for direct callers and archives.
        starts = [r for r in self.starts[int(pitcher_id)] if r["game_date"] < date]
        opponent = [r for r in self.opponents[str(opponent_team)]
                    if date - pd.Timedelta(days=30) <= r["game_date"] < date]
        bf = sum(r["batters_faced"] for r in starts)
        ks = sum(r["strikeouts"] for r in starts)
        opponent_bf = sum(r["batters_faced"] for r in opponent)
        opponent_ks = sum(r["strikeouts"] for r in opponent)
        expected_bf = (bf + 3 * self.priors["start_bf"]) / (len(starts) + 3)
        k_rate = (ks + 50 * self.priors["start_k_rate"]) / (bf + 50)
        opponent_rate = (opponent_ks + 100 * self.priors["opponent_k_rate"]) / (opponent_bf + 100)
        adjustment = float(np.clip((opponent_rate / self.priors["opponent_k_rate"]) ** 0.5, 0.8, 1.2))
        return {"prior_starts": len(starts), "prior_batters_faced": bf,
                "opponent_prior_pa": opponent_bf, "expected_batters_faced": expected_bf,
                "pitcher_k_rate": k_rate, "opponent_k_rate": opponent_rate,
                "opponent_adjustment": adjustment,
                "last_start_date": str(starts[-1]["game_date"].date()) if starts else None,
                "feature_data_through": str(self.data_through.date()) if self.data_through is not None else None,
                "league_mean": self.priors["start_k"],
                "recent_starts": (ks + 3 * self.priors["start_k"]) / (len(starts) + 3),
                "workload_opponent": expected_bf * k_rate * adjustment}

    def observe_day(self, date, rows: pd.DataFrame) -> None:
        date = pd.Timestamp(date)
        if self.data_through is not None and date <= self.data_through:
            raise ValueError("History must be updated once per day in chronological order")
        for row in rows.to_dict("records"):
            record = {"game_date": date, "batters_faced": int(row["batters_faced"]),
                      "strikeouts": int(row["strikeouts"])}
            if row["is_starter"]:
                self.starts[int(row["pitcher_id"])].append(record)
        for team, group in rows.groupby("opponent_team"):
            history = self.opponents[str(team)]
            history.append({"game_date": date, "batters_faced": int(group.batters_faced.sum()),
                            "strikeouts": int(group.strikeouts.sum())})
            while history and history[0]["game_date"] < date - pd.Timedelta(days=30):
                history.popleft()
        self.data_through = date


def chronological_predictions(appearances: pd.DataFrame, boundaries: dict) -> tuple[pd.DataFrame, PregameHistory]:
    history = PregameHistory(learn_priors(appearances, boundaries["train_end"]))
    data = appearances.copy()
    data["game_date"] = pd.to_datetime(data.game_date)
    predictions = []
    for date, games in data.groupby("game_date", sort=True):
        if pd.Timestamp(boundaries["validation_start"]) <= date <= pd.Timestamp(boundaries["test_end"]):
            # Score every start on this date BEFORE observing any result that day.
            for row in games[games.is_starter].to_dict("records"):
                predictions.append({"game_pk": int(row["game_pk"]), "pitcher_id": int(row["pitcher_id"]),
                                    "game_date": str(date.date()), "actual_k": int(row["strikeouts"]),
                                    **history.features(row["pitcher_id"], row["opponent_team"], date)})
        history.observe_day(date, games)
    return pd.DataFrame(predictions), history


def count_bounds(predicted, radius: float):
    lower = np.maximum(0, np.ceil(np.asarray(predicted) - radius)).astype(int)
    upper = np.maximum(lower, np.floor(np.asarray(predicted) + radius)).astype(int)
    return lower, upper


def summarize_errors(frame: pd.DataFrame, model: str, radius: float) -> dict:
    predicted = frame[model].to_numpy(dtype=float)
    actual = frame.actual_k.to_numpy(dtype=float)
    lower, upper = count_bounds(predicted, radius)
    return {"rows": len(frame), "mae": float(np.abs(predicted - actual).mean()),
            "rmse": float(np.sqrt(np.square(predicted - actual).mean())),
            "bias": float((predicted - actual).mean()),
            "interval_coverage": float(((actual >= lower) & (actual <= upper)).mean()),
            "mean_interval_width": float((upper - lower).mean())}


def evaluate_backtest(predictions: pd.DataFrame, boundaries: dict) -> tuple[dict, pd.DataFrame]:
    validation = predictions[predictions.game_date < boundaries["test_start"]]
    test = predictions[predictions.game_date >= boundaries["test_start"]]
    dates = sorted(validation.game_date.unique())
    if len(dates) < 4 or test.empty:
        raise ValueError("Need at least four validation dates and nonempty fixed test data")
    cut = dates[max(1, min(len(dates)-1, int(len(dates)*0.7)))]
    selection = validation[validation.game_date < cut]
    calibration = validation[validation.game_date >= cut]
    champion = min(MODELS, key=lambda model: float((selection[model]-selection.actual_k).abs().mean()))
    # Validation tail is separate from model selection. Coverage is measured on
    # held-out starts, not guaranteed under temporal distribution shift.
    error = (calibration[champion]-calibration.actual_k).abs().to_numpy()
    quantile = min(1.0, np.ceil((len(error)+1)*0.8) / len(error))
    radius = float(np.quantile(error, quantile, method="higher"))
    rows = [{"model": model, "is_selected": model == champion,
             "selection_mae": float((selection[model]-selection.actual_k).abs().mean()),
             "test_start": boundaries["test_start"], "test_end": boundaries["test_end"],
             **summarize_errors(test, model, radius)} for model in MODELS]
    monthly = [{"month": month, "model": champion, **summarize_errors(group, champion, radius)}
               for month, group in test.groupby(test.game_date.str[:7])]
    manifest = {"champion": champion, "interval_radius": radius, "interval_nominal": 0.8,
                "selection_end": str(selection.game_date.max()), "calibration_start": cut,
                "calibration_end": str(calibration.game_date.max()), "calibration_rows": len(calibration),
                "boundaries": boundaries, "test_metrics": rows, "monthly_test_metrics": monthly,
                "population": "Observed first pitchers in completed regular-season games; includes openers and short starts",
                "limitations": ["Retrospective feature backtest; no archived probable-starter selection or cancellation replay.",
                                "Counts completed recorded plate appearances; no official innings-pitched target.",
                                "Prior-day data only; no current-game velocity, location, workload, or outcomes.",
                                "Empirical interval coverage may change over time; not a guarantee.",
                                "No lineup, injury, pitch-limit, or weather adjustments in these baselines."]}
    predictions = predictions.copy()
    predictions["split"] = np.where(predictions.game_date >= boundaries["test_start"], "test",
                                     np.where(predictions.game_date >= cut, "calibration", "selection"))
    predictions["predicted_k"] = predictions[champion]
    predictions["lower_k"], predictions["upper_k"] = count_bounds(predictions.predicted_k, radius)
    return manifest, predictions


def upcoming_predictions(slots: pd.DataFrame, history: PregameHistory, model: dict, now: datetime) -> pd.DataFrame:
    rows = []
    slots = slots.drop_duplicates(["game_pk", "pitcher_team"])
    for slot in slots.to_dict("records"):
        if slot.get("probable_status") != "Confirmed probable" or pd.isna(slot.get("pitcher_id")):
            continue
        start = pd.Timestamp(slot["game_datetime_utc"])
        date = str(slot["game_date"])[:10]
        if start <= pd.Timestamp(now) or pd.Timestamp(date) <= history.data_through:
            continue
        features = history.features(int(slot["pitcher_id"]), slot["opponent_team"], date)
        mean = features[model["champion"]]
        radius = model["interval_radius"]
        lower, upper = count_bounds(mean, radius)
        rows.append({"game_pk": int(slot["game_pk"]), "pitcher_id": int(slot["pitcher_id"]),
                     "pitcher_name": slot["pitcher_name"], "pitcher_team": slot["pitcher_team"],
                     "opponent_team": slot["opponent_team"], "game_date": date,
                     "game_datetime_utc": start.isoformat(), "generated_at_utc": now.isoformat(),
                     "model": model["champion"], "predicted_k": mean,
                     "lower_k": int(lower), "upper_k": int(upper),
                     "prior_starts": features["prior_starts"], "last_start_date": features["last_start_date"],
                     "expected_batters_faced": features["expected_batters_faced"],
                     "pitcher_k_rate": features["pitcher_k_rate"], "opponent_k_rate": features["opponent_k_rate"],
                     "feature_data_through": features["feature_data_through"],
                     "sample_status": "Limited starting history" if features["prior_starts"] < 3 else "At least 3 prior starts"})
    columns = ["game_pk","pitcher_id","pitcher_name","pitcher_team","opponent_team","game_date",
               "game_datetime_utc","generated_at_utc","model","predicted_k","lower_k","upper_k","prior_starts",
               "last_start_date","expected_batters_faced","pitcher_k_rate","opponent_k_rate","feature_data_through","sample_status"]
    return pd.DataFrame(rows, columns=columns).sort_values(["game_date","predicted_k"], ascending=[True,False])


def settle_archives(directory: Path, appearances: pd.DataFrame) -> pd.DataFrame:
    first = {}
    for path in sorted(directory.glob("*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        for row in artifact["predictions"]:
            key = (row["game_pk"], row["pitcher_id"])
            if key not in first or row["generated_at_utc"] < first[key]["generated_at_utc"]:
                first[key] = {**row, "archive_file": f"outputs/forecast/archive/{path.name}"}
    actual = {(int(row.game_pk),int(row.pitcher_id)): row for row in appearances[appearances.is_starter].itertuples()}
    completed = set(appearances.game_pk)
    results = []
    for key, forecast in first.items():
        row = actual.get(key)
        status = "pending" if key[0] not in completed else "did_not_start"
        observed = None
        if row is not None:
            # Compare to the actual recorded start too, in case start times changed.
            if pd.Timestamp(forecast["generated_at_utc"]) < pd.Timestamp(row.game_datetime_utc):
                status, observed = "observed", int(row.strikeouts)
            else:
                status = "excluded_after_actual_start"
        results.append({**forecast, "outcome_status": status, "actual_k": observed,
                        "absolute_error": abs(observed-forecast["predicted_k"]) if observed is not None else None})
    return pd.DataFrame(results, columns=["game_pk","pitcher_id","pitcher_name","pitcher_team","game_date",
                                        "generated_at_utc","model_version","predicted_k","lower_k","upper_k",
                                        "outcome_status","actual_k","absolute_error","archive_file"])


def build_comparison(radar: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    radar = radar[(radar.window_days == 14) & (radar.profile_key == "roto_balance")].copy()
    nearest = forecasts.sort_values("game_datetime_utc").drop_duplicates("pitcher_id")
    # Upcoming rookies remain selectable even when absent from the qualified radar.
    result = radar.merge(nearest, on="pitcher_id", how="outer", suffixes=("", "_forecast"))
    for field in ("pitcher_name", "pitcher_team"):
        result[field] = result[field].fillna(result[f"{field}_forecast"])
    fields = ["pitcher_id","pitcher_name","pitcher_team","window_start","window_end","pitches","games",
              "avg_velocity","k_minus_bb_rate","expected_whiff_rate","hard_hit_rate_allowed","measured_batted_balls",
              "sample_strength","fantasy_signal","game_date","opponent_team","predicted_k","lower_k","upper_k",
              "prior_starts","expected_batters_faced","feature_data_through","model"]
    return result.reindex(columns=fields).sort_values("fantasy_signal", ascending=False, na_position="last")


def write_csv(frame: pd.DataFrame, path: Path):
    temporary = path.with_suffix(".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/pipeline_config.json")
    args = parser.parse_args()
    config = load_config(args.config)
    output = project_path(config["paths"]["outputs_dir"])
    directory = output / "forecast"
    archive = directory / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(project_path(config["paths"]["database"])), read_only=True) as connection:
        appearances = connection.execute(APPEARANCES_SQL).fetchdf()
    if (appearances.strikeouts > appearances.batters_faced).any():
        raise ValueError("Strikeouts exceed completed plate appearances")
    backtest, history = chronological_predictions(appearances, config["model_evaluation"])
    model, backtest = evaluate_backtest(backtest, config["model_evaluation"])
    model["priors"] = history.priors
    model["dataset"] = dataset_identity(config)
    model["code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    model["model_version"] = hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc)
    forecasts = upcoming_predictions(pd.read_csv(output / "fantasy" / "matchup_stream_planner.csv"), history, model, now)
    forecasts["model_version"] = model["model_version"]
    predictions = json.loads(forecasts.to_json(orient="records"))
    archive_path = archive / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}.json"
    # Exclusive creation; previously emitted predictions are never overwritten.
    with archive_path.open("x", encoding="utf-8") as file:
        json.dump({"generated_at_utc": now.isoformat(), "model": model, "predictions": predictions}, file, indent=2)
    write_csv(backtest, directory / "backtest.csv")
    write_csv(pd.DataFrame(model["test_metrics"]), directory / "evaluation.csv")
    write_csv(forecasts, directory / "upcoming.csv")
    settled = settle_archives(archive, appearances)
    write_csv(settled, directory / "forecast_history.csv")
    from src.forecast_monitor import summarize_live
    write_csv(summarize_live(settled, model["dataset"]["data_through"]), directory / "live_monitor.csv")
    comparison = build_comparison(pd.read_csv(output / "fantasy" / "pitcher_fantasy_radar.csv"), forecasts)
    write_csv(comparison, directory / "comparison.csv")
    (directory / "model_manifest.json").write_text(json.dumps(model, indent=2), encoding="utf-8")
    selected = next(row for row in model["test_metrics"] if row["is_selected"])
    print(f"Starter baseline: {model['champion']}; fixed-test MAE={selected['mae']:.3f}, empirical interval coverage={selected['interval_coverage']:.1%}")
    print(f"Upcoming: {len(forecasts)}; comparison pitchers: {len(comparison)}; archived pregame forecasts: {archive_path.name}")


if __name__ == "__main__":
    from src.artifact_lineage import run_versioned
    run_versioned("build_start_forecast", main)
