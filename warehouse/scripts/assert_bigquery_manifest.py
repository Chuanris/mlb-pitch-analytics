"""Assert that a parsed dbt manifest retains the BigQuery MPP contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MODEL_ID = "model.mlb_pitch_analytics.int_pitch_outcomes"


def assert_manifest(path: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    model = manifest["nodes"][MODEL_ID]
    config = model["config"]

    expected_partition = {
        "field": "game_date",
        "data_type": "date",
        "granularity": "day",
    }
    assert config["materialized"] == "incremental"
    assert config["incremental_strategy"] == "merge"
    assert config["unique_key"] == "pitch_id"
    assert config["partition_by"] == expected_partition
    assert config["cluster_by"] == ["pitcher_id", "pitch_type"]

    enabled_reconciliation_tests = [
        node_id
        for node_id, node in manifest["nodes"].items()
        if "reconcile_" in node_id and node["config"]["enabled"]
    ]
    assert enabled_reconciliation_tests == []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    assert_manifest(arguments.manifest.resolve())
    print("BigQuery manifest contract: OK")
