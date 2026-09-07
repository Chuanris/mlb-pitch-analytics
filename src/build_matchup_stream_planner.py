from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

from src.common import load_config, project_path
from src.extract_game_context import API_ROOT, fetch_json


FORECAST_API_ROOT = "https://api.open-meteo.com/v1/forecast"
PROFILE_KEYS = ("roto_balance", "strikeout_upside", "ratio_protection")
TEAM_ALIASES = {
    "ARI": "AZ",
    "CHW": "CWS",
    "KCR": "KC",
    "OAK": "ATH",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "WSN": "WSH",
}
WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Severe thunderstorm",
}


def normalize_team(value: str | None) -> str | None:
    if not value:
        return None
    code = str(value).upper()
    return TEAM_ALIASES.get(code, code)


def schedule_url(start_date: date, end_date: date) -> str:
    query = urlencode(
        {
            "sportId": 1,
            "gameType": "R",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "hydrate": "probablePitcher,team,venue",
        }
    )
    return f"{API_ROOT}/v1/schedule?{query}"


def weather_url(venues: list[dict], start_date: date, end_date: date) -> str:
    query = urlencode(
        {
            "latitude": ",".join(str(row["latitude"]) for row in venues),
            "longitude": ",".join(str(row["longitude"]) for row in venues),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "precipitation_probability",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ]
            ),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "UTC",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
    )
    return f"{FORECAST_API_ROOT}?{query}"


def recent_opponent_metrics(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT
            batter_team AS opponent_team,
            COUNT(plate_appearance_event) FILTER (
                WHERE plate_appearance_event IS NOT NULL
                  AND plate_appearance_event != 'truncated_pa'
            )::BIGINT AS plate_appearances,
            SUM(CASE WHEN plate_appearance_event IN ('strikeout', 'strikeout_double_play') THEN 1 ELSE 0 END)::BIGINT AS strikeouts,
            SUM(CASE WHEN plate_appearance_event = 'walk' THEN 1 ELSE 0 END)::BIGINT AS walks,
            SUM(batted_ball_flag)::BIGINT AS batted_balls,
            COUNT(*) FILTER (WHERE batted_ball_flag = 1 AND hard_hit_flag IS NOT NULL) AS measured_batted_balls,
            SUM(hard_hit_flag)::BIGINT AS hard_hits
        FROM silver.fact_pitch
        WHERE game_date BETWEEN ? AND ?
        GROUP BY batter_team
        """,
        [start_date, end_date],
    ).fetchdf()
    frame["opponent_team"] = frame["opponent_team"].map(normalize_team)
    frame["opponent_strikeout_rate"] = frame["strikeouts"] / frame["plate_appearances"]
    frame["opponent_walk_rate"] = frame["walks"] / frame["plate_appearances"]
    frame["opponent_hard_hit_rate"] = frame["hard_hits"] / frame["measured_batted_balls"].replace(0, np.nan)
    frame["strikeout_favorability_percentile"] = frame["opponent_strikeout_rate"].rank(
        method="average", pct=True
    )
    frame["walk_favorability_percentile"] = frame["opponent_walk_rate"].rank(
        method="average", pct=True, ascending=False
    )
    frame["hard_hit_favorability_percentile"] = frame["opponent_hard_hit_rate"].rank(
        method="average", pct=True, ascending=False
    )
    frame["opponent_matchup_signal"] = 100.0 * (
        0.50 * frame["strikeout_favorability_percentile"]
        + 0.25 * frame["walk_favorability_percentile"]
        + 0.25 * frame["hard_hit_favorability_percentile"]
    )
    return frame


def park_metrics(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT
            context.venue_id,
            ARG_MAX(context.venue_name, pitch.game_date) AS venue_name,
            SUM(pitch.batted_ball_flag)::BIGINT AS park_batted_balls,
            COUNT(*) FILTER (WHERE pitch.batted_ball_flag = 1 AND pitch.hard_hit_flag IS NOT NULL) AS park_measured_batted_balls,
            SUM(pitch.hard_hit_flag)::BIGINT AS park_hard_hits,
            COUNT(pitch.plate_appearance_event) FILTER (
                WHERE pitch.plate_appearance_event IS NOT NULL
                  AND pitch.plate_appearance_event != 'truncated_pa'
            )::BIGINT AS park_plate_appearances,
            SUM(CASE WHEN pitch.plate_appearance_event = 'home_run' THEN 1 ELSE 0 END)::BIGINT AS park_home_runs
        FROM silver.fact_pitch AS pitch
        JOIN silver.fact_game_context AS context USING (game_pk)
        GROUP BY context.venue_id
        HAVING park_batted_balls >= 500 AND park_plate_appearances >= 1000
        """
    ).fetchdf()
    frame["park_hard_hit_rate"] = frame["park_hard_hits"] / frame["park_measured_batted_balls"].replace(0, np.nan)
    frame["park_home_run_rate"] = frame["park_home_runs"] / frame["park_plate_appearances"]
    frame["park_contact_suppression_signal"] = 100.0 * (
        0.60 * frame["park_hard_hit_rate"].rank(method="average", pct=True, ascending=False)
        + 0.40 * frame["park_home_run_rate"].rank(method="average", pct=True, ascending=False)
    )
    return frame


def load_venues(path: Path) -> dict[int, dict]:
    frame = pd.read_parquet(path)
    rows = {}
    for row in frame.to_dict(orient="records"):
        venue_id = int(row["venue_id"])
        rows[venue_id] = row
    return rows


def scheduled_pitcher_slots(payload: dict, now_utc: datetime) -> list[dict]:
    slots = []
    for date_group in payload.get("dates", []):
        for game in date_group.get("games", []):
            status = game.get("status") or {}
            if str(status.get("abstractGameState") or "").lower() != "preview":
                continue
            game_datetime = datetime.fromisoformat(game["gameDate"].replace("Z", "+00:00"))
            if game_datetime < now_utc:
                continue
            for side, opponent_side in (("away", "home"), ("home", "away")):
                team_block = game["teams"][side]
                opponent_block = game["teams"][opponent_side]
                probable = team_block.get("probablePitcher") or {}
                slots.append(
                    {
                        "game_pk": int(game["gamePk"]),
                        "game_date": game.get("officialDate"),
                        "game_datetime_utc": game_datetime,
                        "home_away": side.title(),
                        "pitcher_id": probable.get("id"),
                        "pitcher_name": probable.get("fullName") or "TBD",
                        "pitcher_team": normalize_team(team_block["team"].get("abbreviation")),
                        "opponent_team": normalize_team(opponent_block["team"].get("abbreviation")),
                        "opponent_name": opponent_block["team"].get("name"),
                        "venue_id": int(game["venue"]["id"]),
                        "venue_name": game["venue"].get("name"),
                        "probable_status": "Confirmed probable" if probable.get("id") else "TBD",
                        "game_status": status.get("detailedState"),
                    }
                )
    return slots


def forecast_by_venue(
    venue_rows: list[dict],
    start_date: date,
    end_date: date,
) -> dict[int, dict]:
    usable = [
        row
        for row in venue_rows
        if pd.notna(row.get("latitude")) and pd.notna(row.get("longitude"))
    ]
    if not usable:
        return {}
    try:
        payload = fetch_json(weather_url(usable, start_date, end_date))
    except Exception as exc:
        logging.warning("Weather forecast unavailable: %s", exc)
        return {}
    responses = payload if isinstance(payload, list) else [payload]
    forecasts = {}
    for venue, response in zip(usable, responses):
        hourly = response.get("hourly") or {}
        if not hourly.get("time"):
            continue
        frame = pd.DataFrame(hourly)
        frame["forecast_time_utc"] = pd.to_datetime(frame["time"], utc=True)
        forecasts[int(venue["venue_id"])] = frame
    return forecasts


def weather_for_game(
    forecast: pd.DataFrame | None,
    game_datetime: datetime,
    roof_type: str | None,
) -> dict:
    roof = str(roof_type or "Unknown")
    if roof.lower() == "dome":
        risk = "Controlled environment"
    else:
        risk = "Forecast unavailable"
    if forecast is None or forecast.empty:
        return {
            "temperature_f": None,
            "precipitation_probability": None,
            "weather_condition": None,
            "wind_speed_mph": None,
            "wind_direction_degrees": None,
            "weather_risk": risk,
            "roof_type": roof,
        }
    distances = (forecast["forecast_time_utc"] - pd.Timestamp(game_datetime)).abs()
    nearest = forecast.loc[distances.idxmin()]
    if distances.min() > pd.Timedelta(hours=2):
        return {
            "temperature_f": None,
            "precipitation_probability": None,
            "weather_condition": None,
            "wind_speed_mph": None,
            "wind_direction_degrees": None,
            "weather_risk": risk,
            "roof_type": roof,
        }
    precipitation = pd.to_numeric(nearest.get("precipitation_probability"), errors="coerce")
    code = pd.to_numeric(nearest.get("weather_code"), errors="coerce")
    if roof.lower() == "dome":
        risk = "Controlled environment"
    elif pd.notna(precipitation) and precipitation >= 50:
        risk = "Roof decision" if "retract" in roof.lower() else "Elevated rain risk"
    elif pd.notna(precipitation) and precipitation >= 25:
        risk = "Weather watch"
    else:
        risk = "Low weather risk"
    return {
        "temperature_f": pd.to_numeric(nearest.get("temperature_2m"), errors="coerce"),
        "precipitation_probability": precipitation,
        "weather_condition": WEATHER_CODES.get(int(code), "Other") if pd.notna(code) else None,
        "wind_speed_mph": pd.to_numeric(nearest.get("wind_speed_10m"), errors="coerce"),
        "wind_direction_degrees": pd.to_numeric(nearest.get("wind_direction_10m"), errors="coerce"),
        "weather_risk": risk,
        "roof_type": roof,
    }


def stream_score(skill_signal: float | None, matchup_signal: float | None, park_signal: float | None) -> tuple[float | None, float]:
    if skill_signal is None or pd.isna(skill_signal):
        return None, 0.0
    weighted_values = [(float(skill_signal), 0.65)]
    if matchup_signal is not None and pd.notna(matchup_signal):
        weighted_values.append((float(matchup_signal), 0.25))
    if park_signal is not None and pd.notna(park_signal):
        weighted_values.append((float(park_signal), 0.10))
    coverage = sum(weight for _, weight in weighted_values)
    score = sum(value * weight for value, weight in weighted_values) / coverage
    return round(score, 1), coverage


def stream_tier(score: float | None, probable_status: str) -> str:
    if probable_status != "Confirmed probable":
        return "Awaiting probable starter"
    if score is None or pd.isna(score):
        return "Insufficient recent sample"
    if score >= 80:
        return "Priority stream research"
    if score >= 70:
        return "Strong matchup research"
    if score >= 60:
        return "League-context dependent"
    return "Low-priority matchup"


def local_game_time(game_datetime: datetime, venue: dict) -> tuple[str, str]:
    time_zone_id = venue.get("time_zone_id")
    local = game_datetime.astimezone(ZoneInfo(time_zone_id)) if time_zone_id else game_datetime
    clock = local.strftime("%I:%M %p").lstrip("0")
    return local.isoformat(), f"{local:%a %b} {local.day}, {clock}"


def build_rows(
    slots: list[dict],
    radar: pd.DataFrame,
    opponents: pd.DataFrame,
    parks: pd.DataFrame,
    venues: dict[int, dict],
    forecasts: dict[int, pd.DataFrame],
) -> pd.DataFrame:
    radar_lookup = {
        (int(row.pitcher_id), row.profile_key): row._asdict()
        for row in radar.itertuples(index=False)
    }
    opponent_lookup = {
        row["opponent_team"]: row for row in opponents.to_dict(orient="records")
    }
    park_lookup = {
        int(row["venue_id"]): row for row in parks.to_dict(orient="records")
    }
    rows = []
    for slot in slots:
        venue = venues.get(slot["venue_id"], {})
        local_iso, local_label = local_game_time(slot["game_datetime_utc"], venue)
        weather = weather_for_game(
            forecasts.get(slot["venue_id"]), slot["game_datetime_utc"], venue.get("roof_type")
        )
        opponent = opponent_lookup.get(slot["opponent_team"], {})
        park = park_lookup.get(slot["venue_id"], {})
        for profile_key in PROFILE_KEYS:
            pitcher = (
                radar_lookup.get((int(slot["pitcher_id"]), profile_key), {})
                if slot["pitcher_id"] is not None
                else {}
            )
            score, score_coverage = stream_score(
                pitcher.get("fantasy_signal"),
                opponent.get("opponent_matchup_signal"),
                park.get("park_contact_suppression_signal"),
            )
            rows.append(
                {
                    **slot,
                    "game_datetime_utc": slot["game_datetime_utc"].isoformat(),
                    "game_datetime_local": local_iso,
                    "game_time_label": local_label,
                    "profile_key": profile_key,
                    "profile": pitcher.get("profile") or profile_key.replace("_", " ").title(),
                    "fantasy_signal": pitcher.get("fantasy_signal"),
                    "fantasy_rank": pitcher.get("rank"),
                    "fantasy_trend": pitcher.get("trend_status"),
                    "fantasy_sample_strength": pitcher.get("sample_strength"),
                    "opponent_plate_appearances": opponent.get("plate_appearances"),
                    "opponent_strikeout_rate": opponent.get("opponent_strikeout_rate"),
                    "opponent_walk_rate": opponent.get("opponent_walk_rate"),
                    "opponent_hard_hit_rate": opponent.get("opponent_hard_hit_rate"),
                    "opponent_matchup_signal": opponent.get("opponent_matchup_signal"),
                    "park_hard_hit_rate": park.get("park_hard_hit_rate"),
                    "park_home_run_rate": park.get("park_home_run_rate"),
                    "park_contact_suppression_signal": park.get("park_contact_suppression_signal"),
                    **weather,
                    "stream_score": score,
                    "stream_score_coverage": score_coverage,
                    "stream_tier": stream_tier(score, slot["probable_status"]),
                }
            )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["stream_rank"] = frame.groupby("profile_key")["stream_score"].rank(
            method="first", ascending=False, na_option="bottom"
        )
        frame.loc[frame["stream_score"].isna(), "stream_rank"] = np.nan
        frame = frame.sort_values(
            ["profile_key", "game_datetime_utc", "stream_score"],
            ascending=[True, True, False],
        )
    return frame


def validate_output(frame: pd.DataFrame, scheduled_slots: int) -> None:
    if scheduled_slots == 0:
        if not frame.empty:
            raise RuntimeError("Stream planner produced rows without scheduled pitcher slots")
        return
    expected_rows = scheduled_slots * len(PROFILE_KEYS)
    if len(frame) != expected_rows:
        raise RuntimeError(f"Expected {expected_rows} stream planner rows, found {len(frame)}")
    if frame.duplicated(["game_pk", "pitcher_team", "profile_key"]).any():
        raise RuntimeError("Duplicate game/team/profile keys in stream planner output")
    if set(frame["profile_key"]) != set(PROFILE_KEYS):
        raise RuntimeError("Stream planner profile coverage is incomplete")
    if not frame["stream_score"].dropna().between(0, 100).all():
        raise RuntimeError("Stream score outside zero-to-100 bounds")
    if frame.loc[frame["probable_status"] == "TBD", "stream_score"].notna().any():
        raise RuntimeError("TBD pitcher slots must remain unscored")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an upcoming matchup-aware fantasy pitching stream planner.")
    parser.add_argument("--config", default="config/pipeline_config.json")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    config = load_config(args.config)
    outputs_dir = project_path(config["paths"]["outputs_dir"])
    database_path = project_path(config["paths"]["database"])
    venue_path = project_path(config["paths"]["venue_reference"])
    fantasy_dir = outputs_dir / "fantasy"
    fantasy_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        data_through = connection.execute("SELECT MAX(game_date) FROM silver.fact_pitch").fetchone()[0]
        local_today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        start_date = max(data_through + timedelta(days=1), local_today)
        end_date = start_date + timedelta(days=max(1, args.days) - 1)
        opponents = recent_opponent_metrics(connection, data_through - timedelta(days=29), data_through)
        parks = park_metrics(connection)
    finally:
        connection.close()

    schedule_source = schedule_url(start_date, end_date)
    payload = fetch_json(schedule_source)
    now_utc = datetime.now(timezone.utc)
    slots = scheduled_pitcher_slots(payload, now_utc)
    venues = load_venues(venue_path)
    scheduled_venues = [venues[venue_id] for venue_id in sorted({row["venue_id"] for row in slots}) if venue_id in venues]
    forecasts = forecast_by_venue(scheduled_venues, start_date, end_date)
    radar = pd.read_csv(fantasy_dir / "pitcher_fantasy_radar.csv")
    radar = radar[(radar["window_days"] == 14) & radar["profile_key"].isin(PROFILE_KEYS)].copy()
    frame = build_rows(slots, radar, opponents, parks, venues, forecasts)
    validate_output(frame, len(slots))

    output_path = fantasy_dir / "matchup_stream_planner.csv"
    temporary = output_path.with_suffix(".csv.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(output_path)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_through": data_through.isoformat(),
        "schedule_start": start_date.isoformat(),
        "schedule_end": end_date.isoformat(),
        "schedule_source": schedule_source,
        "weather_source": FORECAST_API_ROOT,
        "rows": int(len(frame)),
        "scheduled_pitcher_slots": len(slots),
        "confirmed_probable_slots": sum(row["probable_status"] == "Confirmed probable" for row in slots),
        "profiles": list(PROFILE_KEYS),
        "stream_score": {
            "formula": "65% recent pitcher skill + 25% opponent batting tendency + 10% historical park contact suppression, renormalized when optional matchup or park context is unavailable",
            "pitcher_window_days": 14,
            "opponent_window_days": 30,
            "weather_usage": "risk flag only; weather does not change stream score",
        },
        "limitations": [
            "Probable pitchers can change after publication and TBD slots are never guessed.",
            "Opponent and park components are descriptive recent/historical tendencies, not causal opponent or park effects.",
            "Weather is a forecast near scheduled first pitch and can change; roof status is not confirmed.",
            "Roster availability, league scoring, innings limits, and transaction rules are not available.",
            "Stream score is a research ranking, not a start/sit guarantee or projected fantasy points.",
        ],
    }
    (fantasy_dir / "matchup_stream_planner_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Matchup stream planner: {len(frame):,} profile rows across {len(slots):,} scheduled pitcher slots "
        f"({manifest['confirmed_probable_slots']:,} confirmed) -> {output_path}"
    )


if __name__ == "__main__":
    from src.artifact_lineage import run_versioned
    run_versioned("build_matchup_stream_planner", main)
