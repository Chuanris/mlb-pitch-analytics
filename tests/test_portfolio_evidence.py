from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
AI_GUIDE = ROOT / "docs" / "AI_WORKFLOW.md"
SQL_GUIDE = ROOT / "docs" / "SQL_PERFORMANCE.md"
PORTFOLIO = ROOT / "docs" / "PORTFOLIO.md"
OPERATIONS = ROOT / "docs" / "OPERATIONS.md"
README = ROOT / "README.md"
PR_TEMPLATE = ROOT / ".github" / "pull_request_template.md"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class PortfolioEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai_guide = AI_GUIDE.read_text(encoding="utf-8")
        cls.sql_guide = SQL_GUIDE.read_text(encoding="utf-8")
        cls.portfolio = PORTFOLIO.read_text(encoding="utf-8")
        cls.operations = OPERATIONS.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")
        cls.pr_template = PR_TEMPLATE.read_text(encoding="utf-8")
        cls.ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.ci_contract = yaml.load(cls.ci_workflow, Loader=yaml.BaseLoader)

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

    def test_readme_and_portfolio_expose_sql_performance_evidence(self):
        self.assertIn("docs/SQL_PERFORMANCE.md", self.readme)
        self.assertIn("[DuckDB benchmark](SQL_PERFORMANCE.md)", self.portfolio)
        for boundary in (
            "not called a cold-cache result",
            "does not claim physical partition pruning",
            "cross-thread correctness checks",
        ):
            self.assertIn(boundary, self.sql_guide)

    def test_observability_demo_is_discoverable_without_overclaiming(self):
        command = ".\\.venv\\Scripts\\python.exe -m src.observability_demo"
        for document in (self.readme, self.portfolio, self.operations):
            self.assertIn(command, document)
        self.assertIn("does not prove upstream source completeness", self.portfolio)

    def test_ci_publishes_observability_contract_evidence(self):
        steps = self.ci_contract["jobs"]["python-and-pipeline-contracts"]["steps"]
        by_name = {step["name"]: step for step in steps}
        generate = by_name["Generate observability contract evidence"]
        upload = by_name["Upload observability contract evidence"]

        self.assertIn(
            "python -m src.observability_demo > outputs/ci/observability-demo.json",
            generate["run"],
        )
        self.assertIn("python -m json.tool", generate["run"])
        self.assertEqual(upload["uses"], "actions/upload-artifact@v6")
        self.assertEqual(upload["with"]["name"], "observability-contract-evidence")
        self.assertEqual(upload["with"]["path"], "outputs/ci/observability-demo.json")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertEqual(upload["with"]["retention-days"], "30")

        names = [step["name"] for step in steps]
        self.assertLess(
            names.index("Validate the full pipeline plan"),
            names.index("Generate observability contract evidence"),
        )


if __name__ == "__main__":
    unittest.main()
