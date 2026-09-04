from __future__ import annotations

from pathlib import Path

import nbformat as nbf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "notebooks" / "02_whiff_model_evaluation.ipynb"


def main() -> None:
    notebook = nbf.v4.new_notebook()
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook["metadata"]["language_info"] = {"name": "python", "version": "3"}
    notebook["cells"] = [
        nbf.v4.new_markdown_cell(
            """# MLB Whiff Probability Model Audit

## TL;DR

The tuned, Platt-calibrated rolling-form plus pitch-type and matchup histogram
gradient boosting model is the current champion. On the untouched June 12 to
September 1, 2026 test period, its log loss is **0.42224** versus **0.51854**
for the smoothed pitch-type/count baseline, an **18.6%** improvement. Calibration
improves the raw champion's log loss from **0.42359** and expected calibration
error from **0.0161** to **0.0108**, while ROC-AUC remains **0.7952**.

New 14-day recent-form features and tuned candidates were evaluated through the
same chronological validation gate. The tuned candidate was promoted; the
14-day candidates were not. Weather also remains outside the champion scorer.

This is a post-release pitch-quality model: it estimates `P(whiff | swing)` after
the pitch has been tracked. It is not a pre-pitch forecast and does not predict
game winners."""
        ),
        nbf.v4.new_markdown_cell(
            """## Context and Methods

The source is `gold.training_pitch_whiff` in
`database/mlb_pitch_analytics.duckdb`. The mart contains one row per recorded
swing and excludes same-pitch result text, batted-ball outcomes, run-expectancy
changes, post-pitch scores, and future rest fields.

### Key assumptions

- 2025 is the training period.
- March 25 through June 11, 2026 is validation; June 12 through September 1 is
  the untouched chronological test.
- The first 70% of validation fits the initial Platt calibrator and the final
  30% is its acceptance check. After acceptance, it refits on all validation
  rows before one untouched test evaluation.
- Current-pitch velocity, movement, release, and location are valid only because
  the prediction horizon is post-release pitch quality.
- Rolling history is frozen at the start of each player-game. No current-game
  event is included in its own form features.
- Candidate features include 14- and 30-day player form, pitch-type history, and
  pitcher-batter matchup history. Each must win chronological validation.
- `tracking_regime` identifies the 2026 Statcast/ABS alignment change.

Field definitions: [Baseball Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs)."""
        ),
        nbf.v4.new_code_cell(
            """from pathlib import Path
import json

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

project_root = Path.cwd()
if not (project_root / "database" / "mlb_pitch_analytics.duckdb").exists():
    project_root = Path.cwd().parent

database_path = project_root / "database" / "mlb_pitch_analytics.duckdb"
model_dir = project_root / "outputs" / "models"
database_path, model_dir"""
        ),
        nbf.v4.new_markdown_cell("## Data"),
        nbf.v4.new_code_cell(
            """connection = duckdb.connect(str(database_path), read_only=True)
profile = connection.execute(
    '''
    SELECT
        season,
        COUNT(*) AS swing_rows,
        SUM(target_whiff) AS whiffs,
        AVG(target_whiff) AS whiff_rate,
        COUNT(temperature_f)::DOUBLE / COUNT(*) AS temperature_coverage,
        COUNT(wind_speed_mph)::DOUBLE / COUNT(*) AS wind_coverage,
        MIN(game_date) AS first_date,
        MAX(game_date) AS last_date
    FROM gold.training_pitch_whiff
    GROUP BY season
    ORDER BY season
    '''
).fetchdf()
connection.close()
profile"""
        ),
        nbf.v4.new_markdown_cell(
            """## Results

The cells below read the checked-in artifacts produced by
`python -m src.train_whiff_model`. Training is intentionally not rerun during
notebook rendering, so the audit remains fast and does not overwrite reviewed
model files."""
        ),
        nbf.v4.new_code_cell(
            """manifest = json.loads((model_dir / "whiff_model_metrics.json").read_text(encoding="utf-8"))
metric_rows = []
for model_name, split_metrics in manifest["metrics"].items():
    for split_name, values in split_metrics.items():
        metric_rows.append({"model": model_name, "split": split_name, **values})
metrics = pd.DataFrame(metric_rows)
metrics[[
    "model", "split", "rows", "log_loss", "brier_score", "roc_auc",
    "average_precision", "expected_calibration_error"
]].sort_values(["split", "log_loss"])"""
        ),
        nbf.v4.new_code_cell(
            """test_metrics = metrics[metrics["split"] == "test"].sort_values("log_loss")
fig, axes = plt.subplots(1, 2, figsize=(11, 5))
axes[0].barh(test_metrics["model"], test_metrics["log_loss"], color="#1261A0")
axes[0].set_title("Untouched 2026 test: log loss")
axes[0].set_xlabel("Lower is better")
axes[1].barh(test_metrics["model"], test_metrics["roc_auc"], color="#F28C28")
axes[1].set_title("Untouched 2026 test: ROC-AUC")
axes[1].set_xlabel("Higher is better")
plt.tight_layout()
plt.show()"""
        ),
        nbf.v4.new_code_cell(
            """monthly = pd.read_csv(model_dir / "whiff_model_monthly.csv")
champion = manifest["champion"]
champion_monthly = monthly[monthly["model"] == champion].copy()
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(champion_monthly["month"], champion_monthly["observed_whiff_rate"], marker="o", label="Observed")
ax.plot(champion_monthly["month"], champion_monthly["predicted_whiff_rate"], marker="o", label="Predicted")
ax.set_title("Champion model: observed vs predicted whiff rate")
ax.set_ylabel("Whiff rate")
ax.tick_params(axis="x", rotation=45)
ax.legend()
plt.tight_layout()
plt.show()
champion_monthly"""
        ),
        nbf.v4.new_markdown_cell(
            """## Takeaways

- The tuned rolling + pitch-type + matchup candidate won validation and became
  the raw champion.
- Validation-fitted Platt calibration reduced untouched-test log loss and ECE
  without changing ROC-AUC.
- The new 14-day feature candidates did not win validation, so the production
  scorer continues to use the validated longer-history feature set.
- Weather and matchup-only variants remain research candidates rather than
  claimed production lift.
- Dashboard fantasy rankings use the calibrated expected-whiff output as one
  skill component; they are not projected fantasy points."""
        ),
    ]
    OUTPUT_PATH.write_text(nbf.writes(notebook), encoding="utf-8")
    print(f"Notebook written: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
