"""Export the deterministic dbt fixture as auditable CSV landing files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from warehouse.scripts.create_ci_fixture import RAW_COLUMNS, RAW_ROWS  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_fixture(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_statcast.csv"
    ranges_path = output_dir / "pipeline_ranges.csv"

    with raw_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([column.strip() for column in RAW_COLUMNS.split(",")])
        writer.writerows(RAW_ROWS)

    with ranges_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["season", "start_date", "end_date"])
        writer.writerow([2025, "2025-04-01", "2025-04-03"])

    manifest = {
        "fixture": "deterministic-dbt-edge-cases",
        "raw_rows": len(RAW_ROWS),
        "pipeline_range_rows": 1,
        "files": {
            raw_path.name: sha256(raw_path),
            ranges_path.name: sha256(ranges_path),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory that will receive two CSV files and a SHA-256 manifest.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = write_fixture(arguments.output_dir.resolve())
    print(json.dumps(result, sort_keys=True))
