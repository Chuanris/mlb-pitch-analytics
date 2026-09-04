from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def project_path(relative_path: str | Path) -> Path:
    path = Path(relative_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def date_chunks(start_date: date, end_date: date, chunk_days: int) -> Iterator[tuple[date, date]]:
    if chunk_days < 1:
        raise ValueError("chunk_days must be at least 1")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")

    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end_date)
        yield chunk_start, chunk_end
        chunk_start = chunk_end + timedelta(days=1)


def resolved_mode_ranges(config: dict, mode: str, today: date | None = None) -> list[dict]:
    if mode not in config:
        raise KeyError(f"Mode is missing from config: {mode}")

    parameters = config[mode]
    configured_ranges = parameters.get("ranges") or [
        {
            "season": config.get("season", date.fromisoformat(parameters["start_date"]).year),
            "start_date": parameters["start_date"],
            "end_date": parameters["end_date"],
            "chunk_days": parameters["chunk_days"],
        }
    ]
    current_day = today or date.today()
    latest_complete_day = current_day - timedelta(days=1)
    resolved = []
    for configured in configured_ranges:
        start = date.fromisoformat(configured["start_date"])
        scheduled_end = date.fromisoformat(configured["end_date"])
        dynamic = bool(configured.get("latest_complete_day", False))
        end = min(scheduled_end, latest_complete_day) if dynamic else scheduled_end
        if end < start:
            continue
        resolved.append(
            {
                "season": int(configured.get("season", start.year)),
                "start_date": start,
                "end_date": end,
                "chunk_days": int(configured.get("chunk_days", parameters.get("chunk_days", 7))),
                "latest_complete_day": dynamic,
            }
        )
    if not resolved:
        raise ValueError(f"Mode {mode} has no active date ranges as of {current_day}")
    return resolved


def partition_ranges(parameters: dict) -> Iterator[tuple[date, date]]:
    start = parameters["start_date"]
    end = parameters["end_date"]
    chunk_days = int(parameters["chunk_days"])
    if not parameters.get("latest_complete_day") or chunk_days != 7:
        yield from date_chunks(start, end, chunk_days)
        return

    # Active seasons use stable Monday-Sunday files. Partial weeks remain daily
    # files until the next Monday, when extraction consolidates them safely.
    cursor = start
    while cursor <= end:
        full_week_end = cursor + timedelta(days=6)
        if cursor.weekday() == 0 and full_week_end <= end:
            yield cursor, full_week_end
            cursor = full_week_end + timedelta(days=1)
        else:
            yield cursor, cursor
            cursor += timedelta(days=1)


def configured_partition_paths(config: dict, mode: str, today: date | None = None) -> list[Path]:
    raw_dir = project_path(config["paths"]["raw_dir"])
    return [
        raw_dir / f"statcast_{chunk_start}_{chunk_end}.parquet"
        for parameters in resolved_mode_ranges(config, mode, today=today)
        for chunk_start, chunk_end in partition_ranges(parameters)
    ]


def configured_game_context_paths(
    config: dict,
    mode: str,
    today: date | None = None,
) -> list[Path]:
    context_dir = project_path(config["paths"]["game_context_dir"])
    return [
        context_dir / f"game_context_{chunk_start}_{chunk_end}.parquet"
        for parameters in resolved_mode_ranges(config, mode, today=today)
        for chunk_start, chunk_end in partition_ranges(parameters)
    ]


def empty_partition_marker(path: Path) -> Path:
    return path.with_suffix(".empty.json")
