from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from src.common import load_config, project_path


APP_ID = "7dcc5b0c-3b12-473d-943c-54187439bfad"
SUMMARY_QUERY_ID = "pitch_summary"
LOCATION_QUERY_ID = "location_density"
MODEL_EVALUATION_QUERY_ID = "model_evaluation"
MODEL_CALIBRATION_QUERY_ID = "model_calibration"
MODEL_LEADERBOARD_QUERY_ID = "model_leaderboard"
PITCH_PREDICTIONS_QUERY_ID = "pitch_model_predictions"
FANTASY_RADAR_QUERY_ID = "fantasy_pitcher_radar"
STREAM_PLANNER_QUERY_ID = "matchup_stream_planner"

MODEL_LABELS = {
    "smoothed_group_baseline": "Smoothed baseline",
    "logistic_regression": "Logistic regression",
    "hist_gradient_boosting_base": "Base HGB",
    "hist_gradient_boosting_time_weather": "Base + weather",
    "hist_gradient_boosting_rolling_form": "Rolling form",
    "hist_gradient_boosting_rolling_form_recent": "Rolling + 14-day form",
    "hist_gradient_boosting_rolling_form_time_weather": "Rolling + weather",
    "hist_gradient_boosting_rolling_form_pitch_type": "Rolling + pitch type",
    "hist_gradient_boosting_rolling_form_recent_pitch_type": "Rolling + 14-day form + pitch type",
    "hist_gradient_boosting_rolling_form_matchup": "Rolling + matchup",
    "hist_gradient_boosting_rolling_form_pitch_type_matchup": "Rolling + pitch type + matchup",
    "hist_gradient_boosting_rolling_form_recent_pitch_type_matchup": "Rolling + 14-day form + pitch type + matchup",
    "hist_gradient_boosting_tuned_pitch_type": "Tuned rolling + pitch type",
    "hist_gradient_boosting_tuned_pitch_type_matchup": "Tuned rolling + pitch type + matchup",
    "hist_gradient_boosting_tuned_pitch_type_matchup_platt_calibrated": "Calibrated tuned champion",
    "hist_gradient_boosting_rolling_form_pitch_type_matchup_platt_calibrated": "Calibrated combined champion",
}

PITCH_SUMMARY_SQL = """
SELECT
    season,
    pitcher_id,
    pitcher_name,
    pitcher_team,
    pitcher_throws,
    batter_stand,
    pitch_type,
    pitch_name,
    pitch_family,
    count_state,
    COUNT(*)::BIGINT AS pitch_count,
    SUM(in_zone_flag)::BIGINT AS in_zone_count,
    SUM(swing_flag)::BIGINT AS swing_count,
    SUM(whiff_flag)::BIGINT AS whiff_count,
    SUM(chase_flag)::BIGINT AS chase_count,
    SUM(batted_ball_flag)::BIGINT AS batted_ball_count,
    COUNT(*) FILTER (WHERE batted_ball_flag = 1 AND hard_hit_flag IS NOT NULL) AS measured_batted_ball_count,
    SUM(hard_hit_flag)::BIGINT AS hard_hit_count,
    ROUND(SUM(release_speed), 2) AS velocity_total,
    COUNT(release_speed)::BIGINT AS velocity_count,
    STRFTIME(MIN(game_date), '%Y-%m-%d') AS first_game_date,
    STRFTIME(MAX(game_date), '%Y-%m-%d') AS last_game_date
FROM silver.fact_pitch
GROUP BY ALL
ORDER BY season, pitcher_name, pitch_name, count_state, batter_stand
""".strip()

LOCATION_DENSITY_SQL = """
SELECT
    season,
    batter_stand,
    pitch_family,
    count_state,
    ROUND(plate_x * 4) / 4 AS plate_x_bin,
    ROUND(plate_z * 4) / 4 AS plate_z_bin,
    COUNT(*)::BIGINT AS pitch_count
FROM silver.fact_pitch
WHERE plate_x BETWEEN -2 AND 2
  AND plate_z BETWEEN 0 AND 5
GROUP BY ALL
ORDER BY season, plate_z_bin, plate_x_bin, pitch_family
""".strip()


def summary_metric_definitions() -> list[dict]:
    source = [{"tables": ["silver.fact_pitch"], "files": ["database/mlb_pitch_analytics.duckdb"]}]
    return [
        {
            "label": "Pitch count",
            "definition": "Reviewed regular-season pitches remaining after the selected dashboard filters.",
            "formula": "SUM(pitch_count)",
            "componentIds": ["pitch-count", "pitch-usage", "pitch-mix-by-season", "count-strategy", "pitcher-table"],
            "sourceLineage": source,
        },
        {
            "label": "Zone rate",
            "definition": "Pitches in Statcast zones 1 through 9 divided by all reviewed pitches.",
            "formula": "SUM(in_zone_count) / SUM(pitch_count)",
            "componentIds": ["zone-rate", "pitcher-table"],
            "sourceLineage": source,
        },
        {
            "label": "Whiff rate",
            "definition": "Swinging strikes divided by swings. Called strikes and taken pitches are excluded.",
            "formula": "SUM(whiff_count) / SUM(swing_count)",
            "componentIds": ["whiff-rate", "outcome-rates", "velocity-whiff-profile", "pitcher-table"],
            "sourceLineage": source,
        },
        {
            "label": "Chase rate",
            "definition": "Out-of-zone swings divided by pitches outside Statcast zones 1 through 9.",
            "formula": "SUM(chase_count) / (SUM(pitch_count) - SUM(in_zone_count))",
            "componentIds": ["chase-rate", "outcome-rates", "pitcher-table"],
            "sourceLineage": source,
        },
        {
            "label": "Hard-hit rate",
            "definition": "Batted balls with launch speed of at least 95 mph divided by batted-ball events with measured exit velocity; missing measurements are excluded.",
            "formula": "SUM(hard_hit_count) / SUM(measured_batted_ball_count)",
            "componentIds": ["hard-hit-rate", "outcome-rates", "pitcher-table"],
            "sourceLineage": source,
        },
        {
            "label": "Average velocity",
            "definition": "Pitch-count-weighted mean Statcast release speed in miles per hour.",
            "formula": "SUM(velocity_total) / SUM(velocity_count)",
            "componentIds": ["velocity-whiff-profile", "pitcher-table"],
            "sourceLineage": source,
        },
    ]


def location_metric_definitions() -> list[dict]:
    return [
        {
            "label": "Location density",
            "definition": "Reviewed regular-season pitches counted in quarter-foot horizontal and vertical plate-location bins.",
            "formula": "SUM(pitch_count) by plate_x_bin and plate_z_bin",
            "componentIds": ["location-density"],
            "sourceLineage": [
                {"tables": ["silver.fact_pitch"], "files": ["database/mlb_pitch_analytics.duckdb"]}
            ],
        }
    ]


def reviewed_rows(connection: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    frame = connection.execute(sql).fetchdf()
    frame = frame.astype(object).where(frame.notna(), None)
    return frame.to_dict(orient="records")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dataframe_rows(frame: pd.DataFrame) -> list[dict]:
    prepared = frame.copy()
    for column in prepared.columns:
        if pd.api.types.is_datetime64_any_dtype(prepared[column]):
            prepared[column] = prepared[column].dt.strftime("%Y-%m-%d")
    return json.loads(prepared.to_json(orient="records", date_format="iso"))


def prediction_leaderboard_rows(outputs_dir: Path) -> list[dict]:
    path = outputs_dir / "predictions" / "model_leaderboards.csv"
    frame = pd.read_csv(path)
    return dataframe_rows(frame.sort_values(["target_key", "entity_type", "rank"]))


def latest_pitch_prediction_rows(outputs_dir: Path, rows_per_target: int = 250) -> list[dict]:
    frames = []
    for target_key in ("whiff", "hard_hit"):
        path = outputs_dir / "predictions" / f"{target_key}_test_predictions.parquet"
        frame = pd.read_parquet(path)
        frame = frame.sort_values(
            ["game_date", "game_pk", "pitch_id"], ascending=[False, False, False]
        ).head(rows_per_target)
        frame["predicted_probability_display"] = frame["predicted_probability"].map(
            lambda value: f"{value:.1%}"
        )
        frame["actual_outcome"] = frame["actual_event"].map(
            {1: "Whiff", 0: "Contact"}
            if target_key == "whiff"
            else {1: "Hard hit", 0: "Not hard hit"}
        )
        frame["actual_minus_expected_pp"] = frame["actual_minus_expected"] * 100.0
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    return dataframe_rows(
        combined.sort_values(
            ["target_key", "game_date", "game_pk", "pitch_id"],
            ascending=[True, False, False, False],
        )
    )


def fantasy_pitcher_radar_rows(outputs_dir: Path) -> list[dict]:
    path = outputs_dir / "fantasy" / "pitcher_fantasy_radar.csv"
    frame = pd.read_csv(path)
    return dataframe_rows(
        frame.sort_values(["window_days", "profile_key", "rank"])
    )


def matchup_stream_planner_rows(outputs_dir: Path) -> list[dict]:
    path = outputs_dir / "fantasy" / "matchup_stream_planner.csv"
    frame = pd.read_csv(path)
    return dataframe_rows(
        frame.sort_values(["profile_key", "game_datetime_utc", "stream_score"], na_position="last")
    )


def model_evaluation_rows(outputs_dir: Path, matchup_coverage: dict[str, float]) -> list[dict]:
    rows = []
    for target_key, target_label in (("whiff", "Whiff"), ("hard_hit", "Hard hit")):
        manifest = load_json(outputs_dir / "models" / f"{target_key}_model_metrics.json")
        baseline_loss = manifest["metrics"]["smoothed_group_baseline"]["test"]["log_loss"]
        champion = manifest["champion"]
        champion_base_model = manifest.get("champion_base_model", champion)
        calibration_accepted = bool(manifest.get("probability_calibration", {}).get("accepted", False))
        shortlist = {
            "smoothed_group_baseline",
            "hist_gradient_boosting_base",
            "hist_gradient_boosting_rolling_form",
            "hist_gradient_boosting_rolling_form_pitch_type",
            "hist_gradient_boosting_rolling_form_recent",
            "hist_gradient_boosting_rolling_form_recent_pitch_type",
            "hist_gradient_boosting_tuned_pitch_type",
            "hist_gradient_boosting_tuned_pitch_type_matchup",
            champion,
        }
        for model_name, split_metrics in manifest["metrics"].items():
            if "test" not in split_metrics:
                continue
            metrics = split_metrics["test"]
            observed_key = "whiff_rate" if target_key == "whiff" else "hard_hit_rate"
            predicted_key = "predicted_whiff_rate" if target_key == "whiff" else "predicted_hard_hit_rate"
            label = MODEL_LABELS.get(model_name, model_name.replace("_", " ").title())
            rows.append(
                {
                    "target": target_label,
                    "target_key": target_key,
                    "model": model_name,
                    "model_label": label,
                    "display_label": f"{target_label} · {label}",
                    "status": "Champion" if model_name == champion else "Candidate",
                    "is_champion": model_name == champion,
                    "is_champion_base": model_name == champion_base_model,
                    "probability_calibration_accepted": calibration_accepted,
                    "is_shortlist": model_name in shortlist,
                    "test_rows": metrics["rows"],
                    "observed_rate": metrics[observed_key],
                    "predicted_rate": metrics[predicted_key],
                    "log_loss": metrics["log_loss"],
                    "brier_score": metrics["brier_score"],
                    "roc_auc": metrics["roc_auc"],
                    "average_precision": metrics["average_precision"],
                    "expected_calibration_error": metrics["expected_calibration_error"],
                    "log_loss_reduction_pct": 100.0 * (baseline_loss - metrics["log_loss"]) / baseline_loss,
                    "matchup_history_coverage": matchup_coverage[target_key],
                    "test_start": manifest["split"]["test_start"],
                    "test_end": manifest["split"]["test_end"],
                    "generated_at_utc": manifest["generated_at_utc"],
                }
            )
    return rows


def model_calibration_rows(outputs_dir: Path) -> list[dict]:
    rows = []
    for target_key, target_label in (("whiff", "Whiff"), ("hard_hit", "Hard hit")):
        manifest = load_json(outputs_dir / "models" / f"{target_key}_model_metrics.json")
        selected_models = {manifest["champion"]}
        if target_key == "whiff" and manifest.get("champion_base_model"):
            selected_models.add(manifest["champion_base_model"])
        csv_path = outputs_dir / "models" / f"{target_key}_model_calibration.csv"
        with csv_path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                if row["split"] != "test" or row["model"] not in selected_models:
                    continue
                calibrated = (
                    target_key == "whiff"
                    and row["model"] == manifest["champion"]
                    and row["model"] != manifest.get("champion_base_model")
                )
                series = (
                    "Whiff · calibrated champion" if calibrated
                    else f"{target_label} · {'raw champion' if target_key == 'whiff' else 'champion'}"
                )
                rows.append(
                    {
                        "target": target_label,
                        "series": series,
                        "model": row["model"],
                        "bin": int(row["bin"]),
                        "rows": int(row["rows"]),
                        "predicted_rate": float(row["predicted_rate"]),
                        "observed_rate": float(row["observed_rate"]),
                        "is_reference": False,
                    }
                )
    rows.extend(
        {
            "target": "Reference",
            "series": "Ideal calibration",
            "model": "ideal_calibration",
            "bin": index,
            "rows": None,
            "predicted_rate": index / 10,
            "observed_rate": index / 10,
            "is_reference": True,
        }
        for index in range(11)
    )
    return sorted(rows, key=lambda row: (row["series"], row["predicted_rate"]))


def starter_forecast_queries(outputs_dir: Path, mode: str) -> dict:
    specifications = {
        "starter_live_monitor": ("live_monitor.csv", "Live first-forecast outcomes by archived model version; excludes historical backtests", "starter-live-monitor"),
        "pitcher_comparison": ("comparison.csv", "Pitcher comparison: recent observed skill and next-start baseline", "pitcher-comparison"),
        "starter_forecasts": ("upcoming.csv", "Timestamped pregame strikeout baselines for confirmed probable starters", "starter-forecast-table"),
        "starter_forecast_evaluation": ("evaluation.csv", "Fixed out-of-time evaluation of pregame starter strikeout baselines", "starter-forecast-evaluation"),
        "starter_forecast_history": ("forecast_history.csv", "First archived pregame forecast per game and pitcher, with observed outcomes", "starter-forecast-history"),
    }
    queries = {
        key: {"rows": dataframe_rows(pd.read_csv(outputs_dir / "forecast" / filename)) if mode == "full" else [],
              "source": {"label": label, "tables": ["silver.fact_pitch", "silver.fact_game_context"],
                         "files": [f"outputs/forecast/{filename}", "outputs/forecast/model_manifest.json"],
                         "filters": ["Pregame features use completed games from earlier calendar dates only.",
                                     "Model selected on early validation; interval calibrated on separate validation tail.",
                                     "Retrospective backtest covers observed first pitchers, not historical probable-starter announcements.",
                                     "Prediction intervals target 80% empirical coverage; future coverage is not guaranteed.",
                                     "No lineup, injury or weather adjustments; lack of a confirmed future start is not a zero prediction."],
                         "metricDefinitions": [{"label": "Next-start strikeouts", "definition": label,
                                                "formula": "recent_starts = (K in last 5 starts + 3 * training mean K per start) / (prior start count + 3). Alternative baselines: training league mean; projected BF * smoothed K rate * opponent adjustment. MAE = mean(abs(predicted K - actual K)).",
                                                "componentIds": [component],
                                                "sourceLineage": [{"files": [f"outputs/forecast/{filename}", "outputs/forecast/model_manifest.json"]}]}]}}
        for key, (filename, label, component) in specifications.items()
    }
    queries["pitcher_comparison"]["source"]["files"].extend([
        "outputs/fantasy/pitcher_fantasy_radar.csv", "outputs/forecast/upcoming.csv"])
    archives = sorted({row["archive_file"] for row in queries["starter_forecast_history"]["rows"] if row.get("archive_file")})
    queries["starter_forecast_history"]["source"]["files"].extend(archives)
    queries["starter_live_monitor"]["source"]["files"].extend(["outputs/forecast/forecast_history.csv", *archives])
    queries["starter_live_monitor"]["source"]["metricDefinitions"] = [{
        "label": "Live forecast monitoring", "definition": "Observed first archived predictions grouped by model version; pending and excluded outcomes never enter error denominators.",
        "formula": "MAE=mean(abs(predicted-actual)); RMSE=sqrt(mean((predicted-actual)^2)); bias=mean(predicted-actual). Coverage uses only observed rows with valid archived bounds. Fewer than 30 observations is labeled limited sample; 30 is a display threshold, not statistical validation.",
        "componentIds": ["starter-live-monitor"]}]
    return queries


def hitter_queries(outputs_dir: Path, mode: str) -> dict:
    directory = outputs_dir / 'hitters'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8')) if mode == 'full' else {}
    evaluation_manifest_path = directory / 'evaluation_manifest.json'
    evaluation_manifest = json.loads(evaluation_manifest_path.read_text(encoding='utf-8')) if mode == 'full' and evaluation_manifest_path.exists() else {}
    definitions = {
        'fantasy_hitters': ('radar.json', 'Daily 5x5 hitter opportunity and contact evidence',
                            ['hitters-board', 'hitters-detail', 'hitters-impact', 'hitters-table']),
        'hitter_schedule': ('schedule.json', 'MLB games still scheduled at snapshot time', ['hitters-schedule', 'hitters-board', 'hitters-impact']),
        'hitter_validation': ('evaluation.json', 'Chronological conditional-rate diagnostic', ['hitters-validation']),
        'hitter_metadata': ('manifest.json', 'Separate statistics, roster and schedule cutoffs', ['hitters-method']),
    }
    result = {}
    for key, (filename, label, components) in definitions.items():
        rows = json.loads((directory / filename).read_text(encoding='utf-8')) if mode == 'full' else []
        if key == 'hitter_metadata':
            rows = [{k: v for k, v in manifest.items() if k not in ('sources', 'caveats', 'coverage')}] if manifest else []
        result[key] = {'rows': rows, 'source': {
            'label': label, 'tables': ['bronze.raw_statcast'],
            'files': [f'outputs/hitters/{filename}', 'outputs/hitters/schedule.json', 'outputs/hitters/manifest.json', 'src/build_fantasy_hitters.py'],
            'urls': [s['url'] for s in (evaluation_manifest if key == 'hitter_validation' else manifest).get('sources', [])] + ['https://baseballsavant.mlb.com/csv-docs'],
            'filters': manifest.get('caveats', []) + ['5x5 categories; daily lineup changes. No fantasy ownership feed.'],
            'metricDefinitions': [{'label': label, 'componentIds': components,
                'definition': 'Official R, HR, RBI, SB, H and AB through the completed Statcast cutoff; tracked quality has its own denominators.',
                'formula': 'Default pace = season count/PA (H/AB for AVG). Optional pace = (last30 count + 100 * prior)/(last30 PA or AB + 100); prior=(pre-window season count + 200*league rate)/(pre-window season PA or AB+200). Planned PA = selected unstarted games * last14 current-team PA/team game (max 5). The player row schedule_json contains the joined reviewed team schedule. AVG impact = planned H - target AVG * planned AB. Smoothing constants are heuristics, not validated stabilization thresholds.',
                'sourceLineage': [{'files': [f'outputs/hitters/{filename}']}]}]}}
        if key == 'hitter_validation':
            result[key]['source']['files'].append('outputs/hitters/evaluation_manifest.json')
            result[key]['source']['tables'] = []
            result[key]['source']['metricDefinitions'][0].update(
                definition='Three chronological weeks; candidate membership is based only on prior statistics. Results are conditional on observed future playing time.',
                formula='MAE = mean(abs(prior rate * actual future PA or AB - observed next-week count)). Eligibility uses season PA >=100 and recent30 PA >=30 at each origin; zero-future-PA players are excluded from this conditional diagnostic. No end-to-end lineup or waiver benefit is established.')
    return result


def build_snapshot(database_path: Path, outputs_dir: Path) -> dict:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        summary_rows = reviewed_rows(connection, PITCH_SUMMARY_SQL)
        location_rows = reviewed_rows(connection, LOCATION_DENSITY_SQL)
        mode, start_season, end_season, configured_start, configured_end = connection.execute(
            "SELECT mode, start_season, end_season, start_date, end_date FROM metadata.pipeline_config"
        ).fetchone()
        actual_start, actual_end = connection.execute(
            "SELECT MIN(game_date), MAX(game_date) FROM silver.fact_pitch"
        ).fetchone()
        whiff_matchup_coverage = connection.execute(
            "SELECT COUNT(matchup_whiff_rate_prior_30_swings)::DOUBLE / COUNT(*) FROM gold.training_pitch_whiff"
        ).fetchone()[0]
        hard_hit_matchup_coverage = connection.execute(
            "SELECT COUNT(matchup_hard_hit_rate_prior_20_batted_balls)::DOUBLE / COUNT(*) FROM gold.training_pitch_hard_hit"
        ).fetchone()[0]
    finally:
        connection.close()

    matchup_coverage = {
        "whiff": float(whiff_matchup_coverage),
        "hard_hit": float(hard_hit_matchup_coverage),
    }
    evaluation_rows = model_evaluation_rows(outputs_dir, matchup_coverage) if mode == "full" else []
    calibration_rows = model_calibration_rows(outputs_dir) if mode == "full" else []
    leaderboard_rows = prediction_leaderboard_rows(outputs_dir) if mode == "full" else []
    prediction_rows = latest_pitch_prediction_rows(outputs_dir) if mode == "full" else []
    fantasy_rows = fantasy_pitcher_radar_rows(outputs_dir) if mode == "full" else []
    stream_planner_rows = matchup_stream_planner_rows(outputs_dir) if mode == "full" else []

    season_label = str(start_season) if start_season == end_season else f"{start_season}-{end_season}"
    caveats = [
        f"Regular-season games only; configured seasons {season_label}.",
        f"Configured window: {configured_start} through {configured_end}.",
        f"Latest reviewed game date available in this snapshot: {actual_end}.",
    ]
    if mode == "sample":
        caveats.append("The sample is descriptive and is not a full-season benchmark.")
    else:
        caveats.append("The active season stops at the latest complete day and excludes postseason games.")

    return {
        "id": APP_ID,
        "surface": "dashboard",
        "title": "MLB Pitch Intelligence & Fantasy Radar",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "reviewed",
        "filters": [
            {"id": "season", "label": "Season", "field": "season", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID, LOCATION_QUERY_ID]},
            {"id": "pitcher", "label": "Pitcher", "field": "pitcher_name", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID]},
            {"id": "team", "label": "Team", "field": "pitcher_team", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID]},
            {"id": "batterSide", "label": "Batter side", "field": "batter_stand", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID, LOCATION_QUERY_ID]},
            {"id": "countState", "label": "Count state", "field": "count_state", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID, LOCATION_QUERY_ID]},
            {"id": "pitchFamily", "label": "Pitch family", "field": "pitch_family", "defaultValue": "all", "queryIds": [SUMMARY_QUERY_ID, LOCATION_QUERY_ID]},
        ],
        "queries": {
            **starter_forecast_queries(outputs_dir, mode),
            **hitter_queries(outputs_dir, mode),
            SUMMARY_QUERY_ID: {
                "rows": summary_rows,
                "reportingField": "last_game_date",
                "source": {
                    "label": f"Reviewed {mode} Statcast pitch summary",
                    "sql": PITCH_SUMMARY_SQL,
                    "tables": ["silver.fact_pitch"],
                    "files": ["database/mlb_pitch_analytics.duckdb"],
                    "filters": caveats,
                    "metricDefinitions": summary_metric_definitions(),
                },
            },
            LOCATION_QUERY_ID: {
                "rows": location_rows,
                "source": {
                    "label": f"Reviewed {mode} Statcast plate-location density",
                    "sql": LOCATION_DENSITY_SQL,
                    "tables": ["silver.fact_pitch"],
                    "files": ["database/mlb_pitch_analytics.duckdb"],
                    "filters": caveats + ["Pitcher and team filters do not apply to the location-density query."],
                    "metricDefinitions": location_metric_definitions(),
                },
            },
            MODEL_EVALUATION_QUERY_ID: {
                "rows": evaluation_rows,
                "reportingField": "test_end",
                "source": {
                    "label": "Reviewed chronological model evaluation",
                    "tables": ["gold.training_pitch_whiff", "gold.training_pitch_hard_hit"],
                    "files": [
                        "outputs/models/whiff_model_metrics.json",
                        "outputs/models/hard_hit_model_metrics.json",
                    ],
                    "filters": [
                        "2025 trains the models; early 2026 is validation; later 2026 is untouched test.",
                        "Champion selection uses validation, never test performance.",
                        "Whiff uses swings; hard hit uses batted-ball events.",
                        (f"Untouched test window: {evaluation_rows[0]['test_start']} through {evaluation_rows[0]['test_end']}." if evaluation_rows else "Model evaluation is unavailable in sample mode."),
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Log-loss reduction",
                            "definition": "Percent reduction in untouched-test log loss versus the target-specific smoothed group baseline.",
                            "formula": "100 * (baseline_log_loss - model_log_loss) / baseline_log_loss",
                            "componentIds": ["model-lift", "whiff-model-champion", "hard-hit-model-champion"],
                            "sourceLineage": [{"files": ["outputs/models/whiff_model_metrics.json", "outputs/models/hard_hit_model_metrics.json"]}],
                        },
                        {
                            "label": "Expected calibration error",
                            "definition": "Weighted absolute gap between predicted and observed event rates across ten probability bins.",
                            "formula": "SUM(bin_share * ABS(observed_rate - predicted_rate))",
                            "componentIds": ["whiff-calibration-status", "model-calibration"],
                            "sourceLineage": [{"files": ["outputs/models/whiff_model_calibration.csv", "outputs/models/hard_hit_model_calibration.csv"]}],
                        },
                    ],
                },
            },
            MODEL_CALIBRATION_QUERY_ID: {
                "rows": calibration_rows,
                "source": {
                    "label": "Reviewed untouched-test calibration bins",
                    "tables": ["gold.training_pitch_whiff", "gold.training_pitch_hard_hit"],
                    "files": [
                        "outputs/models/whiff_model_calibration.csv",
                        "outputs/models/hard_hit_model_calibration.csv",
                    ],
                    "filters": [
                        "Ten equal-width predicted-probability bins; empty bins are omitted.",
                        "The diagonal reference is a computed identity line where predicted rate equals observed rate.",
                        "Whiff Platt calibration is fitted on validation only and evaluated on untouched test.",
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Calibration curve",
                            "definition": "Observed event rate versus mean predicted probability within each populated test bin.",
                            "formula": "AVG(target) and AVG(prediction) by predicted-probability bin",
                            "componentIds": ["model-calibration"],
                            "sourceLineage": [{"files": ["outputs/models/whiff_model_calibration.csv", "outputs/models/hard_hit_model_calibration.csv"]}],
                        }
                    ],
                },
            },
            MODEL_LEADERBOARD_QUERY_ID: {
                "rows": leaderboard_rows,
                "reportingField": "last_game_date",
                "source": {
                    "label": "Reviewed champion-model player and pitch-type rankings",
                    "tables": ["gold.training_pitch_whiff", "gold.training_pitch_hard_hit"],
                    "files": [
                        "outputs/predictions/model_leaderboards.csv",
                        "outputs/predictions/prediction_manifest.json",
                    ],
                    "filters": [
                        "Rankings use only the untouched chronological test window.",
                        "Whiff rankings require at least 100 swings per pitcher and 500 swings per pitch type.",
                        "Hard-hit rankings require at least 50 batted-ball events per pitcher and 200 per pitch type.",
                        "Positive model edge means better than the target-wide expected rate: more whiffs or fewer hard hits allowed.",
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Model-expected rate",
                            "definition": "Mean champion-model probability across the entity's eligible test events.",
                            "formula": "AVG(predicted_probability)",
                            "componentIds": ["model-leaderboard-chart", "model-leaderboard-table"],
                            "sourceLineage": [{"files": ["outputs/predictions/model_leaderboards.csv"]}],
                        },
                        {
                            "label": "Model edge",
                            "definition": "Target-direction-adjusted difference from the test-window average expected rate, in percentage points.",
                            "formula": "whiff: entity_expected - overall_expected; hard hit: overall_expected - entity_expected",
                            "componentIds": ["model-leaderboard-chart", "model-leaderboard-table"],
                            "sourceLineage": [{"files": ["outputs/predictions/model_leaderboards.csv"]}],
                        },
                    ],
                },
            },
            PITCH_PREDICTIONS_QUERY_ID: {
                "rows": prediction_rows,
                "reportingField": "game_date",
                "source": {
                    "label": "Latest champion-model pitch scores from the untouched test window",
                    "tables": ["gold.training_pitch_whiff", "gold.training_pitch_hard_hit"],
                    "files": [
                        "outputs/predictions/whiff_test_predictions.parquet",
                        "outputs/predictions/hard_hit_test_predictions.parquet",
                    ],
                    "filters": [
                        "The dashboard embeds the latest 250 scored events per target; the parquet artifacts retain every test row.",
                        "Whiff probability is conditional on a recorded swing; hard-hit probability is conditional on a batted-ball event.",
                        "These are post-release pitch-quality scores, not pre-pitch forecasts or game-winner predictions.",
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Pitch event probability",
                            "definition": "Champion-model probability for the target-specific eligible event.",
                            "formula": "calibrated whiff champion or validation-selected hard-hit champion predict_proba",
                            "componentIds": ["latest-pitch-predictions"],
                            "sourceLineage": [{"files": ["outputs/predictions/whiff_test_predictions.parquet", "outputs/predictions/hard_hit_test_predictions.parquet"]}],
                        }
                    ],
                },
            },
            FANTASY_RADAR_QUERY_ID: {
                "rows": fantasy_rows,
                "reportingField": "window_end",
                "source": {
                    "label": "Reviewed recent-form fantasy pitching radar",
                    "tables": ["silver.fact_pitch", "gold.training_pitch_whiff", "gold.training_pitch_hard_hit"],
                    "files": [
                        "outputs/fantasy/pitcher_fantasy_radar.csv",
                        "outputs/fantasy/fantasy_radar_manifest.json",
                        "outputs/predictions/whiff_recent_predictions.parquet",
                        "outputs/predictions/hard_hit_recent_predictions.parquet",
                    ],
                    "filters": [
                        "Skills-based fantasy decision support, not projected fantasy points or a roster-availability feed.",
                        "Profiles combine model-expected whiff and hard-hit suppression with recent K-BB%, chase rate, and walk suppression.",
                        "Seven-, fourteen-, and thirty-day windows use visible workload and model-score minimums.",
                        "Wins, saves, earned runs, official innings pitched, opponent schedules, and roster availability are not available in this source.",
                        "Role is inferred from recent pitches per game and is not an official roster designation.",
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Fantasy skill signal",
                            "definition": "A zero-to-100 weighted percentile score for recent pitching skills. It is a comparison signal, not projected league points.",
                            "formula": "Roto balance: 25% expected whiff + 25% expected hard-hit suppression + 25% K-BB + 15% chase + 10% walk suppression; alternate profiles change these documented weights.",
                            "componentIds": ["fantasy-insight-board", "fantasy-qualified-pool", "fantasy-high-skill-pool", "fantasy-rising-pool", "fantasy-starter-pool", "fantasy-radar-chart", "fantasy-radar-table"],
                            "sourceLineage": [{"files": ["outputs/fantasy/pitcher_fantasy_radar.csv", "outputs/fantasy/fantasy_radar_manifest.json"]}],
                        },
                        {
                            "label": "Expected whiff rate",
                            "definition": "Mean calibrated champion-model whiff probability across recorded swings in the selected recent window.",
                            "formula": "AVG(calibrated_whiff_probability)",
                            "componentIds": ["fantasy-radar-table"],
                            "sourceLineage": [{"files": ["outputs/predictions/whiff_recent_predictions.parquet"]}],
                        },
                        {
                            "label": "Expected hard-hit rate allowed",
                            "definition": "Mean hard-hit champion probability across batted-ball events in the selected recent window; lower is better.",
                            "formula": "AVG(hard_hit_probability)",
                            "componentIds": ["fantasy-radar-table"],
                            "sourceLineage": [{"files": ["outputs/predictions/hard_hit_recent_predictions.parquet"]}],
                        },
                        {
                            "label": "Underlying skill gap",
                            "definition": "A research flag comparing model-expected whiff and hard-hit rates with observed rates in the same window. Positive means the two model expectations are collectively stronger than the recent observed results.",
                            "formula": "0.5 * ((expected_whiff_rate - observed_whiff_rate) + (observed_hard_hit_rate - expected_hard_hit_rate)) * 100",
                            "componentIds": ["fantasy-insight-board", "fantasy-radar-table"],
                            "sourceLineage": [{"files": ["outputs/fantasy/pitcher_fantasy_radar.csv"]}],
                        },
                        {
                            "label": "Sample strength",
                            "definition": "The smallest qualifying-event multiple across pitches, batters faced, scored swings, and scored batted-ball events. Labels describe evidence volume, not model certainty.",
                            "formula": "MIN(actual_count / window_minimum) across four qualification gates",
                            "componentIds": ["fantasy-insight-board", "fantasy-radar-table"],
                            "sourceLineage": [{"files": ["outputs/fantasy/pitcher_fantasy_radar.csv", "outputs/fantasy/fantasy_radar_manifest.json"]}],
                        },
                    ],
                },
            },
            STREAM_PLANNER_QUERY_ID: {
                "rows": stream_planner_rows,
                "reportingField": "game_date",
                "source": {
                    "label": "Upcoming matchup-aware fantasy pitching stream planner",
                    "tables": ["silver.fact_pitch", "silver.fact_game_context"],
                    "files": [
                        "outputs/fantasy/matchup_stream_planner.csv",
                        "outputs/fantasy/matchup_stream_planner_manifest.json",
                        "outputs/fantasy/pitcher_fantasy_radar.csv",
                        "data/game_context/mlb_venues.parquet",
                    ],
                    "urls": [
                        "https://statsapi.mlb.com/api/v1/schedule",
                        "https://api.open-meteo.com/v1/forecast",
                        "https://support.espn.com/hc/en-us/articles/360003946651-Scoring-Formats",
                        "https://help.yahoo.com/kb/fantasy-baseball/SLN6785.html",
                    ],
                    "filters": [
                        "Upcoming seven-day regular-season schedule from MLB Stats API; completed and in-progress games are omitted.",
                        "Probable pitchers are displayed only when present in the schedule response; TBD rotation slots are never inferred.",
                        "Pitcher skill uses the current 14-day fantasy radar profile; opponent tendencies use the most recent 30 complete data days.",
                        "Weather is the Open-Meteo hourly forecast nearest scheduled first pitch and is used only as a risk flag.",
                        "League Strategy Lab is a client-side scenario overlay: Categories uses the selected skill profile; Points skill proxy blends 60% selected profile with 40% strikeout upside before an optional risk haircut.",
                        "Player Pool Manager labels are user-supplied and stored only in local browser storage; they filter the workspace without changing reviewed source rows or model scores.",
                        "Roster availability, league rules, confirmed roof status, and late rotation changes remain outside this source.",
                    ],
                    "metricDefinitions": [
                        {
                            "label": "Stream score",
                            "definition": "A zero-to-100 research ranking for confirmed probable pitchers with a qualifying recent skill score. It is not projected fantasy points or a start guarantee.",
                            "formula": "65% recent pitcher skill + 25% opponent batting tendency + 10% historical park contact suppression; optional context is renormalized when unavailable",
                            "componentIds": ["stream-confirmed-probables", "stream-scored-matchups", "stream-strong-options", "stream-planner-chart", "stream-planner-table"],
                            "sourceLineage": [{"files": ["outputs/fantasy/matchup_stream_planner.csv", "outputs/fantasy/matchup_stream_planner_manifest.json"]}],
                        },
                        {
                            "label": "Personalized fit",
                            "definition": "A zero-to-100 scenario ranking layered on the unchanged Stream Score. It helps shortlist research under selected league and risk preferences; it is not projected fantasy points.",
                            "formula": "Categories: selected-profile Stream Score. Points skill proxy: 60% selected-profile score + 40% strikeout-upside score. Low risk subtracts 8/4/3 for elevated-rain/roof-decision/weather-watch, 4/2 for qualified/solid sample, and 3 for cooling. Balanced risk subtracts 4/2/1, 2/1, and 1 respectively. High risk subtracts zero.",
                            "componentIds": ["stream-strong-options", "stream-planner-chart", "stream-planner-table"],
                            "sourceLineage": [{"files": ["outputs/fantasy/matchup_stream_planner.csv"]}],
                        },
                        {
                            "label": "Player pool status",
                            "definition": "A user-maintained browser-local label for an upcoming pitcher: Available, My roster, Watchlist, Unavailable, or Unclassified. It is not sourced from a fantasy platform.",
                            "formula": "User selection keyed by MLB pitcher ID in local browser storage; default is Unclassified",
                            "componentIds": ["stream-player-pool", "stream-planner-chart", "stream-planner-table"],
                        },
                        {
                            "label": "Opponent matchup signal",
                            "definition": "Pitcher-favorable percentile blend of the opponent's recent strikeout, walk, and hard-hit batting rates.",
                            "formula": "50% strikeout favorability + 25% walk suppression favorability + 25% hard-hit suppression favorability",
                            "componentIds": ["stream-planner-chart", "stream-planner-table"],
                            "sourceLineage": [{"tables": ["silver.fact_pitch"]}],
                        },
                        {
                            "label": "Weather risk",
                            "definition": "Forecast and roof-context flag nearest scheduled first pitch. It does not change the base Stream Score, but low- and balanced-risk Personalized Fit scenarios can apply a transparent haircut.",
                            "formula": "Open-Meteo precipitation probability thresholds with MLB venue roof type",
                            "componentIds": ["stream-weather-flags", "stream-planner-table"],
                            "sourceLineage": [{"urls": ["https://api.open-meteo.com/v1/forecast"], "files": ["data/game_context/mlb_venues.parquet"]}],
                        },
                    ],
                },
            },
        },
        "coverage": {
            "configuredStart": str(configured_start),
            "configuredEnd": str(configured_end),
            "actualStart": str(actual_start),
            "actualEnd": str(actual_end),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reviewed data for the MLB dashboard.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    output_path = project_path(config["paths"].get("dashboard_snapshot", "dashboard/src/data.json"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(database_path, outputs_dir)
    temporary = output_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(output_path)
    print(
        "Dashboard snapshot: "
        f"{len(snapshot['queries'][SUMMARY_QUERY_ID]['rows']):,} summary rows, "
        f"{len(snapshot['queries'][LOCATION_QUERY_ID]['rows']):,} location rows -> {output_path}"
        f"; {len(snapshot['queries'][MODEL_EVALUATION_QUERY_ID]['rows']):,} model rows"
        f"; {len(snapshot['queries'][MODEL_CALIBRATION_QUERY_ID]['rows']):,} calibration rows"
        f"; {len(snapshot['queries'][MODEL_LEADERBOARD_QUERY_ID]['rows']):,} leaderboard rows"
        f"; {len(snapshot['queries'][PITCH_PREDICTIONS_QUERY_ID]['rows']):,} latest prediction rows"
        f"; {len(snapshot['queries'][FANTASY_RADAR_QUERY_ID]['rows']):,} fantasy radar rows"
        f"; {len(snapshot['queries'][STREAM_PLANNER_QUERY_ID]['rows']):,} stream planner rows"
    )


if __name__ == "__main__":
    from src.artifact_lineage import run_versioned
    run_versioned("build_dashboard_snapshot", main)
