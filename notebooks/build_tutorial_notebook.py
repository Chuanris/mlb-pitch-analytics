from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "01_pipeline_and_sql_tutorial.ipynb"


notebook = nbf.v4.new_notebook()
notebook["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.12"},
}

notebook["cells"] = [
    nbf.v4.new_markdown_cell(
        """# MLB Statcast Pipeline and SQL Tutorial

## Goal

Understand how real pitch-level Statcast data moves from raw files into an analytical database, verify that the data is trustworthy, and answer the first descriptive baseball question with SQL. This notebook does **not** predict game winners.

**Lesson dataset:** April 1–3, 2025 regular-season Statcast pitches.

**Source:** Baseball Savant via `pybaseball`."""
    ),
    nbf.v4.new_markdown_cell(
        """## Setup

Run `python run_pipeline.py --mode sample` before executing this notebook. All paths below are relative to the project root so the notebook remains portable."""
    ),
    nbf.v4.new_code_cell(
        """from pathlib import Path
import duckdb
import pandas as pd
from IPython.display import display

project_root = Path.cwd()
database_path = project_root / "database" / "mlb_pitch_analytics.duckdb"
quality_report_path = project_root / "outputs" / "data_quality_report.csv"

assert database_path.exists(), "Run: python run_pipeline.py --mode sample"
connection = duckdb.connect(str(database_path), read_only=True)
print(f"Database: {database_path}")"""
    ),
    nbf.v4.new_markdown_cell(
        """## Steps

### 1. Profile the lesson dataset

The silver fact table has one row per pitch. Its identifier combines the game, plate appearance, and pitch number."""
    ),
    nbf.v4.new_code_cell(
        '''profile_sql = """
SELECT
    COUNT(*) AS pitches,
    COUNT(DISTINCT game_pk) AS games,
    COUNT(DISTINCT pitcher_id) AS pitchers,
    MIN(game_date) AS first_date,
    MAX(game_date) AS last_date
FROM silver.fact_pitch
"""
profile = connection.execute(profile_sql).fetchdf()
display(profile)'''
    ),
    nbf.v4.new_markdown_cell(
        """### 2. Inspect the database layers

- **Bronze** preserves source-shaped data.
- **Silver** standardizes types and creates reusable pitch-level flags.
- **Gold** aggregates the fact table for Excel and Tableau.

This separation prevents dashboard logic from becoming a collection of hidden, inconsistent calculations."""
    ),
    nbf.v4.new_code_cell(
        '''tables_sql = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('bronze', 'silver', 'gold')
ORDER BY table_schema, table_name
"""
display(connection.execute(tables_sql).fetchdf())'''
    ),
    nbf.v4.new_markdown_cell(
        """### 3. Review the automated quality gate

A pipeline should fail before publishing when identifiers, count values, or metric relationships are invalid."""
    ),
    nbf.v4.new_code_cell(
        """quality_report = pd.read_csv(quality_report_path)
display(quality_report)
assert quality_report["status"].eq("PASS").all()"""
    ),
    nbf.v4.new_markdown_cell(
        """### 4. Answer the first SQL question

**Question:** Which pitch types were most common in the lesson sample, and how did their velocity, whiff rate, and chase rate differ?

Whiff rate uses swings as its denominator. Chase rate uses out-of-zone pitches as its denominator. Those denominator choices matter more than the formatting of the final chart."""
    ),
    nbf.v4.new_code_cell(
        '''pitch_mix_sql = """
SELECT
    pitch_name,
    COUNT(*) AS pitch_count,
    COUNT(*)::DOUBLE / SUM(COUNT(*)) OVER () AS usage_rate,
    AVG(release_speed) AS avg_velocity,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate
FROM silver.fact_pitch
GROUP BY pitch_name
HAVING COUNT(*) >= 10
ORDER BY pitch_count DESC
LIMIT 10
"""
pitch_mix = connection.execute(pitch_mix_sql).fetchdf()
pitch_mix_display = pitch_mix.copy()
for column in ["usage_rate", "whiff_rate", "chase_rate"]:
    pitch_mix_display[column] = (100 * pitch_mix_display[column]).round(1)
pitch_mix_display["avg_velocity"] = pitch_mix_display["avg_velocity"].round(1)
display(pitch_mix_display)'''
    ),
    nbf.v4.new_markdown_cell(
        """### 5. Compare strategy by count state

This is descriptive. A difference in rate is not automatically causal, and small groups should not be overinterpreted."""
    ),
    nbf.v4.new_code_cell(
        '''count_state_sql = """
SELECT
    count_state,
    COUNT(*) AS pitches,
    SUM(in_zone_flag)::DOUBLE / COUNT(*) AS zone_rate,
    SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
    SUM(chase_flag)::DOUBLE
        / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate
FROM silver.fact_pitch
GROUP BY count_state
ORDER BY CASE count_state
    WHEN 'First Pitch' THEN 1
    WHEN 'Pitcher Ahead' THEN 2
    WHEN 'Even' THEN 3
    WHEN 'Hitter Ahead' THEN 4
    WHEN 'Two Strikes' THEN 5
END
"""
count_state = connection.execute(count_state_sql).fetchdf()
count_state_display = count_state.copy()
for column in ["zone_rate", "whiff_rate", "chase_rate"]:
    count_state_display[column] = (100 * count_state_display[column]).round(1)
display(count_state_display)'''
    ),
    nbf.v4.new_markdown_cell(
        """## Checks

These assertions encode relationships that must always hold, regardless of the date range."""
    ),
    nbf.v4.new_code_cell(
        '''relationship_checks = connection.execute("""
SELECT
    SUM(whiff_flag) <= SUM(swing_flag) AS whiffs_valid,
    SUM(chase_flag) <= SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END) AS chases_valid,
    SUM(hard_hit_flag) <= SUM(batted_ball_flag) AS hard_hits_valid,
    COUNT(*) = COUNT(DISTINCT pitch_id) AS pitch_ids_unique
FROM silver.fact_pitch
""").fetchdf()
display(relationship_checks)
assert relationship_checks.all(axis=None)
connection.close()'''
    ),
    nbf.v4.new_markdown_cell(
        """## Next Steps

1. Open `outputs/MLB_Excel_Lesson_1.xlsx`.
2. Audit the formula-backed KPIs.
3. Recreate the pitch-type summary using a PivotTable.
4. Explain why `Whiff Rate = Whiffs / Swings`, rather than `Whiffs / All Pitches`.
5. Only after that, connect Tableau to `data/tableau/tableau_pitch_detail.csv`.

For the next lesson, we will build the first Tableau view: pitch usage by count state, with team, pitcher, batter side, and minimum-sample filters."""
    ),
]

parser = argparse.ArgumentParser(description="Build the guided MLB tutorial notebook.")
parser.add_argument("--execute", action="store_true", help="Execute with a local Jupyter kernel after building.")
args = parser.parse_args()

nbf.write(notebook, NOTEBOOK_PATH)
if args.execute:
    client = NotebookClient(
        notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(PROJECT_ROOT)}},
    )
    executed = client.execute()
    nbf.write(executed, NOTEBOOK_PATH)
    print(f"Built and executed {NOTEBOOK_PATH}")
else:
    print(f"Built {NOTEBOOK_PATH}")
