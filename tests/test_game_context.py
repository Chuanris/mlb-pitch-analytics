from __future__ import annotations

import unittest

from src.extract_game_context import deduplicate_schedule_games, parse_wind


class GameContextTests(unittest.TestCase):
    def test_parse_wind_extracts_speed_and_field_relative_direction(self):
        speed, direction = parse_wind("10 mph, Out To RF")
        self.assertEqual(speed, 10.0)
        self.assertEqual(direction, "Out To RF")

    def test_rescheduled_game_prefers_final_record(self):
        postponed = {
            "gamePk": 778443,
            "gameDate": "2025-04-05T20:10:00Z",
            "status": {"abstractGameState": "Preview", "detailedState": "Postponed"},
        }
        final = {
            "gamePk": 778443,
            "gameDate": "2025-04-06T17:35:00Z",
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
        }
        selected = deduplicate_schedule_games([postponed, final])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["gameDate"], final["gameDate"])


if __name__ == "__main__":
    unittest.main()
