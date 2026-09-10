from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def write_run_status(configuration: dict, status: dict) -> None:
    directory = Path(configuration.get("paths", {}).get("outputs_dir", "outputs"))
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pipeline_status.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_step(arguments: list[str]) -> None:
    print("\nRUN:", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=PROJECT_ROOT, check=True)


def build_pipeline_commands(
    *,
    mode: str,
    workflow: str,
    config: str,
    skip_extract: bool = False,
    force_extract: bool = False,
    refresh_days: int | None = None,
    python_executable: str | None = None,
) -> list[list[str]]:
    """Return the canonical command plan shared by the CLI and Airflow."""
    python = python_executable or sys.executable
    commands: list[list[str]] = []
    if workflow == "daily":
        commands.append([python, "-m", "src.model_release", "--config", config, "--action", "verify"])
    if not skip_extract:
        extract_command = [
            python,
            "-m",
            "src.extract_statcast",
            "--config",
            config,
            "--mode",
            mode,
        ]
        if force_extract:
            extract_command.append("--force")
        if refresh_days is not None:
            extract_command.extend(["--refresh-days", str(refresh_days)])
        commands.append(extract_command)

        context_command = [
            python,
            "-m",
            "src.extract_game_context",
            "--config",
            config,
            "--mode",
            mode,
        ]
        if force_extract:
            context_command.append("--force")
        if refresh_days is not None:
            context_command.extend(["--refresh-days", str(refresh_days)])
        commands.append(context_command)

    commands.append(
        [python, "-m", "src.build_database", "--config", config, "--mode", mode]
    )
    commands.append([python, "-m", "src.validate_data", "--config", config])
    if mode == "full":
        if workflow == "retrain":
            commands.append([python, "-m", "src.train_whiff_model", "--config", config])
            commands.append([python, "-m", "src.train_hard_hit_model", "--config", config])
        scoring = [python, "-m", "src.score_pitch_models", "--config", config]
        if workflow == "daily":
            scoring.append("--recent-only")
        commands.append(scoring)
        if workflow == "retrain":
            commands.append(
                [python, "-m", "src.model_release", "--config", config, "--action", "publish"]
            )
        commands.append([python, "-m", "src.build_fantasy_pitcher_radar", "--config", config])
        commands.append([python, "-m", "src.build_matchup_stream_planner", "--config", config])
        commands.append([python, "-m", "src.build_start_forecast", "--config", config])
        commands.append([python, "-m", "src.build_fantasy_hitters", "--config", config])
    commands.append([python, "-m", "src.export_outputs", "--config", config])
    commands.append([python, "-m", "src.build_dashboard_snapshot", "--config", config])
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MLB Statcast ELT pipeline end to end.")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    parser.add_argument("--workflow", choices=["retrain", "daily"], default="retrain",
                        help="Full mode: retrain models or reuse a verified release for daily scoring.")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--refresh-days", type=int, help="Refresh this many latest complete days.")
    parser.add_argument("--config", default="config/pipeline_config.json", help="Configuration path, relative to the repository root or absolute.")
    parser.add_argument("--dry-run", action="store_true", help="Print the execution plan without downloading data or writing outputs.")
    args = parser.parse_args(argv)
    if args.workflow == "daily" and args.mode != "full":
        parser.error("--workflow daily requires --mode full")
    if args.refresh_days is not None and args.refresh_days < 0:
        parser.error("--refresh-days must be zero or greater")
    if args.skip_extract and (args.force_extract or args.refresh_days is not None):
        parser.error("--skip-extract cannot be combined with --force-extract or --refresh-days")

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    try:
        with config_path.open(encoding="utf-8") as file:
            configuration = json.load(file)
        if not isinstance(configuration, dict) or args.mode not in configuration:
            parser.error(f"Configuration must contain the selected mode: {args.mode}")
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read configuration {config_path}: {error}")

    config = str(config_path.resolve())
    commands = build_pipeline_commands(
        mode=args.mode,
        workflow=args.workflow,
        config=config,
        skip_extract=args.skip_extract,
        force_extract=args.force_extract,
        refresh_days=args.refresh_days,
    )
    status = {"run_id": str(uuid4()), "workflow": args.workflow, "mode": args.mode,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "running", "steps": []}
    for index, command in enumerate(commands, start=1):
        print(f"\nStep {index}/{len(commands)}: {command[2]}", flush=True)
        if args.dry_run:
            print(subprocess.list2cmdline(command), flush=True)
            continue
        try:
            started = time.monotonic()
            status["current_step"] = command[2]
            write_run_status(configuration, status)
            run_step(command)
            status["steps"].append({"module": command[2], "seconds": round(time.monotonic() - started, 3), "status": "success"})
            write_run_status(configuration, status)
        except subprocess.CalledProcessError as error:
            status.update(status="failed", error=str(error), finished_at_utc=datetime.now(timezone.utc).isoformat())
            write_run_status(configuration, status)
            print(f"Pipeline failed at {command[2]} (exit code {error.returncode}). "
                  "Later steps were not run. See the output above for details.", file=sys.stderr)
            return 1
        except OSError as error:
            status.update(status="failed", error=str(error), finished_at_utc=datetime.now(timezone.utc).isoformat())
            write_run_status(configuration, status)
            print(f"Cannot start {command[2]}: {error}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            status.update(status="interrupted", finished_at_utc=datetime.now(timezone.utc).isoformat())
            write_run_status(configuration, status)
            print("\nPipeline interrupted; later steps were not run.", file=sys.stderr)
            return 130
    if args.dry_run:
        print("\nDry run complete. No pipeline steps were executed.")
        return 0
    status.update(status="success", finished_at_utc=datetime.now(timezone.utc).isoformat(), current_step=None)
    write_run_status(configuration, status)
    if args.mode == "sample":
        print("\nPipeline complete. Open notebooks/01_pipeline_and_sql_tutorial.ipynb next.")
    else:
        print("\nFull-season pipeline complete. Tableau-ready exports are in data/tableau/.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
