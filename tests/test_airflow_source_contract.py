from __future__ import annotations

import ast
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = ROOT / "orchestration" / "dags" / "mlb_daily_pipeline.py"
COMPOSE_PATH = ROOT / "orchestration" / "compose.yaml"


class AirflowSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DAG_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_uses_airflow_3_public_authoring_interface(self):
        imports = [node for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)]
        sdk_import = next(node for node in imports if node.module == "airflow.sdk")
        self.assertEqual({alias.name for alias in sdk_import.names}, {"TaskGroup", "dag", "task"})
        self.assertFalse(any(node.module in {"airflow.models", "airflow.decorators"} for node in imports))

    def test_dag_has_schedule_overlap_and_timeout_guards(self):
        dag_call = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dag"
        )
        keywords = {keyword.arg: keyword.value for keyword in dag_call.keywords}
        self.assertEqual(ast.literal_eval(keywords["schedule"]), "30 6 * * *")
        self.assertFalse(ast.literal_eval(keywords["catchup"]))
        self.assertEqual(ast.literal_eval(keywords["max_active_runs"]), 1)
        self.assertEqual(ast.literal_eval(keywords["max_active_tasks"]), 4)
        self.assertIn("dagrun_timeout", keywords)

    def test_all_authored_tasks_have_stable_ids(self):
        task_ids = {
            ast.literal_eval(keyword.value)
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "task_id" and isinstance(keyword.value, ast.Constant)
        }
        self.assertEqual(
            task_ids,
            {
                "validate_execution_plan",
                "verify_model_release",
                "dbt_build",
                "statcast",
                "game_context",
                "build_database",
                "validate_data",
                "score_pitch_models",
                "fantasy_pitcher_radar",
                "matchup_stream_planner",
                "start_forecast",
                "fantasy_hitters",
                "export_outputs",
                "build_dashboard_snapshot",
                "health_check",
            },
        )

    def test_compose_is_local_only_and_has_required_airflow_3_services(self):
        compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(
            set(services),
            {
                "airflow-db",
                "airflow-init",
                "airflow-api-server",
                "airflow-scheduler",
                "airflow-dag-processor",
            },
        )
        self.assertEqual(services["airflow-api-server"]["ports"], ["127.0.0.1:8080:8080"])
        environment = compose["x-airflow-common"]["environment"]
        self.assertEqual(environment["AIRFLOW__CORE__EXECUTOR"], "LocalExecutor")
        self.assertEqual(environment["AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION"], "true")


if __name__ == "__main__":
    unittest.main()
