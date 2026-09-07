"""Pin verified models and benchmark outputs for daily scoring without training."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

from src.artifact_lineage import dataset_identity, digest, verify_receipt
from src.common import load_config, project_path


FEATURE_FILES = ["sql/01_build_silver.sql", "sql/02_build_gold.sql",
                 "src/train_whiff_model.py", "src/train_hard_hit_model.py", "requirements.txt"]


def release_path(config):
    return project_path(config["paths"]["outputs_dir"]) / "lineage" / "model_release.json"


def verify_release(config):
    identity = dataset_identity(config)
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    path = release_path(config)
    verify_receipt(path, identity, config_hash)
    release = json.loads(path.read_text(encoding="utf-8"))
    if release.get("kind") != "frozen_model_release":
        raise RuntimeError("Invalid model release; run --workflow retrain.")
    return release


def publish_release(config):
    identity = dataset_identity(config)
    if identity["mode"] != "full":
        raise RuntimeError("A model release requires a full-mode dataset.")
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    output = project_path(config["paths"]["outputs_dir"])
    files = {}
    verified = set()
    for stage in ("train_whiff_model", "train_hard_hit_model", "score_pitch_models"):
        path = output / "lineage" / f"{stage}.json"
        verify_receipt(path, identity, config_hash, verified)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if stage == "score_pitch_models":
            if "model_release" in receipt.get("dependencies", {}):
                raise RuntimeError("Cannot publish a new release from daily scores; run --workflow retrain.")
            continue
        if any(argument.split("=", 1)[0] == "--max-rows-per-split" for argument in receipt.get("arguments", [])):
            raise RuntimeError("Limited-row experiment models cannot be released; retrain without row limits.")
        files.update(receipt["files"])
    for name in ("whiff_test_predictions.parquet", "hard_hit_test_predictions.parquet", "model_leaderboards.csv"):
        path = output / "predictions" / name
        files[str(path.resolve())] = digest(path)
    prediction = json.loads((output / "predictions" / "prediction_manifest.json").read_text())
    release = {"kind": "frozen_model_release", "dataset": identity, "config_hash": config_hash,
               "generated_at_utc": datetime.now(timezone.utc).isoformat(), "files": files,
               "benchmark_targets": prediction["targets"], "leaderboard_rows": prediction["leaderboard_rows"],
               "feature_contract": {name: digest(project_path(name)) for name in FEATURE_FILES}}
    path = release_path(config)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(release, indent=2), encoding="utf-8")
    temporary.replace(path)
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--action", choices=("publish", "verify"), default="verify")
    args = parser.parse_args()
    config = load_config(args.config)
    release = publish_release(config) if args.action == "publish" else verify_release(config)
    print(f"Model release {args.action}: trained on dataset {release['dataset']['run_id']}; {len(release['files'])} files verified.")


if __name__ == "__main__":
    main()
