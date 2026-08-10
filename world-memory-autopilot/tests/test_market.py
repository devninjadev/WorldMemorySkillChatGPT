from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Event
import tempfile
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import world_memory.market as market
from world_memory.bootstrap import DependencyBootstrapError


def _fred_csv(series_id: str, values: list[float]) -> str:
    rows = [f"observation_date,{series_id}"]
    for index, value in enumerate(values):
        rows.append(f"2026-01-{index + 1:02d},{value}")
    return "\n".join(rows) + "\n"


def _fred_batch_zip() -> bytes:
    weekly_friday = ["observation_date,NFCIRISK"]
    weekly_wednesday = ["observation_date,WALCL,WDTGAL"]
    daily = ["observation_date,RRPONTSYD,DTWEXBGS"]
    for index in range(14):
        day = f"2026-01-{index + 1:02d}"
        weekly_friday.append(f"{day},{float(index)}")
        weekly_wednesday.append(f"{day},{7000.0 + index},1000.0")
        daily.append(f"{day},1.0,{100.0 + index}")
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("weekly,_ending_friday.csv", "\n".join(weekly_friday) + "\n")
        archive.writestr("weekly,_as_of_wednesday.csv", "\n".join(weekly_wednesday) + "\n")
        archive.writestr("daily.csv", "\n".join(daily) + "\n")
    return payload.getvalue()


def _credit_histories() -> dict[str, dict[str, float]]:
    days = ["2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14"]
    return {
        "HYG": {day: 80.0 + index for index, day in enumerate(days)},
        "LQD": {day: 100.0 + index for index, day in enumerate(days)},
    }


def _yahoo_chart(closes: list[float]) -> str:
    timestamps = [
        int(datetime.fromisoformat(f"2026-01-{day:02d}T12:00:00+00:00").timestamp())
        for day in (7, 8, 9, 12, 13, 14)
    ]
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {"quote": [{"close": closes}]},
                    }
                ],
                "error": None,
            }
        }
    )


class MarketCollectionTests(unittest.TestCase):
    def test_yfinance_history_surfaces_rate_limit_instead_of_returning_empty_data(self) -> None:
        class YFRateLimitError(RuntimeError):
            pass

        class RateLimitedTicker:
            def history(self, **_: object) -> object:
                raise YFRateLimitError("Too Many Requests")

        fake_yfinance = SimpleNamespace(Ticker=lambda _: RateLimitedTicker())
        with patch("world_memory.bootstrap.ensure_runtime_dependencies", return_value={}), patch.dict(
            sys.modules, {"yfinance": fake_yfinance}
        ):
            with self.assertRaises(YFRateLimitError):
                market._yfinance_history(1.0)

    def test_dependency_bootstrap_failure_uses_direct_yahoo_history_urls(self) -> None:
        def unavailable_bootstrap(_: float) -> dict:
            raise DependencyBootstrapError("dependency_install_failed", "pip unavailable")

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if parsed.netloc != "query1.finance.yahoo.com":
                raise OSError("fixture intentionally withholds non-Yahoo sources")
            symbol = parsed.path.rsplit("/", 1)[-1]
            return _yahoo_chart(
                [80.0, 81.0, 82.0, 83.0, 84.0, 85.0]
                if symbol == "HYG"
                else [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
            )

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
            finance_history=unavailable_bootstrap,
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result["creditRatio"]["status"], "ok")
        self.assertEqual(result["creditRatio"]["cacheStatus"], "refreshed")

    def test_fresh_credit_cache_skips_hourly_yahoo_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "market-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "creditRatio": {
                            "savedAt": "2026-01-14T10:00:00Z",
                            "histories": _credit_histories(),
                        },
                    }
                ),
                encoding="utf-8",
            )

            def forbidden_finance_history(_: float) -> dict:
                raise AssertionError("fresh cache must suppress Yahoo acquisition")

            result = market.collect_market_data(
                "2026-01-14T12:00:00Z",
                fetch_text=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                finance_history=forbidden_finance_history,
                cache_path=cache_path,
                clock=lambda: datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(result["creditRatio"]["status"], "ok")
            self.assertEqual(result["creditRatio"]["cacheStatus"], "fresh-hit")
            self.assertFalse(
                any(gap["sourceId"] in {"HYG", "LQD"} for gap in result["dataQuality"]["gaps"])
            )

    def test_rate_limited_credit_provider_uses_valid_cache(self) -> None:
        class YFRateLimitError(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "market-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "creditRatio": {
                            "savedAt": "2026-01-14T05:00:00Z",
                            "histories": _credit_histories(),
                        },
                    }
                ),
                encoding="utf-8",
            )

            def rate_limited(_: float) -> dict:
                raise YFRateLimitError("Too Many Requests")

            result = market.collect_market_data(
                "2026-01-14T12:00:00Z",
                fetch_text=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                finance_history=rate_limited,
                cache_path=cache_path,
                clock=lambda: datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(result["creditRatio"]["status"], "ok")
            self.assertEqual(result["creditRatio"]["cacheStatus"], "stale-fallback")
            degradation = next(
                gap for gap in result["dataQuality"]["gaps"] if gap["sourceId"] == "YAHOO_HYG_LQD"
            )
            self.assertTrue(degradation["rateLimited"])

    def test_successful_credit_provider_refreshes_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "market-cache.json"
            histories = {
                symbol: {datetime.fromisoformat(day).date(): value for day, value in values.items()}
                for symbol, values in _credit_histories().items()
            }
            result = market.collect_market_data(
                "2026-01-14T12:00:00Z",
                fetch_text=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                finance_history=lambda _: histories,
                cache_path=cache_path,
                clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(result["creditRatio"]["status"], "ok")
            self.assertEqual(result["creditRatio"]["cacheStatus"], "refreshed")
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["creditRatio"]["savedAt"], "2026-01-14T12:00:01Z")

    def test_fred_batch_and_live_tickers_share_one_parallel_pass(self) -> None:
        fred_started = Event()
        btc_started = Event()
        close_time = int(datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)

        def fetch_bytes(_: str, __: float) -> bytes:
            fred_started.set()
            if not btc_started.wait(0.25):
                raise OSError("BTC request did not overlap FRED request")
            return _fred_batch_zip()

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if "binance" not in parsed.netloc:
                raise OSError("fixture intentionally withholds Yahoo")
            symbol = parse_qs(parsed.query)["symbol"][0]
            if symbol == "BTCUSDT":
                btc_started.set()
                if not fred_started.wait(0.25):
                    raise OSError("FRED request did not overlap BTC request")
            return json.dumps(
                {
                    "symbol": symbol,
                    "lastPrice": "100.0",
                    "priceChangePercent": "1.5",
                    "quoteVolume": "1000000.0",
                    "count": 100,
                    "closeTime": close_time,
                }
            )

        fixed_now = datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc)
        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=fetch_bytes,
            clock=lambda: fixed_now,
        )

        self.assertEqual(result["fred"]["WALCL"]["status"], "ok")
        self.assertEqual(result["binance"]["BTCUSDT"]["status"], "ok")

    def test_independent_live_tickers_are_requested_concurrently(self) -> None:
        cl_started = Event()
        xau_started = Event()
        close_time = int(datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if "binance" not in parsed.netloc:
                raise OSError("fixture intentionally withholds non-Binance sources")
            symbol = parse_qs(parsed.query)["symbol"][0]
            if symbol == "CLUSDT":
                cl_started.set()
                if not xau_started.wait(0.25):
                    raise OSError("XAU request did not overlap CL request")
            elif symbol == "XAUUSDT":
                xau_started.set()
                if not cl_started.wait(0.25):
                    raise OSError("CL request did not overlap XAU request")
            return json.dumps(
                {
                    "symbol": symbol,
                    "lastPrice": "100.0",
                    "priceChangePercent": "1.5",
                    "quoteVolume": "1000000.0",
                    "count": 100,
                    "closeTime": close_time,
                }
            )

        fixed_now = datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc)
        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            clock=lambda: fixed_now,
        )

        self.assertEqual(result["binance"]["CLUSDT"]["status"], "ok")
        self.assertEqual(result["binance"]["XAUUSDT"]["status"], "ok")

    def test_fred_series_are_collected_from_one_official_batch(self) -> None:
        fred_urls: list[str] = []

        def fetch_bytes(url: str, _: float) -> bytes:
            fred_urls.append(url)
            return _fred_batch_zip()

        def fetch_text(_: str, __: float) -> str:
            raise OSError("fixture intentionally withholds non-FRED sources")

        fixed_now = datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc)
        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            timeout=7.0,
            fetch_text=fetch_text,
            fetch_bytes=fetch_bytes,
            clock=lambda: fixed_now,
        )

        self.assertEqual(len(fred_urls), 1)
        self.assertIn("NFCIRISK%2CWALCL%2CWDTGAL%2CRRPONTSYD%2CDTWEXBGS", fred_urls[0])
        self.assertTrue(all(item["status"] == "ok" for item in result["fred"].values()))
        self.assertEqual(result["netLiquidity"]["status"], "ok")

    def test_live_ticker_allows_only_bounded_exchange_clock_skew(self) -> None:
        received_at = datetime(2026, 1, 14, 12, 0, 5, tzinfo=timezone.utc)

        def payload(close_second: int) -> str:
            return json.dumps(
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "100.0",
                    "priceChangePercent": "1.5",
                    "quoteVolume": "1000000.0",
                    "count": 100,
                    "closeTime": int(
                        datetime(
                            2026, 1, 14, 12, 0, close_second, tzinfo=timezone.utc
                        ).timestamp()
                        * 1000
                    ),
                }
            )

        accepted = market._parse_binance_ticker(payload(6), "BTCUSDT", received_at)
        self.assertEqual(accepted["observationAt"], "2026-01-14T12:00:06Z")
        with self.assertRaisesRegex(ValueError, "future"):
            market._parse_binance_ticker(payload(8), "BTCUSDT", received_at)

    def test_live_ticker_uses_response_time_instead_of_collection_cutoff(self) -> None:
        close_time = int(datetime(2026, 1, 14, 12, 0, 4, tzinfo=timezone.utc).timestamp() * 1000)

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if "binance" not in parsed.netloc:
                raise OSError("fixture intentionally withholds non-Binance sources")
            symbol = parse_qs(parsed.query)["symbol"][0]
            return json.dumps(
                {
                    "symbol": symbol,
                    "lastPrice": "100.0",
                    "priceChangePercent": "1.5",
                    "quoteVolume": "1000000.0",
                    "count": 100,
                    "closeTime": close_time,
                }
            )

        received_at = datetime(2026, 1, 14, 12, 0, 5, tzinfo=timezone.utc)
        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            clock=lambda: received_at,
        )

        self.assertEqual(result["binance"]["BTCUSDT"]["status"], "ok")
        self.assertEqual(result["binance"]["BTCUSDT"]["fetchedAt"], "2026-01-14T12:00:05Z")

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
