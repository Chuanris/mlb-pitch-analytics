from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AI_GUIDE = ROOT / "docs" / "AI_WORKFLOW.md"
PORTFOLIO = ROOT / "docs" / "PORTFOLIO.md"
README = ROOT / "README.md"
PR_TEMPLATE = ROOT / ".github" / "pull_request_template.md"


class PortfolioEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai_guide = AI_GUIDE.read_text(encoding="utf-8")
        cls.portfolio = PORTFOLIO.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")
        cls.pr_template = PR_TEMPLATE.read_text(encoding="utf-8")

    def test_ai_case_study_links_failed_diagnostic_and_green_runs(self):
        for run_id in ("34539763740", "34540591806", "34540760348"):
            self.assertIn(
                f"https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/{run_id}",
                self.ai_guide,
            )
        for commit in ("a75a99d", "56fcafb", "198bbfc"):
            self.assertIn(
                f"https://github.com/Chuanris/mlb-pitch-analytics/commit/{commit}",
                self.ai_guide,
            )

    def test_ai_case_study_keeps_claim_boundaries_explicit(self):
        for boundary in (
            "does not prove a data refresh",
            "do not prove a live GCP deployment",
            "not a continuously running scheduler",
            "does not claim a percentage productivity gain or hours saved",
        ):
            self.assertIn(boundary, self.ai_guide)

    def test_pr_template_requires_human_review_and_evidence(self):
        for field in (
            "Human review performed",
            "Suggestions corrected or rejected",
            "Evidence used to verify the result",
            "No secrets, credentials, generated databases or personal practice files",
            "Cloud and production claims match the linked evidence",
        ):
            self.assertIn(field, self.pr_template)

    def test_readme_and_portfolio_expose_ai_evidence(self):
        self.assertIn("docs/AI_WORKFLOW.md", self.readme)
        self.assertIn("[AI workflow](AI_WORKFLOW.md)", self.portfolio)
        self.assertNotIn("Process evidence pending a published PR", self.portfolio)


if __name__ == "__main__":
    unittest.main()
