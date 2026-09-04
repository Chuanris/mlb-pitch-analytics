from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq

from src.common import load_config, partition_ranges, project_path, resolved_mode_ranges


API_ROOT = "https://statsapi.mlb.com/api"
USER_AGENT = "MLB-Pitch-Analytics/1.0 (portfolio data pipeline)"
WIND_PATTERN = re.compile(r"(?P<speed>\d+(?:\.\d+)?)\s*mph(?:,\s*(?P<direction>.*))?", re.I)


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def fetch_json(url: str, attempts: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt)
    raise RuntimeError(f"MLB Stats API request failed after {attempts} attempts: {url}") from last_error


def schedule_url(start_date: date, end_date: date) -> str:
    query = urlencode(
        {
            "sportId": 1,
            "gameType": "R",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "hydrate": "venue,weather",
        }
    )
    return f"{API_ROOT}/v1/schedule?{query}"


def venue_url(venue_id: int) -> str:
    return f"{API_ROOT}/v1/venues/{venue_id}?hydrate=location,timezone,fieldInfo"


def validate_partition(path: Path) -> int:
    try:
        row_count = pq.ParquetFile(path).metadata.num_rows
    except Exception as exc:
        raise RuntimeError(f"Unreadable game-context Parquet partition: {path}") from exc
    if row_count < 1:
        raise RuntimeError(f"Game-context partition is empty: {path}")
    return row_count


def parse_wind(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    match = WIND_PATTERN.search(value)
    if not match:
        return None, value.strip() or None
    speed = float(match.group("speed"))
    direction = (match.group("direction") or "").strip() or None
    return speed, direction


def load_venue_cache(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    return {
        int(row["venue_id"]): row.to_dict()
        for _, row in frame.iterrows()
    }


def fetch_venue(venue_id: int, fallback_name: str | None = None) -> dict:
    payload = fetch_json(venue_url(venue_id))
    venues = payload.get("venues") or []
    if not venues:
        raise RuntimeError(f"MLB venue response did not include venue {venue_id}")
    venue = venues[0]
    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    time_zone = venue.get("timeZone") or {}
    field = venue.get("fieldInfo") or {}
    return {
        "venue_id": venue_id,
        "venue_name": venue.get("name") or fallback_name,
        "city": location.get("city"),
        "state": location.get("stateAbbrev") or location.get("state"),
        "country": location.get("country"),
        "latitude": coordinates.get("latitude"),
        "longitude": coordinates.get("longitude"),
        "azimuth_angle": location.get("azimuthAngle"),
        "elevation_ft": location.get("elevation"),
        "time_zone_id": time_zone.get("id"),
        "roof_type": field.get("roofType"),
        "turf_type": field.get("turfType"),
        "source_url": venue_url(venue_id),
        "loaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_venue_cache(path: Path, venues: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(venues.values()).sort_values("venue_id").reset_index(drop=True)
    temporary = path.with_suffix(".parquet.tmp")
    try:
        frame.to_parquet(temporary, index=False)
        validate_partition(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def local_time_fields(game_datetime: str, time_zone_id: str | None) -> dict:
    utc_value = datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
    if time_zone_id:
        local_value = utc_value.astimezone(ZoneInfo(time_zone_id))
    else:
        local_value = utc_value
    hour = local_value.hour + local_value.minute / 60.0
    return {
        "game_datetime_utc": utc_value.isoformat(),
        "game_datetime_local": local_value.isoformat(),
        "local_start_hour": hour,
        "local_day_of_week": local_value.weekday(),
        "local_month": local_value.month,
        "weekend_flag": int(local_value.weekday() >= 5),
    }


def game_row(game: dict, venue: dict, source_start: date, source_end: date) -> dict:
    weather = game.get("weather") or {}
    wind_speed, wind_direction = parse_wind(weather.get("wind"))
    condition = weather.get("condition")
    roof_type = venue.get("roof_type")
    condition_lower = str(condition or "").lower()
    indoor = str(roof_type or "").lower() == "dome" or "dome" in condition_lower or "roof closed" in condition_lower
    return {
        "game_pk": int(game["gamePk"]),
        "game_status": (game.get("status") or {}).get("detailedState"),
        "official_date": game.get("officialDate"),
        "day_night": game.get("dayNight"),
        "venue_id": int(game["venue"]["id"]),
        "venue_name": game["venue"].get("name") or venue.get("venue_name"),
        **local_time_fields(game["gameDate"], venue.get("time_zone_id")),
        "temperature_f": pd.to_numeric(weather.get("temp"), errors="coerce"),
        "weather_condition": condition,
        "wind_speed_mph": wind_speed,
        "wind_direction": wind_direction,
        "wind_out_flag": int(str(wind_direction or "").lower().startswith("out to")),
        "wind_in_flag": int(str(wind_direction or "").lower().startswith("in from")),
        "crosswind_flag": int(str(wind_direction or "").lower() in {"l to r", "r to l"}),
        "indoor_flag": int(indoor),
        "source_start_date": source_start.isoformat(),
        "source_end_date": source_end.isoformat(),
        "source_url": schedule_url(source_start, source_end),
        "loaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def status_priority(game: dict) -> int:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    detailed = str(status.get("detailedState") or "").lower()
    if abstract == "final" or detailed == "final":
        return 3
    if abstract == "live":
        return 2
    if "postpon" in detailed or "cancel" in detailed:
        return 0
    return 1


def deduplicate_schedule_games(games: list[dict]) -> list[dict]:
    selected: dict[int, dict] = {}
    for game in games:
        game_pk = int(game["gamePk"])
        existing = selected.get(game_pk)
        if existing is None or status_priority(game) > status_priority(existing):
            selected[game_pk] = game
    return list(selected.values())


def cleanup_daily_files(context_dir: Path, start: date, end: date, keep: Path) -> None:
    if start == end:
        return
    resolved = context_dir.resolve()
    cursor = start
    while cursor <= end:
        daily = context_dir / f"game_context_{cursor}_{cursor}.parquet"
        if daily != keep and daily.parent.resolve() == resolved:
            daily.unlink(missing_ok=True)
        cursor += timedelta(days=1)


def extract_range(
    parameters: dict,
    context_dir: Path,
    venue_path: Path,
    venue_cache: dict[int, dict],
    force: bool,
    refresh_days: int,
) -> None:
    context_dir.mkdir(parents=True, exist_ok=True)
    refresh_after = (
        parameters["end_date"] - timedelta(days=max(0, refresh_days - 1))
        if parameters.get("latest_complete_day") and refresh_days > 0
        else None
    )
    for chunk_start, chunk_end in partition_ranges(parameters):
        output_path = context_dir / f"game_context_{chunk_start}_{chunk_end}.parquet"
        refresh = force or (refresh_after is not None and chunk_end >= refresh_after)
        if output_path.exists() and not refresh:
            logging.info("Skip valid game context: %s (%s games)", output_path.name, validate_partition(output_path))
            continue

        logging.info("Extract MLB game context %s through %s", chunk_start, chunk_end)
        payload = fetch_json(schedule_url(chunk_start, chunk_end))
        raw_games = [game for date_group in payload.get("dates", []) for game in date_group.get("games", [])]
        games = deduplicate_schedule_games(raw_games)
        if len(games) != len(raw_games):
            logging.warning(
                "Deduplicated %s rescheduled/postponed schedule row(s) by game_pk",
                len(raw_games) - len(games),
            )
        if not games:
            raise RuntimeError(f"No MLB regular-season schedule rows for {chunk_start} through {chunk_end}")

        for game in games:
            venue_id = int(game["venue"]["id"])
            if venue_id not in venue_cache:
                venue_cache[venue_id] = fetch_venue(venue_id, game["venue"].get("name"))
                write_venue_cache(venue_path, venue_cache)

        frame = pd.DataFrame(
            [
                game_row(game, venue_cache[int(game["venue"]["id"])], chunk_start, chunk_end)
                for game in games
            ]
        ).sort_values(["official_date", "game_pk"])
        if frame["game_pk"].duplicated().any():
            raise RuntimeError(f"Duplicate game_pk values in MLB schedule partition {chunk_start} through {chunk_end}")
        temporary = output_path.with_suffix(".parquet.tmp")
        try:
            frame.to_parquet(temporary, index=False)
            validate_partition(temporary)
            temporary.replace(output_path)
            cleanup_daily_files(context_dir, chunk_start, chunk_end, output_path)
        finally:
            temporary.unlink(missing_ok=True)
        logging.info("Saved %s games to %s", len(frame), output_path.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MLB game time, venue, and game-weather context.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--refresh-days", type=int)
    args = parser.parse_args()

    config = load_config(args.config)
    paths = config["paths"]
    configure_logging(project_path(paths["log_file"]))
    context_dir = project_path(paths["game_context_dir"])
    venue_path = project_path(paths["venue_reference"])
    venues = load_venue_cache(venue_path)
    parameters = config[args.mode]
    refresh_days = args.refresh_days if args.refresh_days is not None else int(parameters.get("refresh_days", 0))
    for resolved_range in resolved_mode_ranges(config, args.mode):
        extract_range(
            resolved_range,
            context_dir,
            venue_path,
            venues,
            force=args.force,
            refresh_days=refresh_days,
        )
    write_venue_cache(venue_path, venues)


if __name__ == "__main__":
    main()
