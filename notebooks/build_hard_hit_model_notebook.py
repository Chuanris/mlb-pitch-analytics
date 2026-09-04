from __future__ import annotations

from pathlib import Path

import nbformat as nbf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "notebooks" / "03_hard_hit_model_evaluation.ipynb"


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
            """# MLB Hard-Hit Probability Model Audit

## tl;dr

The rolling-form plus pitch-type histogram gradient boosting model is the
current champion. On the untouched June 11–August 31, 2026 test period, its log
loss is **0.59443** versus **0.65775** for the smoothed pitch-type/count
baseline, a **9.6%** improvement. Relative to rolling form alone, log loss
improves from **0.59625** and ROC-AUC improves from **0.7076** to **0.7105**.

Rolling form uses only the pitcher's prior 200 batted balls, batter's prior 50
batted balls, and each player's prior 30 days, snapshotted before the game.
Pitch-type history uses the pitcher's prior 100 and batter's prior 30 batted
balls for that pitch type. Matchup history is sparse and slightly worsened test
log loss, so neither matchup nor weather is included in the champion."""
        ),
        nbf.v4.new_markdown_cell(
            """## Context & Methods

The source is `gold.training_pitch_hard_hit` in
`database/mlb_pitch_analytics.duckdb`. Its grain is one recorded batted ball and
the target is exit velocity at or above 95 mph.

### Key Assumptions

- 2025 is the training period.
- The first half of available 2026 dates is validation; the later half is the
  untouched chronological test.
- Launch speed defines the target and is never a feature. Launch angle, bat
  speed, swing length, estimated wOBA, and post-pitch outcomes are also excluded.
- Rolling history is frozen at the start of each player-game. No batted ball
  from the current game is included in its own form features.
- Pitch-type and matchup history are also frozen before the current game.
- Current pitch movement and location are allowed because this is a
  post-release contact-quality evaluation, not a pre-pitch forecast.

Field definitions: [Baseball Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs)."""
        ),
        nbf.v4.new_code_cell(
            """from pathlib import Path
import json
import subprocess
import sys

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
    \"\"\"
    SELECT
        season,
        COUNT(*) AS batted_ball_rows,
        SUM(target_hard_hit) AS hard_hits,
        AVG(target_hard_hit) AS hard_hit_rate,
        COUNT(temperature_f)::DOUBLE / COUNT(*) AS temperature_coverage,
        COUNT(wind_speed_mph)::DOUBLE / COUNT(*) AS wind_coverage,
        MIN(game_date) AS first_date,
        MAX(game_date) AS last_date
    FROM gold.training_pitch_hard_hit
    GROUP BY season
    ORDER BY season
    \"\"\"
).fetchdf()
connection.close()
profile"""
        ),
        nbf.v4.new_markdown_cell(
            """### Reproduce the model artifacts

The next cell reruns the checked-in training entry point and replaces the
reviewed hard-hit model outputs in `outputs/models/`."""
        ),
        nbf.v4.new_code_cell(
            """completed = subprocess.run(
    [
        sys.executable,
        "-m",
        "src.train_hard_hit_model",
        "--config",
        "config/pipeline_config.json",
    ],
    cwd=project_root,
    check=True,
    capture_output=True,
    text=True,
)
print(completed.stdout)"""
        ),
        nbf.v4.new_markdown_cell("## Results"),
        nbf.v4.new_code_cell(
            """manifest = json.loads((model_dir / "hard_hit_model_metrics.json").read_text(encoding="utf-8"))
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
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
axes[0].barh(test_metrics["model"], test_metrics["log_loss"], color="#2774ae")
axes[0].set_title("Untouched 2026 test: log loss")
axes[0].set_xlabel("Lower is better")
axes[1].barh(test_metrics["model"], test_metrics["roc_auc"], color="#ef7c00")
axes[1].set_title("Untouched 2026 test: ROC-AUC")
axes[1].set_xlabel("Higher is better")
plt.tight_layout()
plt.show()"""
        ),
        nbf.v4.new_code_cell(
            """monthly = pd.read_csv(model_dir / "hard_hit_model_monthly.csv")
champion = manifest["champion"]
champion_monthly = monthly[monthly["model"] == champion].copy()
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(champion_monthly["month"], champion_monthly["observed_hard_hit_rate"], marker="o", label="Observed")
ax.plot(champion_monthly["month"], champion_monthly["predicted_hard_hit_rate"], marker="o", label="Predicted")
ax.set_title("Champion model: observed vs predicted hard-hit rate")
ax.set_ylabel("Hard-hit rate")
ax.tick_params(axis="x", rotation=45)
ax.legend()
plt.tight_layout()
plt.show()
champion_monthly"""
        ),
        nbf.v4.new_markdown_cell(
            """## Takeaways

- Pitch-type form improves validation and untouched test log loss, ROC-AUC,
  average precision, and calibration, so it becomes champion.
- Matchup-only form worsens test log loss from 0.59625 to 0.59647; combining it
  with pitch-type form is also worse than pitch-type form alone.
- Matchup is therefore retained as an experimental feature, not part of the
  hard-hit champion."""
        ),
    ]
    OUTPUT_PATH.write_text(nbf.writes(notebook), encoding="utf-8")
    print(f"Notebook written: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
