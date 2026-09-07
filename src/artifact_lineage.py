"""CLI-stage receipts bind generated files to one committed database version.

Legacy outputs must be regenerated, never silently adopted. Receipts are local
build metadata, not a model registry or a substitute for future serving policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.common import load_config, project_path


DEPENDENCIES = {
    "train_whiff_model": [], "train_hard_hit_model": [],
    "score_pitch_models": ["train_whiff_model", "train_hard_hit_model"],
    "build_fantasy_pitcher_radar": ["score_pitch_models"],
    "build_matchup_stream_planner": ["build_fantasy_pitcher_radar"],
    "build_start_forecast": ["build_matchup_stream_planner"],
    "build_dashboard_snapshot": ["score_pitch_models", "build_fantasy_pitcher_radar",
                                 "build_matchup_stream_planner", "build_start_forecast"],
}
PATTERNS = {
    "train_whiff_model": ["models/whiff*"],
    "train_hard_hit_model": ["models/hard_hit*"],
    "score_pitch_models": ["predictions/*"],
    "build_fantasy_pitcher_radar": ["fantasy/pitcher_fantasy_radar.csv", "fantasy/fantasy_radar_manifest.json"],
    "build_matchup_stream_planner": ["fantasy/matchup_stream_planner*"],
    "build_start_forecast": ["forecast/*.csv", "forecast/model_manifest.json"],
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dataset_identity(config: dict) -> dict:
    with duckdb.connect(str(project_path(config["paths"]["database"])), read_only=True) as connection:
        try:
            row = connection.execute("SELECT run_id, mode, data_through FROM metadata.dataset_version").fetchone()
        except duckdb.Error as error:
            raise RuntimeError("Unversioned database: rebuild it before generating model artifacts.") from error
    if row is None:
        raise RuntimeError("Missing database version; rebuild the database.")
    return {"run_id": row[0], "mode": row[1], "data_through": str(row[2])}


def verify_receipt(path: Path, identity: dict, config_hash: str, verified: set | None = None) -> None:
    verified = verified if verified is not None else set()
    if path.resolve() in verified:
        return
    if not path.is_file():
        raise RuntimeError(f"Missing artifact receipt: {path.name}; rerun its pipeline stage.")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    frozen = path.stem == "model_release" and receipt.get("kind") == "frozen_model_release"
    compatible = receipt["dataset"] == identity
    if frozen:
        compatible = (identity.get("mode") == "full" and receipt["dataset"].get("mode") == "full"
                      and identity["data_through"] >= receipt["dataset"]["data_through"])
        for filename, expected in receipt.get("feature_contract", {}).items():
            if digest(project_path(filename)) != expected:
                raise RuntimeError(f"Model feature contract changed: {filename}; run --workflow retrain.")
    if not compatible or receipt["config_hash"] != config_hash:
        raise RuntimeError(f"Stale artifact version: {path.name}; rerun its pipeline stage.")
    for stage, expected in receipt.get("dependencies", {}).items():
        dependency = path.parent / f"{stage}.json"
        if not dependency.is_file() or digest(dependency) != expected:
            raise RuntimeError(f"Upstream stage changed: {stage}; rerun {path.stem}.")
        verify_receipt(dependency, identity, config_hash, verified)
    for filename, expected in receipt["files"].items():
        file = Path(filename)
        if not file.is_file() or digest(file) != expected:
            raise RuntimeError(f"Artifact changed or missing: {file.name}; rerun its pipeline stage.")
    verified.add(path.resolve())


def run_versioned(stage: str, main) -> None:
    import sys
    if "--help" in sys.argv or "-h" in sys.argv:
        main()
        return
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--target", default="all")
    parser.add_argument("--recent-only", action="store_true")
    args, _ = parser.parse_known_args()
    config = load_config(args.config)
    identity = dataset_identity(config)
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    output = project_path(config["paths"]["outputs_dir"])
    receipt_dir = output / "lineage"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{stage}.json"
    dependencies = DEPENDENCIES[stage] if identity["mode"] == "full" else []
    if stage == "score_pitch_models" and args.recent_only:
        dependencies = ["model_release"]
    verified = set()
    for dependency in dependencies:
        verify_receipt(receipt_dir / f"{dependency}.json", identity, config_hash, verified)
    # Failed/partial overwrites must never retain a successful receipt.
    receipt_path.unlink(missing_ok=True)
    main()
    if stage == "score_pitch_models" and args.target != "all":
        print("Partial target scoring completed without a bundle receipt; run --target all before Fantasy or snapshot generation.")
        return
    if dataset_identity(config) != identity:
        raise RuntimeError("Database changed during artifact generation; rerun the stage.")
    verified = set()
    for dependency in dependencies:
        verify_receipt(receipt_dir / f"{dependency}.json", identity, config_hash, verified)
    files = [file for pattern in PATTERNS.get(stage, []) for file in output.glob(pattern) if file.is_file()]
    if stage == "build_dashboard_snapshot":
        files = [project_path(config["paths"].get("dashboard_snapshot", "dashboard/src/data.json"))]
    if not files:
        raise RuntimeError(f"No artifacts generated for {stage}")
    receipt = {"stage": stage, "dataset": identity, "config_hash": config_hash, "arguments": sys.argv[1:],
               "generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "dependencies": {key: digest(receipt_dir / f"{key}.json") for key in dependencies},
               "files": {str(file.resolve()): digest(file) for file in files}}
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temporary.replace(receipt_path)
