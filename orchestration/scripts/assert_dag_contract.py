"""Import the Airflow DAG and assert its safety and parallelism contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = ROOT / "orchestration" / "dags" / "mlb_daily_pipeline.py"


def load_dag_module():
    spec = importlib.util.spec_from_file_location("mlb_daily_pipeline_contract", DAG_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load DAG module: {DAG_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_dag_module()
    dag = module.mlb_daily_pipeline
    expected_tasks = {
        "validate_execution_plan",
        "verify_model_release",
        "extract.statcast",
        "extract.game_context",
        "build_database",
        "validate_data",
        "dbt_build",
        "score_pitch_models",
        "products.fantasy_pitcher_radar",
        "products.matchup_stream_planner",
        "products.start_forecast",
        "products.fantasy_hitters",
        "export_outputs",
        "build_dashboard_snapshot",
        "health_check",
    }
    actual_tasks = set(dag.task_dict)
    if actual_tasks != expected_tasks:
        raise AssertionError(
            f"DAG task mismatch; missing={expected_tasks - actual_tasks}, "
            f"unexpected={actual_tasks - expected_tasks}"
        )

    expected_downstream = {
        "validate_execution_plan": {"verify_model_release"},
        "verify_model_release": {"extract.statcast", "extract.game_context"},
        "extract.statcast": {"build_database"},
        "extract.game_context": {"build_database"},
        "build_database": {"validate_data"},
        "validate_data": {"dbt_build"},
        "dbt_build": {"score_pitch_models"},
        "score_pitch_models": {
            "products.fantasy_pitcher_radar",
            "products.matchup_stream_planner",
            "products.start_forecast",
            "products.fantasy_hitters",
            "export_outputs",
        },
        "products.fantasy_pitcher_radar": {"build_dashboard_snapshot"},
        "products.matchup_stream_planner": {"build_dashboard_snapshot"},
        "products.start_forecast": {"build_dashboard_snapshot"},
        "products.fantasy_hitters": {"build_dashboard_snapshot"},
        "export_outputs": {"build_dashboard_snapshot"},
        "build_dashboard_snapshot": {"health_check"},
        "health_check": set(),
    }
    for task_id, downstream in expected_downstream.items():
        actual = set(dag.get_task(task_id).downstream_task_ids)
        if actual != downstream:
            raise AssertionError(
                f"Unexpected downstream tasks for {task_id}: {actual}; expected {downstream}"
            )

    if dag.catchup:
        raise AssertionError("Daily DAG must not backfill automatically")
    if dag.max_active_runs != 1 or dag.max_active_tasks != 4:
        raise AssertionError("Daily DAG concurrency guard changed")
    if dag.dagrun_timeout is None:
        raise AssertionError("Daily DAG requires a run timeout")
    for task in dag.tasks:
        if task.execution_timeout is None:
            raise AssertionError(f"Task has no execution timeout: {task.task_id}")

    canonical_modules = [command[2] for command in module.DAILY_COMMANDS.values()]
    if len(canonical_modules) != 12 or len(set(canonical_modules)) != 12:
        raise AssertionError(f"Unexpected canonical daily command plan: {canonical_modules}")

    result = {
        "dag_id": dag.dag_id,
        "task_count": len(dag.tasks),
        "max_active_runs": dag.max_active_runs,
        "max_active_tasks": dag.max_active_tasks,
        "parallel_extract_tasks": 2,
        "parallel_downstream_tasks": 5,
        "canonical_pipeline_commands": len(canonical_modules),
        "status": "PASS",
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
