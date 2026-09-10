"""Create a small deterministic DuckDB source for dbt CI and local smoke tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


RAW_COLUMNS = (
    "pitch_type, pitch_name, game_date, game_year, game_pk, at_bat_number, "
    "pitch_number, inning, inning_topbot, pitcher, player_name, batter, stand, "
    "p_throws, home_team, away_team, balls, strikes, description, events, zone, "
    "release_speed, release_spin_rate, pfx_x, pfx_z, launch_speed, "
    "estimated_woba_using_speedangle, game_type, loaded_at_utc"
)

RAW_ROWS = [
    ("FF", "4-Seam Fastball", "2025-04-01", 2025, 1001, 1, 1, 1, "Top", 10, "Ada Ace", 101, "R", "R", "LAD", "SF", 0, 0, "called_strike", None, 5, 95.0, 2400, -0.2, 1.1, None, None, "R", "2025-04-04T12:00:00Z"),
    ("FF", "4-Seam Fastball", "2025-04-01", 2025, 1001, 1, 2, 1, "Top", 10, "Ada Ace", 101, "R", "R", "LAD", "SF", 0, 1, "swinging_strike", None, 11, 96.0, 2420, -0.1, 1.2, None, None, "R", "2025-04-04T12:00:00Z"),
    ("SL", "Slider", "2025-04-01", 2025, 1001, 1, 3, 1, "Top", 10, "Ada Ace", 101, "R", "R", "LAD", "SF", 0, 2, "hit_into_play", "single", 8, 87.0, 2600, 0.5, 0.1, 98.0, 0.61, "R", "2025-04-04T12:00:00Z"),
    ("SL", "Slider", "2025-04-01", 2025, 1001, 1, 3, 1, "Top", 10, "Ada Ace", 101, "R", "R", "LAD", "SF", 0, 2, "hit_into_play", "field_out", 8, 86.0, 2550, 0.4, 0.1, 80.0, 0.15, "R", "2025-04-04T11:00:00Z"),
    ("CH", "Changeup", "2025-04-01", 2025, 1001, 2, 1, 1, "Top", 10, "Ada Ace", 102, "R", "R", "LAD", "SF", 0, 0, "ball", None, 12, 86.0, 1750, -0.6, 0.4, None, None, "R", "2025-04-04T12:00:00Z"),
    ("CH", "Changeup", "2025-04-01", 2025, 1001, 2, 2, 1, "Top", 10, "Ada Ace", 102, "R", "R", "LAD", "SF", 1, 0, "foul", None, 12, 87.0, 1780, -0.5, 0.5, None, None, "R", "2025-04-04T12:00:00Z"),
    ("CH", "Changeup", "2025-04-01", 2025, 1001, 2, 3, 1, "Top", 10, "Ada Ace", 102, "R", "R", "LAD", "SF", 1, 1, "hit_into_play", "field_out", 5, 88.0, 1800, -0.4, 0.6, None, 0.18, "R", "2025-04-04T12:00:00Z"),
    ("SI", "Sinker", "2025-04-02", 2025, 1002, 1, 1, 1, "Bot", 20, "Byte Ball", 201, "L", "L", "BOS", "NYY", 0, 0, "called_strike", None, 1, 94.0, 2200, 0.7, 0.7, None, None, "R", "2025-04-04T12:00:00Z"),
    ("SI", "Sinker", "2025-04-02", 2025, 1002, 1, 2, 1, "Bot", 20, "Byte Ball", 201, "L", "L", "BOS", "NYY", 0, 1, "swinging_strike", None, 14, 95.0, 2250, 0.8, 0.8, None, None, "R", "2025-04-04T12:00:00Z"),
    ("XX", "Mystery Pitch", "2025-04-02", 2025, 1002, 1, 3, 1, "Bot", 20, "Byte Ball", 201, "L", "L", "BOS", "NYY", 0, 2, "hit_into_play", "field_out", 8, 82.0, 1900, 0.1, 0.2, 90.0, 0.22, "R", "2025-04-04T12:00:00Z"),
    ("FF", "4-Seam Fastball", "2025-04-02", 2025, 2001, 1, 1, 1, "Top", 30, "Spring Arm", 301, "R", "R", "SEA", "SD", 0, 0, "called_strike", None, 5, 93.0, 2300, 0.0, 1.0, None, None, "S", "2025-04-04T12:00:00Z"),
    ("FF", "4-Seam Fastball", "2025-04-10", 2025, 2002, 1, 1, 1, "Top", 40, "Out Range", 401, "R", "R", "SEA", "SD", 0, 0, "called_strike", None, 5, 93.0, 2300, 0.0, 1.0, None, None, "R", "2025-04-11T12:00:00Z"),
]


def build_fixture(path: Path) -> None:
    if path.name not in {"ci.duckdb", "dbt_ci.duckdb"}:
        raise ValueError("Fixture output must be named ci.duckdb or dbt_ci.duckdb")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema bronze")
        connection.execute("create schema metadata")
        connection.execute("create schema gold")
        connection.execute(
            """
            create table bronze.raw_statcast (
                pitch_type varchar,
                pitch_name varchar,
                game_date varchar,
                game_year bigint,
                game_pk bigint,
                at_bat_number bigint,
                pitch_number bigint,
                inning bigint,
                inning_topbot varchar,
                pitcher bigint,
                player_name varchar,
                batter bigint,
                stand varchar,
                p_throws varchar,
                home_team varchar,
                away_team varchar,
                balls bigint,
                strikes bigint,
                description varchar,
                events varchar,
                zone bigint,
                release_speed double,
                release_spin_rate double,
                pfx_x double,
                pfx_z double,
                launch_speed double,
                estimated_woba_using_speedangle double,
                game_type varchar,
                loaded_at_utc varchar
            )
            """
        )
        placeholders = ", ".join("?" for _ in RAW_ROWS[0])
        connection.executemany(
            f"insert into bronze.raw_statcast ({RAW_COLUMNS}) values ({placeholders})",
            RAW_ROWS,
        )
        connection.execute(
            """
            create table metadata.pipeline_ranges (
                season bigint,
                start_date date,
                end_date date
            )
            """
        )
        connection.execute(
            "insert into metadata.pipeline_ranges values (2025, date '2025-04-01', date '2025-04-03')"
        )
        connection.execute(
            """
            create table gold.pitcher_pitch_type_summary as
            select * from (values
                (10, 'R', 'FF', 2, 1, 1, 1, 1, 0, 0),
                (10, 'R', 'SL', 1, 1, 0, 0, 0, 1, 1),
                (10, 'R', 'CH', 3, 2, 0, 2, 1, 1, 0),
                (20, 'L', 'SI', 2, 1, 1, 1, 1, 0, 0),
                (20, 'L', 'XX', 1, 1, 0, 0, 0, 1, 1)
            ) as expected(
                pitcher_id, batter_stand, pitch_type, pitch_count, swing_count,
                whiff_count, out_of_zone_pitch_count, chase_count,
                batted_ball_count, measured_batted_ball_count
            )
            """
        )
        connection.execute(
            """
            create table gold.count_strategy_summary as
            select * from (values
                (10, 'R', 'First Pitch', 'FF', 1, 0, 0, 0, 0),
                (10, 'R', 'Pitcher Ahead', 'FF', 1, 1, 1, 1, 1),
                (10, 'R', 'Two Strikes', 'SL', 1, 1, 0, 0, 0),
                (10, 'R', 'First Pitch', 'CH', 1, 0, 0, 1, 0),
                (10, 'R', 'Hitter Ahead', 'CH', 1, 1, 0, 1, 1),
                (10, 'R', 'Even', 'CH', 1, 1, 0, 0, 0),
                (20, 'L', 'First Pitch', 'SI', 1, 0, 0, 0, 0),
                (20, 'L', 'Pitcher Ahead', 'SI', 1, 1, 1, 1, 1),
                (20, 'L', 'Two Strikes', 'XX', 1, 1, 0, 0, 0)
            ) as expected(
                pitcher_id, batter_stand, count_state, pitch_type, pitch_count,
                swing_count, whiff_count, out_of_zone_pitch_count, chase_count
            )
            """
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="DuckDB file to replace with the fixture")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    build_fixture(arguments.path.resolve())
    print(f"Created dbt CI fixture: {arguments.path.resolve()}")
