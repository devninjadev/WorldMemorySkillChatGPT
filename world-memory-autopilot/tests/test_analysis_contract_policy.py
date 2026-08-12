import unittest
from pathlib import Path


CONTRACT = Path(__file__).parents[1] / "references" / "analysis-contract.md"
MARKET_CONTRACT = Path(__file__).parents[1] / "references" / "market-data-contract.md"


class AnalysisContractPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CONTRACT.read_text(encoding="utf-8")

    def test_scheduled_hourly_is_a_cumulative_full_report(self):
        self.assertIn("Hourly cumulative full report", self.text)
        self.assertIn("latest committed integration cutoff", self.text)
        self.assertIn("same complete Report-v2 fields", self.text)
        self.assertIn("complete cross-asset snapshot", self.text)

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
        self.assertIn("six-hour integration uses the same cumulative synthesis", self.text)
        self.assertIn("Do not drop a verified Tier-1 company or industry development", self.text)
        self.assertIn("does not automatically earn hourly or six-hour placement", self.text)

    def test_us_equity_live_proxies_and_close_based_breadth_are_separate(self):
        self.assertIn("QQQUSDT", self.text)
        self.assertIn("SPYUSDT", self.text)
        self.assertIn("RSP/SPY", self.text)
        self.assertIn("regular-session close-based breadth", self.text)


class MarketDataDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = MARKET_CONTRACT.read_text(encoding="utf-8")

    def test_breadth_fallback_order_and_pair_integrity_are_explicit(self):
        self.assertIn("Nasdaq → S&P Dow Jones Indices → Yahoo Finance → cache", self.text)
        self.assertIn("never combine the two legs across providers or value bases", self.text)
        self.assertIn("1-, 5-, and 20-session", self.text)

    def test_binance_us_equity_proxies_are_primary_live_inputs(self):
        self.assertIn("`QQQUSDT`, USDⓈ-M perpetual", self.text)
        self.assertIn("`SPYUSDT`, USDⓈ-M perpetual", self.text)
        self.assertIn("rolling 24-hour", self.text)

    def test_treasury_curve_uses_official_csv_then_xml(self):
        self.assertIn("U.S. Treasury yield curve", self.text)
        self.assertIn("official annual CSV → official `yield.xml`", self.text)
        self.assertIn("2s10s", self.text)
        self.assertIn("1- and 5-session", self.text)


if __name__ == "__main__":
    unittest.main()
