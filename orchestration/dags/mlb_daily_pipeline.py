"""Airflow 3 daily orchestration for the MLB pitch analytics pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

import pendulum
from airflow.sdk import TaskGroup, dag, task


PROJECT_ROOT = Path(
    os.environ.get("MLB_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline_config.json"
PYTHON_EXECUTABLE = os.environ.get("MLB_PIPELINE_PYTHON", sys.executable)
EXECUTION_MODE = os.environ.get("MLB_AIRFLOW_EXECUTION_MODE", "execute").lower()

if EXECUTION_MODE not in {"execute", "plan"}:
    raise ValueError("MLB_AIRFLOW_EXECUTION_MODE must be 'execute' or 'plan'")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from run_pipeline import build_pipeline_commands  # noqa: E402


def _daily_commands() -> dict[str, list[str]]:
    commands = build_pipeline_commands(
        mode="full",
        workflow="daily",
        config=str(CONFIG_PATH),
        python_executable=PYTHON_EXECUTABLE,
    )
    return {command[2]: command for command in commands}


DAILY_COMMANDS = _daily_commands()


def _run_command(command: list[str], *, cwd: Path = PROJECT_ROOT) -> dict[str, object]:
    """Run one bounded project command and return a small observable receipt."""
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    receipt: dict[str, object] = {
        "command": command,
        "cwd": str(cwd),
        "started_at_utc": started_at.isoformat(),
        "execution_mode": EXECUTION_MODE,
    }
    if EXECUTION_MODE == "plan":
        receipt.update(status="planned", duration_seconds=0.0)
        print(f"PLAN ONLY: {subprocess.list2cmdline(command)}")
        return receipt

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Pipeline configuration not found: {CONFIG_PATH}")

    environment = os.environ.copy()
    environment.setdefault("PYBASEBALL_CACHE", str(PROJECT_ROOT / ".pybaseball"))
    environment.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".matplotlib"))
    print(f"RUN: {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)
    receipt.update(
        status="success",
        duration_seconds=round(time.monotonic() - started, 3),
        finished_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    return receipt


@dag(
    dag_id="mlb_pitch_analytics_daily",
    description="Refresh, validate, transform, score and publish the MLB analytics snapshot.",
    schedule="30 6 * * *",
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Los_Angeles"),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,
    dagrun_timeout=timedelta(hours=4),
    default_args={
        "owner": "data-engineering",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["mlb", "analytics", "daily", "medallion"],
    doc_md="""
    ## MLB pitch analytics daily refresh

    Uses the same canonical module commands as `run_pipeline.py`. Extraction and
    downstream product tasks run in parallel only where their write targets do
    not overlap. Database, quality, and dbt tasks form a serial write/read barrier.
    `plan` mode is reserved for CI and never launches project modules.
    """,
)
def build_daily_dag():
    @task(task_id="validate_execution_plan", execution_timeout=timedelta(minutes=2))
    def validate_execution_plan() -> dict[str, object]:
        return _run_command(
            [
                PYTHON_EXECUTABLE,
                str(PROJECT_ROOT / "run_pipeline.py"),
                "--mode",
                "full",
                "--workflow",
                "daily",
                "--dry-run",
            ]
        )

    @task(execution_timeout=timedelta(minutes=30))
    def project_command(command: list[str]) -> dict[str, object]:
        return _run_command(command)

    @task(task_id="dbt_build", execution_timeout=timedelta(minutes=30))
    def dbt_build() -> dict[str, object]:
        environment_path = PROJECT_ROOT / "database" / "mlb_pitch_analytics.duckdb"
        os.environ.setdefault("DBT_DUCKDB_PATH", str(environment_path))
        os.environ.setdefault("DBT_SCHEMA", "dbt_mlb")
        os.environ.setdefault("DBT_THREADS", "4")
        return _run_command(
            ["dbt", "build", "--profiles-dir", ".", "--target", "duckdb"],
            cwd=PROJECT_ROOT / "warehouse",
        )

    preflight = validate_execution_plan()
    release = project_command.override(
        task_id="verify_model_release", execution_timeout=timedelta(minutes=5)
    )(DAILY_COMMANDS["src.model_release"])

    with TaskGroup(group_id="extract", tooltip="Independent restartable source partitions"):
        statcast = project_command.override(
            task_id="statcast",
            retries=2,
            retry_delay=timedelta(minutes=10),
            execution_timeout=timedelta(minutes=60),
        )(DAILY_COMMANDS["src.extract_statcast"])
        game_context = project_command.override(
            task_id="game_context",
            retries=2,
            retry_delay=timedelta(minutes=10),
            execution_timeout=timedelta(minutes=45),
        )(DAILY_COMMANDS["src.extract_game_context"])

    database = project_command.override(
        task_id="build_database", execution_timeout=timedelta(minutes=45)
    )(DAILY_COMMANDS["src.build_database"])
    quality = project_command.override(
        task_id="validate_data", execution_timeout=timedelta(minutes=20)
    )(DAILY_COMMANDS["src.validate_data"])
    transformations = dbt_build()
    scoring = project_command.override(
        task_id="score_pitch_models", execution_timeout=timedelta(minutes=30)
    )(DAILY_COMMANDS["src.score_pitch_models"])

    with TaskGroup(group_id="products", tooltip="Independent downstream analytical products"):
        pitcher_radar = project_command.override(task_id="fantasy_pitcher_radar")(
            DAILY_COMMANDS["src.build_fantasy_pitcher_radar"]
        )
        stream_planner = project_command.override(task_id="matchup_stream_planner")(
            DAILY_COMMANDS["src.build_matchup_stream_planner"]
        )
        start_forecast = project_command.override(task_id="start_forecast")(
            DAILY_COMMANDS["src.build_start_forecast"]
        )
        hitters = project_command.override(task_id="fantasy_hitters")(
            DAILY_COMMANDS["src.build_fantasy_hitters"]
        )

    exports = project_command.override(task_id="export_outputs")(
        DAILY_COMMANDS["src.export_outputs"]
    )
    snapshot = project_command.override(
        task_id="build_dashboard_snapshot", execution_timeout=timedelta(minutes=20)
    )(DAILY_COMMANDS["src.build_dashboard_snapshot"])
    health = project_command.override(
        task_id="health_check", execution_timeout=timedelta(minutes=5)
    )(
        [
            PYTHON_EXECUTABLE,
            "-m",
            "src.health_check",
            "--config",
            str(CONFIG_PATH),
            "--max-age-days",
            "2",
        ]
    )

    preflight >> release >> [statcast, game_context]
    [statcast, game_context] >> database >> quality >> transformations >> scoring
    scoring >> [pitcher_radar, stream_planner, start_forecast, hitters, exports]
    [pitcher_radar, stream_planner, start_forecast, hitters, exports] >> snapshot >> health


mlb_daily_pipeline = build_daily_dag()


if __name__ == "__main__":
    mlb_daily_pipeline.test()
