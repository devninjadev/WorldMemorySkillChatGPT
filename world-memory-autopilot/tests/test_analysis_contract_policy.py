import unittest
from pathlib import Path


CONTRACT = Path(__file__).parents[1] / "references" / "analysis-contract.md"


class AnalysisContractPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CONTRACT.read_text(encoding="utf-8")

    def test_hourly_is_a_new_information_briefing(self):
        self.assertIn("hourly delta briefing", self.text)
        self.assertIn("unchanged cross-asset", self.text)
        self.assertIn("optional `교차자산 반응`", self.text)

    def test_geography_and_domain_editorial_priorities_are_explicit(self):
        self.assertIn("US or KR", self.text)
        self.assertIn("China, Japan, Europe, or the Middle East", self.text)
        self.assertIn("economics, finance, industry, technology, diplomacy, or politics", self.text)
        self.assertIn("culture, lifestyle, or entertainment", self.text)

    def test_verification_queue_reserves_tier_one_company_coverage(self):
        self.assertIn("verification queue", self.text)
        self.assertIn("company or industry candidate", self.text)
        self.assertIn("US/KR-impact candidate", self.text)

    def test_six_hour_report_keeps_qualified_company_developments(self):
        self.assertIn("six-hour integration is the cumulative synthesis", self.text)
        self.assertIn("Do not drop a verified Tier-1 company or industry development", self.text)
        self.assertIn("does not automatically earn hourly or six-hour placement", self.text)


if __name__ == "__main__":
    unittest.main()
