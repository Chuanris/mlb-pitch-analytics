from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_pipeline


class PipelineCliTests(unittest.TestCase):
    def test_airflow_can_reuse_canonical_daily_command_plan(self):
        commands = run_pipeline.build_pipeline_commands(
            mode="full",
            workflow="daily",
            config="C:/project/config/pipeline_config.json",
            python_executable="python",
        )
        modules = [command[2] for command in commands]
        self.assertEqual(len(modules), 12)
        self.assertEqual(modules[:3], [
            "src.model_release", "src.extract_statcast", "src.extract_game_context",
        ])
        self.assertEqual(modules[-2:], ["src.export_outputs", "src.build_dashboard_snapshot"])
        scoring = next(command for command in commands if command[2] == "src.score_pitch_models")
        self.assertIn("--recent-only", scoring)

    def test_failed_and_interrupted_runs_record_finish_time(self):
        for error, expected in [(subprocess.CalledProcessError(1, 'step'), 'failed'),
                                (OSError('cannot launch'), 'failed'), (KeyboardInterrupt(), 'interrupted')]:
            with self.subTest(expected=expected), patch('run_pipeline.run_step', side_effect=error), patch('run_pipeline.write_run_status') as write:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    run_pipeline.main(['--mode', 'sample', '--skip-extract'])
                final = write.call_args.args[1]
                self.assertEqual(final['status'], expected)
                self.assertIn('finished_at_utc', final)
                self.assertEqual(final['current_step'], 'src.build_database')

    def invoke(self, args, **mock_options):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with patch("run_pipeline.subprocess.run", **mock_options) as run, patch("run_pipeline.write_run_status"):
                result = run_pipeline.main(args)
        return result, run, output.getvalue()

    def test_full_preview_never_executes_steps(self):
        result, run, output = self.invoke(["--mode", "full", "--dry-run"])
        self.assertEqual(result, 0)
        run.assert_not_called()
        self.assertIn("Step 14/14", output)
        self.assertIn("src.train_whiff_model", output)

    def test_daily_preflights_release_and_never_trains(self):
        result, run, _ = self.invoke(["--mode", "full", "--workflow", "daily", "--skip-extract"])
        self.assertEqual(result, 0)
        modules = [call.args[0][2] for call in run.call_args_list]
        self.assertEqual(modules[0], "src.model_release")
        self.assertNotIn("src.train_whiff_model", modules)
        self.assertNotIn("src.train_hard_hit_model", modules)
        scoring = next(call.args[0] for call in run.call_args_list if call.args[0][2] == "src.score_pitch_models")
        self.assertIn("--recent-only", scoring)

    def test_daily_preflight_failure_prevents_database_rebuild(self):
        result, run, _ = self.invoke(["--mode", "full", "--workflow", "daily"],
                                    side_effect=subprocess.CalledProcessError(1, "release"))
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 1)

    def test_sample_skips_models_and_extraction_when_requested(self):
        result, run, _ = self.invoke(["--skip-extract"])
        self.assertEqual(result, 0)
        self.assertEqual([call.args[0][2] for call in run.call_args_list], [
            "src.build_database", "src.validate_data", "src.export_outputs",
            "src.build_dashboard_snapshot",
        ])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs, {"cwd": run_pipeline.PROJECT_ROOT, "check": True})

    def test_invalid_options_fail_before_any_step(self):
        for args in (["--refresh-days", "-1"], ["--skip-extract", "--force-extract"],
                     ["--skip-extract", "--refresh-days", "0"],
                     ["--config", "missing-config.json"]):
            with self.subTest(args=args), patch("run_pipeline.subprocess.run") as run:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    run_pipeline.main(args)
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_failure_stops_downstream_steps(self):
        result, run, output = self.invoke([], side_effect=[None, subprocess.CalledProcessError(7, "context")])
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 2)
        self.assertIn("src.extract_game_context (exit code 7)", output)
        self.assertNotIn("Pipeline complete", output)

    def test_custom_config_and_extraction_options_reach_both_extractors(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "custom config.json"
            config.write_text('{"sample": {}}', encoding="utf-8")
            result, run, _ = self.invoke(["--config", str(config), "--force-extract", "--refresh-days", "0"])
            self.assertEqual(result, 0)
            for call in run.call_args_list:
                command = call.args[0]
                self.assertEqual(command[command.index("--config") + 1], str(config.resolve()))
            for call in run.call_args_list[:2]:
                self.assertIn("--force", call.args[0])
                self.assertEqual(call.args[0][-2:], ["--refresh-days", "0"])


if __name__ == "__main__":
    unittest.main()
