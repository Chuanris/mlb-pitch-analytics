from __future__ import annotations

import argparse

import duckdb

from src.common import load_config, project_path


EXPORTS = {
    "pitcher_pitch_type_summary.csv": "SELECT * FROM gold.pitcher_pitch_type_summary",
    "count_strategy_summary.csv": "SELECT * FROM gold.count_strategy_summary",
    "pitcher_month_summary.csv": "SELECT * FROM gold.pitcher_month_summary",
    "tableau_pitch_detail.csv": "SELECT * FROM gold.tableau_pitch_detail",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export analysis-ready tables for Tableau and Excel.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    database_path = project_path(config["paths"]["database"])
    tableau_dir = project_path(config["paths"]["tableau_dir"])
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    tableau_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(database_path), read_only=True)
    for filename, sql in EXPORTS.items():
        output_path = tableau_dir / filename
        safe_path = str(output_path).replace("'", "''")
        connection.execute(f"COPY ({sql}) TO '{safe_path}' (HEADER, DELIMITER ',')")
        print(f"Exported {filename}")

    lesson_path = outputs_dir / "excel_pitch_sample.csv"
    safe_lesson_path = str(lesson_path).replace("'", "''")
    connection.execute(
        f"""
        COPY (
            SELECT
                pitch_id,
                game_date,
                pitcher_name,
                pitcher_team,
                batter_stand,
                pitch_type,
                pitch_name,
                balls,
                strikes,
                count_state,
                release_speed,
                zone,
                in_zone_flag,
                swing_flag,
                whiff_flag,
                chase_flag,
                batted_ball_flag,
                launch_speed,
                hard_hit_flag,
                result_group
            FROM silver.fact_pitch
            ORDER BY game_date, game_pk, at_bat_number, pitch_number
        ) TO '{safe_lesson_path}' (HEADER, DELIMITER ',')
        """
    )

    summary_path = outputs_dir / "excel_pitch_type_summary.csv"
    safe_summary_path = str(summary_path).replace("'", "''")
    connection.execute(
        f"""
        COPY (
            SELECT
                pitch_type,
                pitch_name,
                COUNT(*) AS pitch_count,
                AVG(release_speed) AS avg_velocity,
                SUM(swing_flag)::DOUBLE / COUNT(*) AS swing_rate,
                SUM(whiff_flag)::DOUBLE / NULLIF(SUM(swing_flag), 0) AS whiff_rate,
                SUM(chase_flag)::DOUBLE / NULLIF(SUM(CASE WHEN in_zone_flag = 0 THEN 1 ELSE 0 END), 0) AS chase_rate,
                SUM(hard_hit_flag)::DOUBLE / NULLIF(SUM(batted_ball_flag), 0) AS hard_hit_rate
            FROM silver.fact_pitch
            GROUP BY pitch_type, pitch_name
            HAVING COUNT(*) >= 10
            ORDER BY pitch_count DESC
        ) TO '{safe_summary_path}' (HEADER, DELIMITER ',')
        """
    )
    connection.close()


if __name__ == "__main__":
    main()
