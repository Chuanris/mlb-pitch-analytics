from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from src.artifact_lineage import digest, verify_receipt
from src.train_whiff_model import make_time_split
from src.validate_data import CHECKS


class ReliabilityTests(unittest.TestCase):
    def test_frozen_release_can_score_newer_data_but_rejects_rewind_or_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "model.bin"
            artifact.write_bytes(b"frozen-model")
            path = root / "model_release.json"
            original = dict(run_id="training", mode="full", data_through="2026-09-03")
            data = dict(kind="frozen_model_release", dataset=original, config_hash="config",
                        files={str(artifact): digest(artifact)}, feature_contract={})
            path.write_text(json.dumps(data))
            verify_receipt(path, dict(original, run_id="daily", data_through="2026-09-04"), "config")
            with self.assertRaisesRegex(RuntimeError, "Stale"):
                verify_receipt(path, dict(original, data_through="2026-08-01"), "config")
            with self.assertRaisesRegex(RuntimeError, "Stale"):
                verify_receipt(path, original, "changed-config")
            artifact.write_bytes(b"changed-model")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                verify_receipt(path, original, "config")

    def test_future_dates_do_not_change_fixed_benchmark(self):
        dates = ["2025-09-01", "2026-04-01", "2026-06-13", "2026-09-03"]
        frame = pd.DataFrame({"game_date": dates})
        before = make_time_split(frame)
        after = make_time_split(pd.concat([frame, pd.DataFrame({"game_date": ["2026-09-04", "2027-04-01"]})]))
        for name in ("train", "validation", "test"):
            pd.testing.assert_frame_equal(getattr(before, name), getattr(after, name))

    def test_invalid_boundaries_rejected(self):
        with self.assertRaises(ValueError):
            make_time_split(pd.DataFrame(), dict(train_end="2026-07-01", validation_start="2026-03-01",
                                                test_start="2026-06-13", test_end="2026-09-03"))

    def test_missing_completed_game_fails_but_postponed_game_does_not(self):
        sql = dict((name, query) for name, query, _ in CHECKS)["completed_regular_games_have_pitches"]
        with duckdb.connect() as connection:
            connection.execute("CREATE SCHEMA silver; CREATE SCHEMA metadata")
            connection.execute("CREATE TABLE silver.fact_game_context(game_pk INT, official_date DATE, game_status VARCHAR)")
            connection.execute("CREATE TABLE silver.fact_pitch(game_pk INT)")
            connection.execute("CREATE TABLE metadata.pipeline_ranges(start_date DATE, end_date DATE)")
            connection.execute("INSERT INTO metadata.pipeline_ranges VALUES ('2026-04-01','2026-04-03')")
            connection.execute("INSERT INTO silver.fact_game_context VALUES (1,'2026-04-01','Final'),(2,'2026-04-02','Postponed')")
            self.assertFalse(connection.execute(sql).fetchone()[0])
            connection.execute("INSERT INTO silver.fact_pitch VALUES (1)")
            self.assertTrue(connection.execute(sql).fetchone()[0])

    def test_receipts_reject_stale_tampered_and_changed_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "model.bin"
            artifact.write_bytes(b"model-v1")
            receipt = root / "train.json"
            identity = {"run_id": "one"}
            data = dict(dataset=identity, config_hash="config", files={str(artifact): digest(artifact)})
            receipt.write_text(json.dumps(data))
            verify_receipt(receipt, identity, "config")
            with self.assertRaisesRegex(RuntimeError, "Stale"):
                verify_receipt(receipt, {"run_id": "two"}, "config")
            downstream = root / "score.json"
            downstream.write_text(json.dumps(dict(data, dependencies={"train": digest(receipt)})))
            receipt.write_text(json.dumps(dict(data, generated_at="later")))
            with self.assertRaisesRegex(RuntimeError, "Upstream"):
                verify_receipt(downstream, identity, "config")
            artifact.write_bytes(b"model-v2")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                verify_receipt(receipt, identity, "config")


if __name__ == "__main__":
    unittest.main()
