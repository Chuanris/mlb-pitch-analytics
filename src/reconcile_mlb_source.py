"""Reconcile local Statcast facts with live MLB schedule and play-by-play evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb

from src.common import load_config, project_path


API_ROOT = "https://statsapi.mlb.com/api"
USER_AGENT = "MLB-Pitch-Analytics/1.0 (portfolio source reconciliation)"
COMPLETED_STATUSES = {"Final", "Game Over", "Completed Early"}


class SourceUnavailableError(RuntimeError):
    """Raised when official MLB evidence cannot be retrieved."""


def fetch_json(url: str, attempts: int = 3) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except Exception as error:
            last_error = error
            if attempt < attempts:
                time.sleep(attempt)
    raise SourceUnavailableError(
        f"Official MLB request failed after {attempts} attempts: {url}"
    ) from last_error


def schedule_url(day: date) -> str:
    query = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": day.isoformat(),
        "endDate": day.isoformat(),
    })
    return f"{API_ROOT}/v1/schedule?{query}"


def game_feed_url(game_pk: int) -> str:
    return f"{API_ROOT}/v1.1/game/{game_pk}/feed/live"


def payload_digest(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def final_schedule_games(payload: dict, day: date) -> dict[int, str]:
    games: dict[int, str] = {}
    for date_group in payload.get("dates") or []:
        for game in date_group.get("games") or []:
            status = game.get("status") or {}
            if status.get("abstractGameState") != "Final":
                continue
            official_date = str(game.get("officialDate") or "")
            if official_date != day.isoformat():
                continue
            games[int(game["gamePk"])] = str(status.get("detailedState") or "Final")
    return games


def feed_plate_appearance_counts(payload: dict, game_pk: int) -> dict[int, int]:
    payload_game_pk = (payload.get("gameData") or {}).get("game", {}).get("pk")
    if payload_game_pk is not None and int(payload_game_pk) != game_pk:
        raise ValueError(
            f"MLB live feed returned game {payload_game_pk} when {game_pk} was requested"
        )

    counts: dict[int, int] = {}
    plays = ((payload.get("liveData") or {}).get("plays") or {}).get("allPlays") or []
    for play in plays:
        pitch_count = sum(
            1 for event in play.get("playEvents") or [] if event.get("isPitch") is True
        )
        if pitch_count == 0:
            continue
        at_bat_index = (play.get("about") or {}).get("atBatIndex")
        if at_bat_index is None:
            raise ValueError(f"MLB live feed game {game_pk} has a pitch without atBatIndex")
        at_bat_number = int(at_bat_index) + 1
        if at_bat_number in counts:
            raise ValueError(
                f"MLB live feed game {game_pk} repeats atBatIndex {at_bat_index}"
            )
        counts[at_bat_number] = pitch_count
    return counts


def _add_mismatch(target: dict, name: str, value) -> None:
    if value:
        target[name] = value


def reconcile_date(
    connection,
    day: date,
    *,
    fetch_json: Callable[[str], dict] = fetch_json,
    now: datetime | None = None,
) -> dict:
    """Compare one official regular-season date with local game and pitch grains."""
    checked_at = now or datetime.now(timezone.utc)
    source_url = schedule_url(day)
    schedule = fetch_json(source_url)
    official_games = final_schedule_games(schedule, day)
    official_ids = set(official_games)

    base = {
        "checked_at_utc": checked_at.astimezone(timezone.utc).isoformat(),
        "official_date": day.isoformat(),
        "claim": {
            "pass_means": (
                "At check time, local completed-game coverage and per-plate-appearance "
                "pitch counts agree with the official MLB schedule and live feeds."
            ),
            "limits": (
                "A pass does not establish that MLB upstream services are error-free, "
                "immutable, or independently audited."
            ),
        },
        "sources": {
            "schedule_url": source_url,
            "schedule_sha256": payload_digest(schedule),
            "game_feed_sha256": {},
        },
    }
    if not official_games:
        return {
            **base,
            "status": "attention",
            "assessment": "unknown_no_final_games",
            "metrics": {
                "official_final_games": 0,
                "local_completed_context_games": 0,
                "local_pitch_games": 0,
                "play_by_play_games_checked": 0,
                "official_pitch_events": 0,
                "local_pitch_rows": 0,
            },
            "mismatches": {},
            "action": "Choose a date with official final regular-season games.",
        }

    official_id_parameters = sorted(official_ids)
    official_id_placeholders = ", ".join("?" for _ in official_id_parameters)
    relevant_parameters = [day, *official_id_parameters]

    context_rows = connection.execute(f"""
        SELECT game_pk, official_date, game_status
        FROM silver.fact_game_context
        WHERE official_date = ? OR game_pk IN ({official_id_placeholders})
    """, relevant_parameters).fetchall()
    local_completed_ids = {
        int(game_pk)
        for game_pk, official_date, game_status in context_rows
        if official_date == day and game_status in COMPLETED_STATUSES
    }
    context_dates: dict[int, set[str]] = {}
    for game_pk, official_date, _ in context_rows:
        context_dates.setdefault(int(game_pk), set()).add(str(official_date))

    pitch_rows = connection.execute(f"""
        SELECT game_pk, game_date, at_bat_number, COUNT(*) AS pitch_rows
        FROM silver.fact_pitch
        WHERE game_date = ? OR game_pk IN ({official_id_placeholders})
        GROUP BY game_pk, game_date, at_bat_number
    """, relevant_parameters).fetchall()
    local_pa_counts = {
        (int(game_pk), int(at_bat_number)): int(count)
        for game_pk, game_date, at_bat_number, count in pitch_rows
        if game_date == day
    }
    local_pitch_ids = {game_pk for game_pk, _ in local_pa_counts}
    pitch_dates: dict[int, set[str]] = {}
    for game_pk, game_date, _, _ in pitch_rows:
        pitch_dates.setdefault(int(game_pk), set()).add(str(game_date))

    checked_game_ids = official_ids & local_pitch_ids
    official_pa_counts: dict[tuple[int, int], int] = {}
    for game_pk in sorted(checked_game_ids):
        feed_url = game_feed_url(game_pk)
        feed = fetch_json(feed_url)
        base["sources"]["game_feed_sha256"][str(game_pk)] = payload_digest(feed)
        for at_bat_number, count in feed_plate_appearance_counts(feed, game_pk).items():
            official_pa_counts[(game_pk, at_bat_number)] = count

    checked_local_pa_counts = {
        key: count
        for key, count in local_pa_counts.items()
        if key[0] in checked_game_ids
    }
    missing_pa = sorted(set(official_pa_counts) - set(checked_local_pa_counts))
    unexpected_pa = sorted(set(checked_local_pa_counts) - set(official_pa_counts))
    count_mismatches = [
        {
            "game_pk": game_pk,
            "at_bat_number": at_bat_number,
            "official": official_pa_counts[(game_pk, at_bat_number)],
            "local": checked_local_pa_counts[(game_pk, at_bat_number)],
        }
        for game_pk, at_bat_number in sorted(
            set(official_pa_counts) & set(checked_local_pa_counts)
        )
        if official_pa_counts[(game_pk, at_bat_number)]
        != checked_local_pa_counts[(game_pk, at_bat_number)]
    ]

    missing_context = sorted(official_ids - local_completed_ids)
    missing_pitch = sorted(official_ids - local_pitch_ids)
    mismatches: dict = {}
    _add_mismatch(mismatches, "missing_context_games", missing_context)
    _add_mismatch(
        mismatches,
        "unexpected_completed_context_games",
        sorted(local_completed_ids - official_ids),
    )
    _add_mismatch(mismatches, "missing_pitch_games", missing_pitch)
    _add_mismatch(
        mismatches,
        "unexpected_pitch_games",
        sorted(local_pitch_ids - official_ids),
    )
    _add_mismatch(
        mismatches,
        "context_games_on_other_dates",
        [
            {"game_pk": game_pk, "dates": sorted(context_dates[game_pk])}
            for game_pk in missing_context
            if game_pk in context_dates
        ],
    )
    _add_mismatch(
        mismatches,
        "pitch_games_on_other_dates",
        [
            {"game_pk": game_pk, "dates": sorted(pitch_dates[game_pk])}
            for game_pk in missing_pitch
            if game_pk in pitch_dates
        ],
    )
    _add_mismatch(
        mismatches,
        "missing_plate_appearances",
        [
            {"game_pk": game_pk, "at_bat_number": at_bat_number}
            for game_pk, at_bat_number in missing_pa
        ],
    )
    _add_mismatch(
        mismatches,
        "unexpected_plate_appearances",
        [
            {"game_pk": game_pk, "at_bat_number": at_bat_number}
            for game_pk, at_bat_number in unexpected_pa
        ],
    )
    _add_mismatch(
        mismatches,
        "plate_appearance_pitch_counts",
        count_mismatches,
    )

    status = "error" if mismatches else "pass"
    assessment = "source_mismatch" if mismatches else "source_reconciled"
    return {
        **base,
        "status": status,
        "assessment": assessment,
        "metrics": {
            "official_final_games": len(official_ids),
            "local_completed_context_games": len(local_completed_ids),
            "local_pitch_games": len(local_pitch_ids),
            "play_by_play_games_checked": len(checked_game_ids),
            "play_by_play_games_skipped": len(official_ids - checked_game_ids),
            "official_plate_appearances": len(official_pa_counts),
            "local_plate_appearances": len(checked_local_pa_counts),
            "official_pitch_events": sum(official_pa_counts.values()),
            "local_pitch_rows": sum(checked_local_pa_counts.values()),
        },
        "mismatches": mismatches,
        "action": (
            "Inspect the listed game and plate-appearance mismatches before claiming source reconciliation."
            if mismatches
            else ""
        ),
    }


def write_output(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        database = project_path(config["paths"]["database"])
        with duckdb.connect(str(database), read_only=True) as connection:
            result = reconcile_date(connection, args.date)
    except SourceUnavailableError as error:
        result = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "official_date": args.date.isoformat(),
            "status": "attention",
            "assessment": "unknown_source_unavailable",
            "detail": str(error),
            "action": "Retry the official MLB source before making a completeness claim.",
        }
    except (duckdb.Error, ValueError) as error:
        result = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "official_date": args.date.isoformat(),
            "status": "error",
            "assessment": "reconciliation_failure",
            "detail": f"{type(error).__name__}: {error}",
            "action": "Inspect the local schema or official source contract before retrying.",
        }

    if args.output:
        write_output(project_path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1 if result["status"] == "attention" else 2


if __name__ == "__main__":
    raise SystemExit(main())
