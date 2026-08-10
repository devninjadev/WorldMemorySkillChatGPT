from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
import unittest

import world_memory.market as market


def _fred_csv(series_id: str, values: list[float]) -> str:
    rows = [f"observation_date,{series_id}"]
    for index, value in enumerate(values):
        rows.append(f"2026-01-{index + 1:02d},{value}")
    return "\n".join(rows) + "\n"


class MarketCollectionTests(unittest.TestCase):
    def test_public_fred_collection_computes_nfci_and_net_liquidity(self):
        collector = getattr(market, "collect_market_data", None)
        self.assertTrue(
            callable(collector),
            "public-source plan must have a deterministic collection implementation",
        )

        fred_payloads = {
            "NFCIRISK": _fred_csv("NFCIRISK", [float(value) for value in range(14)]),
            "WALCL": _fred_csv("WALCL", [7000.0 + value for value in range(14)]),
            "WDTGAL": _fred_csv("WDTGAL", [1000.0] * 14),
            "RRPONTSYD": _fred_csv("RRPONTSYD", [1.0] * 14),
            "DTWEXBGS": _fred_csv("DTWEXBGS", [100.0 + value for value in range(14)]),
        }

        def fetch_text(url: str, timeout: float) -> str:
            self.assertEqual(timeout, 7.0)
            parsed = urlparse(url)
            if parsed.netloc == "fred.stlouisfed.org":
                return fred_payloads[parse_qs(parsed.query)["id"][0]]
            raise OSError("fixture intentionally withholds non-FRED sources")

        fixed_now = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)
        result = collector(
            "2026-01-14T12:00:00Z",
            timeout=7.0,
            fetch_text=fetch_text,
            clock=lambda: fixed_now,
        )

        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["collectionStartedAt"], "2026-01-14T12:00:00Z")
        self.assertEqual(result["collectionEndedAt"], "2026-01-14T12:00:00Z")

        nfci = result["fred"]["NFCIRISK"]
        self.assertEqual(nfci["status"], "ok")
        self.assertEqual(nfci["observationDate"], "2026-01-14")
        self.assertEqual(nfci["level"], 13.0)
        self.assertEqual(
            nfci["changes"],
            {"1-observation": 1.0, "4-observation": 4.0, "13-observation": 13.0},
        )

        liquidity = result["netLiquidity"]
        self.assertEqual(liquidity["status"], "ok")
        self.assertEqual(liquidity["anchorDate"], "2026-01-14")
        self.assertEqual(liquidity["level"], 5013.0)
        self.assertEqual(
            liquidity["componentObservationDates"],
            {"WALCL": "2026-01-14", "WDTGAL": "2026-01-14", "RRPONTSYD": "2026-01-14"},
        )
        self.assertEqual(
            liquidity["changes"],
            {"1-anchor": 1.0, "4-anchor": 4.0, "13-anchor": 13.0},
        )
        self.assertEqual(
            liquidity["formula"],
            "WALCL - WDTGAL - (RRPONTSYD * 1000)",
        )

        self.assertEqual(result["fred"]["WALCL"]["status"], "ok")
        self.assertEqual(result["fred"]["WDTGAL"]["status"], "ok")
        self.assertEqual(result["fred"]["RRPONTSYD"]["status"], "ok")
        self.assertEqual(result["creditRatio"]["status"], "failed")
        self.assertEqual(
            [gap["sourceId"] for gap in result["dataQuality"]["gaps"]],
            ["HYG", "LQD", "CLUSDT", "XAUUSDT", "BTCUSDT"],
        )

    def test_missing_liquidity_component_does_not_erase_nfci(self):
        collector = getattr(market, "collect_market_data", None)
        self.assertTrue(callable(collector))

        payloads = {
            "NFCIRISK": _fred_csv("NFCIRISK", [-0.3, -0.2]),
            "WALCL": _fred_csv("WALCL", [7000.0, 7010.0]),
            "WDTGAL": _fred_csv("WDTGAL", [1000.0, 1010.0]),
            "DTWEXBGS": _fred_csv("DTWEXBGS", [100.0, 101.0]),
        }

        def fetch_text(url: str, timeout: float) -> str:
            parsed = urlparse(url)
            if parsed.netloc == "fred.stlouisfed.org":
                series_id = parse_qs(parsed.query)["id"][0]
                if series_id == "RRPONTSYD":
                    raise OSError("RRP unavailable")
                return payloads[series_id]
            raise OSError("unavailable")

        fixed_now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        result = collector(
            "2026-01-02T12:00:00Z",
            fetch_text=fetch_text,
            clock=lambda: fixed_now,
        )

        self.assertEqual(result["fred"]["NFCIRISK"]["status"], "ok")
        self.assertEqual(result["fred"]["NFCIRISK"]["level"], -0.2)
        self.assertEqual(result["fred"]["RRPONTSYD"]["status"], "failed")
        self.assertEqual(result["netLiquidity"]["status"], "failed")
        self.assertIn("RRPONTSYD", result["netLiquidity"]["missingComponents"])


if __name__ == "__main__":
    unittest.main()
