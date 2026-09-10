from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.build_matchup_stream_planner import schedule_url, stream_score, stream_tier


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANNER_PATH = PROJECT_ROOT / "outputs" / "fantasy" / "matchup_stream_planner.csv"
MANIFEST_PATH = PROJECT_ROOT / "outputs" / "fantasy" / "matchup_stream_planner_manifest.json"
ARTIFACTS_AVAILABLE = PLANNER_PATH.exists() and MANIFEST_PATH.exists()
requires_artifacts = unittest.skipUnless(
    ARTIFACTS_AVAILABLE,
    "Generated matchup planner artifacts are not available in this checkout",
)


class MatchupStreamPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARTIFACTS_AVAILABLE:
            cls.frame = pd.read_csv(PLANNER_PATH)
            cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_schedule_url_uses_regular_season_and_probable_pitcher_hydration(self):
        url = schedule_url(pd.Timestamp("2026-09-01").date(), pd.Timestamp("2026-09-07").date())
        self.assertIn("gameType=R", url)
        self.assertIn("probablePitcher", url)
        self.assertIn("startDate=2026-09-01", url)

    def test_stream_score_uses_documented_weights(self):
        score, coverage = stream_score(80, 60, 40)
        self.assertEqual(score, 71.0)
        self.assertEqual(coverage, 1.0)
        missing, missing_coverage = stream_score(None, 60, 40)
        self.assertIsNone(missing)
        self.assertEqual(missing_coverage, 0.0)

    def test_stream_tier_never_scores_tbd_as_confirmed(self):
        self.assertEqual(stream_tier(90, "TBD"), "Awaiting probable starter")
        self.assertEqual(stream_tier(None, "Confirmed probable"), "Insufficient recent sample")
        self.assertEqual(stream_tier(82, "Confirmed probable"), "Priority stream research")

    @requires_artifacts
    def test_artifact_keys_and_profiles_are_complete(self):
        self.assertFalse(self.frame.empty)
        self.assertFalse(
            self.frame.duplicated(["game_pk", "pitcher_team", "profile_key"]).any()
        )
        self.assertEqual(
            set(self.frame["profile_key"]),
            {"roto_balance", "strikeout_upside", "ratio_protection"},
        )
        self.assertEqual(len(self.frame), self.manifest["rows"])

    @requires_artifacts
    def test_scored_rows_are_bounded_and_tbd_rows_are_unscored(self):
        scored = self.frame[self.frame["stream_score"].notna()]
        self.assertTrue(scored["stream_score"].between(0, 100).all())
        self.assertTrue(scored["fantasy_signal"].between(0, 100).all())
        self.assertTrue(scored["opponent_matchup_signal"].between(0, 100).all())
        self.assertTrue(scored["park_contact_suppression_signal"].between(0, 100).all())
        self.assertTrue(self.frame["stream_score_coverage"].between(0, 1).all())
        self.assertTrue(self.frame.loc[self.frame["probable_status"] == "TBD", "stream_score"].isna().all())

    @requires_artifacts
    def test_rate_and_weather_fields_are_valid_when_present(self):
        for field in (
            "opponent_strikeout_rate",
            "opponent_walk_rate",
            "opponent_hard_hit_rate",
            "park_hard_hit_rate",
            "park_home_run_rate",
        ):
            self.assertTrue(self.frame[field].dropna().between(0, 1).all())
        self.assertTrue(
            self.frame["precipitation_probability"].dropna().between(0, 100).all()
        )


if __name__ == "__main__":
    unittest.main()
