from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from src.common import (
    configured_partition_paths,
    date_chunks,
    los_angeles_date,
    resolved_mode_ranges,
)


class CommonTests(unittest.TestCase):
    def test_date_chunks_cover_range_without_overlap(self):
        chunks = list(date_chunks(date(2025, 4, 1), date(2025, 4, 8), 3))
        self.assertEqual(
            chunks,
            [
                (date(2025, 4, 1), date(2025, 4, 3)),
                (date(2025, 4, 4), date(2025, 4, 6)),
                (date(2025, 4, 7), date(2025, 4, 8)),
            ],
        )

    def test_date_chunks_reject_invalid_parameters(self):
        with self.assertRaises(ValueError):
            list(date_chunks(date(2025, 4, 1), date(2025, 4, 2), 0))
        with self.assertRaises(ValueError):
            list(date_chunks(date(2025, 4, 2), date(2025, 4, 1), 1))

    def test_configured_partition_paths_are_mode_specific(self):
        config = {
            "sample": {
                "start_date": "2025-04-01",
                "end_date": "2025-04-03",
                "chunk_days": 3,
            },
            "paths": {"raw_dir": "data/raw"},
        }
        paths = configured_partition_paths(config, "sample")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, "statcast_2025-04-01_2025-04-03.parquet")

    def test_full_mode_resolves_latest_complete_day_for_active_season(self):
        config = {
            "full": {
                "ranges": [
                    {
                        "season": 2025,
                        "start_date": "2025-03-18",
                        "end_date": "2025-09-28",
                        "chunk_days": 7,
                    },
                    {
                        "season": 2026,
                        "start_date": "2026-03-25",
                        "end_date": "2026-09-27",
                        "chunk_days": 7,
                        "latest_complete_day": True,
                    },
                ]
            },
            "paths": {"raw_dir": "data/raw"},
        }
        ranges = resolved_mode_ranges(config, "full", today=date(2026, 8, 31))
        self.assertEqual(ranges[-1]["end_date"], date(2026, 8, 30))
        paths = configured_partition_paths(config, "full", today=date(2026, 8, 31))
        self.assertEqual(paths[-1].name, "statcast_2026-08-24_2026-08-30.parquet")
        self.assertIn("statcast_2026-08-17_2026-08-23.parquet", {path.name for path in paths})

    def test_los_angeles_date_uses_pacific_boundary_for_aware_and_naive_utc(self):
        utc_boundary = datetime(2025, 4, 4, 2, 0, tzinfo=timezone.utc)

        self.assertEqual(los_angeles_date(utc_boundary), date(2025, 4, 3))
        self.assertEqual(
            los_angeles_date(utc_boundary.replace(tzinfo=None)),
            date(2025, 4, 3),
        )

    def test_los_angeles_date_observes_standard_and_daylight_offsets(self):
        cases = (
            (datetime(2025, 1, 2, 7, 30, tzinfo=timezone.utc), date(2025, 1, 1)),
            (datetime(2025, 7, 2, 6, 30, tzinfo=timezone.utc), date(2025, 7, 1)),
        )

        for instant, expected in cases:
            with self.subTest(instant=instant):
                self.assertEqual(los_angeles_date(instant), expected)

    def test_dynamic_range_default_uses_los_angeles_calendar_date(self):
        config = {
            "full": {
                "ranges": [{
                    "season": 2025,
                    "start_date": "2025-04-01",
                    "end_date": "2025-04-10",
                    "chunk_days": 7,
                    "latest_complete_day": True,
                }]
            }
        }

        with patch("src.common.los_angeles_date", return_value=date(2025, 4, 3)):
            ranges = resolved_mode_ranges(config, "full")

        self.assertEqual(ranges[0]["end_date"], date(2025, 4, 2))


if __name__ == "__main__":
    unittest.main()
