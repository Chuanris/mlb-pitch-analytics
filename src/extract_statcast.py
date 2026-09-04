from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.common import (
    empty_partition_marker,
    load_config,
    partition_ranges,
    project_path,
    resolved_mode_ranges,
)

# pybaseball creates its cache at import time. Keep it inside the project so the
# pipeline also works in sandboxed, CI, and managed Windows environments.
os.environ.setdefault("PYBASEBALL_CACHE", str(project_path(".pybaseball/cache")))
os.environ.setdefault("MPLCONFIGDIR", str(project_path(".matplotlib")))

import pyarrow.parquet as pq
from pybaseball import cache, statcast


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def validate_partition(path: Path) -> int:
    try:
        row_count = pq.ParquetFile(path).metadata.num_rows
    except Exception as exc:
        raise RuntimeError(
            f"Existing raw partition is not a readable Parquet file: {path}. "
            "Rerun with --force to replace it."
        ) from exc
    if row_count < 1:
        raise RuntimeError(
            f"Existing raw partition is empty: {path}. Rerun with --force to replace it."
        )
    return row_count


def write_empty_marker(path: Path, chunk_start, chunk_end) -> None:
    marker = empty_partition_marker(path)
    temporary = marker.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "row_count": 0,
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temporary.replace(marker)


def cleanup_consolidated_daily_files(raw_dir: Path, chunk_start, chunk_end, keep: Path) -> None:
    if chunk_start == chunk_end:
        return
    resolved_raw_dir = raw_dir.resolve()
    current = chunk_start
    while current <= chunk_end:
        daily = raw_dir / f"statcast_{current}_{current}.parquet"
        if daily != keep and daily.parent.resolve() == resolved_raw_dir:
            daily.unlink(missing_ok=True)
            empty_partition_marker(daily).unlink(missing_ok=True)
        current += timedelta(days=1)


def extract_range(parameters: dict, raw_dir: Path, force: bool, refresh_days: int) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    refresh_after = parameters["end_date"] - timedelta(days=max(0, refresh_days - 1)) \
        if parameters.get("latest_complete_day") and refresh_days > 0 else None
    for chunk_start, chunk_end in partition_ranges(parameters):
        output_path = raw_dir / f"statcast_{chunk_start}_{chunk_end}.parquet"
        empty_marker = empty_partition_marker(output_path)
        refresh = force or (refresh_after is not None and chunk_end >= refresh_after)
        if output_path.exists() and not refresh:
            row_count = validate_partition(output_path)
            logging.info("Skip valid raw partition: %s (%s rows)", output_path.name, f"{row_count:,}")
            continue
        if empty_marker.exists() and not refresh:
            logging.info("Skip confirmed empty partition: %s", output_path.name)
            continue

        logging.info("Extract Statcast %s through %s", chunk_start, chunk_end)
        if refresh:
            cache.disable()
        try:
            frame = statcast(
                start_dt=chunk_start.isoformat(),
                end_dt=chunk_end.isoformat(),
                verbose=False,
                parallel=True,
            )
        finally:
            if refresh:
                cache.enable()
        if frame is None or frame.empty:
            write_empty_marker(output_path, chunk_start, chunk_end)
            output_path.unlink(missing_ok=True)
            logging.info("Confirmed no Statcast rows for %s through %s", chunk_start, chunk_end)
            continue

        frame = frame.sort_values(
            ["game_date", "game_pk", "at_bat_number", "pitch_number"],
            ascending=[True, True, True, True],
        ).reset_index(drop=True)
        frame["source_start_date"] = chunk_start.isoformat()
        frame["source_end_date"] = chunk_end.isoformat()
        frame["loaded_at_utc"] = datetime.now(timezone.utc).isoformat()
        temporary_path = output_path.with_suffix(".parquet.tmp")
        try:
            frame.to_parquet(temporary_path, index=False)
            validate_partition(temporary_path)
            temporary_path.replace(output_path)
            empty_marker.unlink(missing_ok=True)
            cleanup_consolidated_daily_files(raw_dir, chunk_start, chunk_end, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        logging.info("Saved %s rows to %s", f"{len(frame):,}", output_path.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MLB Statcast data in restartable date partitions.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    parser.add_argument("--force", action="store_true", help="Replace existing raw date partitions.")
    parser.add_argument("--refresh-days", type=int, help="Refresh this many latest complete days.")
    args = parser.parse_args()

    config = load_config(args.config)
    paths = config["paths"]
    configure_logging(project_path(paths["log_file"]))
    parameters = config[args.mode]
    cache.enable()
    refresh_days = args.refresh_days if args.refresh_days is not None else int(parameters.get("refresh_days", 0))
    for resolved_range in resolved_mode_ranges(config, args.mode):
        extract_range(
            parameters=resolved_range,
            raw_dir=project_path(paths["raw_dir"]),
            force=args.force,
            refresh_days=refresh_days,
        )


if __name__ == "__main__":
    main()
