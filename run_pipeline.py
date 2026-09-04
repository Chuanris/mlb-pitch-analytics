from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def run_step(arguments: list[str]) -> None:
    print("\nRUN:", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MLB Statcast ELT pipeline end to end.")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--refresh-days", type=int, help="Refresh this many latest complete days.")
    args = parser.parse_args()

    config = "config/pipeline_config.json"
    if not args.skip_extract:
        extract_command = [
            sys.executable,
            "-m",
            "src.extract_statcast",
            "--config",
            config,
            "--mode",
            args.mode,
        ]
        if args.force_extract:
            extract_command.append("--force")
        if args.refresh_days is not None:
            extract_command.extend(["--refresh-days", str(args.refresh_days)])
        run_step(extract_command)

        context_command = [
            sys.executable,
            "-m",
            "src.extract_game_context",
            "--config",
            config,
            "--mode",
            args.mode,
        ]
        if args.force_extract:
            context_command.append("--force")
        if args.refresh_days is not None:
            context_command.extend(["--refresh-days", str(args.refresh_days)])
        run_step(context_command)

    run_step(
        [
            sys.executable,
            "-m",
            "src.build_database",
            "--config",
            config,
            "--mode",
            args.mode,
        ]
    )
    run_step([sys.executable, "-m", "src.validate_data", "--config", config])
    if args.mode == "full":
        run_step([sys.executable, "-m", "src.train_whiff_model", "--config", config])
        run_step([sys.executable, "-m", "src.train_hard_hit_model", "--config", config])
        run_step([sys.executable, "-m", "src.score_pitch_models", "--config", config])
        run_step([sys.executable, "-m", "src.build_fantasy_pitcher_radar", "--config", config])
        run_step([sys.executable, "-m", "src.build_matchup_stream_planner", "--config", config])
    run_step([sys.executable, "-m", "src.export_outputs", "--config", config])
    run_step([sys.executable, "-m", "src.build_dashboard_snapshot", "--config", config])
    if args.mode == "sample":
        print("\nPipeline complete. Open notebooks/01_pipeline_and_sql_tutorial.ipynb next.")
    else:
        print("\nFull-season pipeline complete. Tableau-ready exports are in data/tableau/.")


if __name__ == "__main__":
    main()
