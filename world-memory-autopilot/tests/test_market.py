from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _nasdaq_history(symbol: str, closes: list[float]) -> str:
    days = ("01/07/2026", "01/08/2026", "01/09/2026", "01/12/2026", "01/13/2026", "01/14/2026")
    return json.dumps(
        {
            "data": {
                "symbol": symbol,
                "totalRecords": len(days),
                "tradesTable": {
                    "headers": {"date": "Date", "close": "Close/Last"},
                    "rows": [
                        {
                            "date": day,
                            "close": f"${close:.2f}",
                            "volume": "1,000,000",
                            "open": f"${close - 0.1:.2f}",
                            "high": f"${close + 0.1:.2f}",
                            "low": f"${close - 0.2:.2f}",
                        }
                        for day, close in zip(days, closes)
                    ],
                },
            },
            "message": None,
            "status": {"rCode": 200},
        }
    )


def _long_nasdaq_history(symbol: str, closes: list[float]) -> str:
    days = []
    current = datetime(2025, 12, 15, tzinfo=timezone.utc)
    while len(days) < len(closes):
        if current.weekday() < 5:
            days.append(current.strftime("%m/%d/%Y"))
        current += timedelta(days=1)
    return json.dumps(
        {
            "data": {
                "symbol": symbol,
                "totalRecords": len(days),
                "tradesTable": {
                    "headers": {"date": "Date", "close": "Close/Last"},
                    "rows": [
                        {"date": day, "close": f"${close:.4f}"}
                        for day, close in zip(days, closes)
                    ],
                },
            },
            "message": None,
            "status": {"rCode": 200},
        }
    )


def _ishares_history(values: list[float]) -> bytes:
    days = ("Jan 07, 2026", "Jan 08, 2026", "Jan 09, 2026", "Jan 12, 2026", "Jan 13, 2026", "Jan 14, 2026")
    rows = "".join(
        "<ss:Row>"
        f'<ss:Cell><ss:Data ss:Type="String">{day}</ss:Data></ss:Cell>'
        f'<ss:Cell><ss:Data ss:Type="Number">{value}</ss:Data></ss:Cell>'
        '<ss:Cell><ss:Data ss:Type="Number">0</ss:Data></ss:Cell>'
        '<ss:Cell><ss:Data ss:Type="Number">1000000</ss:Data></ss:Cell>'
        "</ss:Row>"
        for day, value in zip(days, values)
    )
    return (
        '<?xml version="1.0"?>'
        '<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<ss:Worksheet ss:Name="Historical"><ss:Table>'
        '<ss:Row><ss:Cell><ss:Data ss:Type="String">As Of</ss:Data></ss:Cell>'
        '<ss:Cell><ss:Data ss:Type="String">NAV per Share</ss:Data></ss:Cell>'
        '<ss:Cell><ss:Data ss:Type="String">Ex-Dividends</ss:Data></ss:Cell>'
        '<ss:Cell><ss:Data ss:Type="String">Shares Outstanding</ss:Data></ss:Cell></ss:Row>'
        f"{rows}</ss:Table></ss:Worksheet></ss:Workbook>"
    ).encode("utf-8")


class MarketCollectionTests(unittest.TestCase):
    def test_sp_global_workbook_parser_extracts_price_return_history(self) -> None:
        import pandas as pd

        rows = [["metadata", None]]
        rows.append(["Date", "Index Level"])
        rows.extend(
            [[f"2025-12-{day:02d}", 1000.0 + day] for day in range(1, 22)]
        )
        frame = pd.DataFrame(rows)
        with patch(
            "world_memory.bootstrap.ensure_runtime_dependencies", return_value={}
        ), patch("pandas.read_excel", return_value=frame):
            history = market._parse_sp_global_history(
                b"legacy-xls",
                datetime(2026, 1, 14, tzinfo=timezone.utc),
                "RSP",
            )

        self.assertEqual(len(history), 21)
        self.assertEqual(history[datetime(2025, 12, 21).date()], 1021.0)

    def test_yfinance_is_third_breadth_tier_and_uses_complete_pair(self) -> None:
        days = []
        current = datetime(2025, 12, 1, tzinfo=timezone.utc)
        while len(days) < 21:
            if current.weekday() < 5:
                days.append(current.date())
            current += timedelta(days=1)
        histories = {
            "RSP": {day: 100.0 + index for index, day in enumerate(days)},
            "SPY": {day: 200.0 + index for index, day in enumerate(days)},
        }

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
            fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
            breadth_finance_history=lambda _: histories,
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        breadth = result["equityBreadth"]
        self.assertEqual(breadth["status"], "ok")
        self.assertEqual(breadth["provider"], "Yahoo Finance via yfinance")
        self.assertEqual(
            [attempt["sourceId"] for attempt in breadth["attempts"]],
            ["NASDAQ_RSP_SPY", "SP_GLOBAL_RSP_SPY", "YAHOO_RSP_SPY"],
        )

    def test_credit_and_breadth_cache_sections_preserve_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market-cache.json"
            credit = {
                symbol: {
                    datetime.fromisoformat(day).date(): value
                    for day, value in values.items()
                }
                for symbol, values in _credit_histories().items()
            }
            days = [datetime(2025, 12, day).date() for day in range(1, 22)]
            breadth = {
                "RSP": {day: 100.0 + index for index, day in enumerate(days)},
                "SPY": {day: 200.0 + index for index, day in enumerate(days)},
            }
            market._write_credit_cache(
                path,
                credit,
                "2026-01-14T12:00:00Z",
                provider="Nasdaq",
                value_basis="Close",
                source_urls={"HYG": "https://example/HYG", "LQD": "https://example/LQD"},
            )
            market._write_breadth_cache(
                path,
                breadth,
                "2026-01-14T12:00:01Z",
                provider="Nasdaq",
                value_basis="Close",
                source_urls={"RSP": "https://example/RSP", "SPY": "https://example/SPY"},
            )

            cached = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(cached), {"schemaVersion", "creditRatio", "equityBreadth"})
            self.assertEqual(cached["creditRatio"]["provider"], "Nasdaq")
            self.assertEqual(cached["equityBreadth"]["provider"], "Nasdaq")

    def test_nasdaq_rsp_spy_pair_computes_breadth_changes(self) -> None:
        close_time = int(datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            symbol = parse_qs(parsed.query).get("symbol", [None])[0]
            if parsed.netloc == "api.nasdaq.com":
                path_symbol = parsed.path.split("/")[3]
                if path_symbol in {"HYG", "LQD"}:
                    return _nasdaq_history(
                        path_symbol,
                        [80, 81, 82, 83, 84, 85]
                        if path_symbol == "HYG"
                        else [100, 101, 102, 103, 104, 105],
                    )
                values = [100 + index for index in range(21)]
                if path_symbol == "SPY":
                    values = [200 + index for index in range(21)]
                return _long_nasdaq_history(path_symbol, values)
            if "binance" in parsed.netloc:
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
            raise OSError("unexpected source")

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        breadth = result["equityBreadth"]
        self.assertEqual(breadth["status"], "ok")
        self.assertEqual(breadth["provider"], "Nasdaq")
        self.assertEqual(breadth["valueBasis"], "Close")
        self.assertEqual(breadth["observationDate"], "2026-01-12")
        self.assertEqual(set(breadth["changesPct"]), {"1-session", "5-session", "20-session"})
        self.assertEqual(breadth["direction5Sessions"], "expanding")

    def test_incomplete_nasdaq_breadth_pair_falls_back_to_complete_sp_global_pair(self) -> None:
        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if parsed.netloc == "api.nasdaq.com":
                symbol = parsed.path.split("/")[3]
                if symbol == "RSP":
                    return _long_nasdaq_history(symbol, [100 + index for index in range(21)])
                raise OSError(f"{symbol} unavailable")
            raise OSError("unavailable")

        sp_values = {
            "RSP": {f"2025-12-{day:02d}": 100.0 + day for day in range(1, 22)},
            "SPY": {f"2025-12-{day:02d}": 200.0 + day for day in range(1, 22)},
        }

        def fetch_bytes(url: str, _: float) -> bytes:
            if "fredgraph.csv" in url:
                return _fred_batch_zip()
            if "indexId=370" in url:
                return b"rsp-sp-global"
            if "indexId=340" in url:
                return b"spy-sp-global"
            raise OSError("unexpected bytes source")

        def parse_sp(payload: bytes, cutoff: datetime, symbol: str):
            expected = b"rsp-sp-global" if symbol == "RSP" else b"spy-sp-global"
            self.assertEqual(payload, expected)
            return {
                datetime.fromisoformat(day).date(): value
                for day, value in sp_values[symbol].items()
                if datetime.fromisoformat(day).date() <= cutoff.date()
            }

        with patch.object(market, "_parse_sp_global_history", side_effect=parse_sp):
            result = market.collect_market_data(
                "2026-01-14T12:00:00Z",
                fetch_text=fetch_text,
                fetch_bytes=fetch_bytes,
                clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
            )

        breadth = result["equityBreadth"]
        self.assertEqual(breadth["status"], "ok")
        self.assertEqual(breadth["provider"], "S&P Dow Jones Indices")
        self.assertEqual(breadth["valueBasis"], "Price Return Index")
        self.assertEqual(
            breadth["formula"],
            "S&P 500 Equal Weight Price Return Index / S&P 500 Price Return Index",
        )
    def test_nasdaq_close_is_used_before_ishares_yahoo_and_cache(self) -> None:
        requested: list[str] = []

        def fetch_text(url: str, _: float) -> str:
            requested.append(url)
            parsed = urlparse(url)
            if parsed.netloc == "api.nasdaq.com":
                symbol = parsed.path.split("/")[3]
                return _nasdaq_history(
                    symbol,
                    [80.0, 81.0, 82.0, 83.0, 84.0, 85.0]
                    if symbol == "HYG"
                    else [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
                )
            raise OSError("fixture intentionally withholds non-Nasdaq text sources")

        def forbidden_finance_history(_: float) -> dict:
            raise AssertionError("Yahoo must not run after a complete Nasdaq pair")

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("FRED unavailable")),
            finance_history=forbidden_finance_history,
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        ratio = result["creditRatio"]
        self.assertEqual(ratio["status"], "ok")
        self.assertEqual(ratio["provider"], "Nasdaq")
        self.assertEqual(ratio["valueBasis"], "Close")
        self.assertEqual(ratio["componentValues"], {"HYG": 85.0, "LQD": 105.0})
        credit_nasdaq = [
            url
            for url in requested
            if "api.nasdaq.com" in url and any(f"/{symbol}/" in url for symbol in ("HYG", "LQD"))
        ]
        self.assertEqual(len(credit_nasdaq), 2)
        self.assertFalse(
            any(
                "query1.finance.yahoo.com" in url
                and any(f"/{symbol}?" in url for symbol in ("HYG", "LQD"))
                for url in requested
            )
        )

    def test_ishares_nav_is_second_and_never_labeled_as_close(self) -> None:
        requested: list[str] = []

        def fetch_text(url: str, _: float) -> str:
            requested.append(url)
            raise OSError("Nasdaq and other text sources unavailable")

        def fetch_bytes(url: str, _: float) -> bytes:
            requested.append(url)
            if "portfolioId=239565" in url:
                return _ishares_history([79.0, 79.2, 79.4, 79.6, 79.8, 80.0])
            if "portfolioId=239566" in url:
                return _ishares_history([105.0, 105.2, 105.4, 105.6, 105.8, 106.0])
            raise OSError("FRED unavailable")

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=fetch_bytes,
            finance_history=lambda _: (_ for _ in ()).throw(
                AssertionError("Yahoo must not run after a complete iShares pair")
            ),
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        ratio = result["creditRatio"]
        self.assertEqual(ratio["status"], "ok")
        self.assertEqual(ratio["provider"], "iShares")
        self.assertEqual(ratio["valueBasis"], "NAV")
        self.assertEqual(ratio["formula"], "HYG NAV per Share / LQD NAV per Share")
        self.assertNotIn("componentCloses", ratio)
        self.assertFalse(
            any(
                "query1.finance.yahoo.com" in url
                and any(f"/{symbol}?" in url for symbol in ("HYG", "LQD"))
                for url in requested
            )
        )

    def test_incomplete_nasdaq_pair_falls_back_to_complete_ishares_pair(self) -> None:
        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if parsed.netloc == "api.nasdaq.com":
                symbol = parsed.path.split("/")[3]
                return _nasdaq_history(
                    symbol,
                    [80.0, 81.0, 82.0, 83.0, 84.0]
                    if symbol == "HYG"
                    else [100.0, 101.0, 102.0, 103.0, 104.0],
                )
            raise OSError("non-Nasdaq text source unavailable")

        def fetch_bytes(url: str, _: float) -> bytes:
            if "portfolioId=239565" in url:
                return _ishares_history([79.0, 79.2, 79.4, 79.6, 79.8, 80.0])
            if "portfolioId=239566" in url:
                return _ishares_history([105.0, 105.2, 105.4, 105.6, 105.8, 106.0])
            raise OSError("FRED unavailable")

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=fetch_bytes,
            finance_history=lambda _: (_ for _ in ()).throw(
                AssertionError("Yahoo must not run after complete iShares fallback")
            ),
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result["creditRatio"]["status"], "ok")
        self.assertEqual(result["creditRatio"]["provider"], "iShares")
        self.assertEqual(result["creditRatio"]["valueBasis"], "NAV")

    def test_yahoo_runs_only_after_nasdaq_and_ishares_fail(self) -> None:
        sequence: list[str] = []

        def fetch_text(url: str, _: float) -> str:
            parsed = urlparse(url)
            if parsed.netloc == "api.nasdaq.com":
                symbol = parsed.path.split("/")[3]
                if symbol in {"HYG", "LQD"}:
                    sequence.append("nasdaq")
            raise OSError("text source unavailable")

        def fetch_bytes(url: str, _: float) -> bytes:
            if "blackrock.com" in url:
                sequence.append("ishares")
            raise OSError("bytes source unavailable")

        def finance_history(_: float) -> dict:
            sequence.append("yahoo")
            return _credit_histories()

        result = market.collect_market_data(
            "2026-01-14T12:00:00Z",
            fetch_text=fetch_text,
            fetch_bytes=fetch_bytes,
            finance_history=finance_history,
            clock=lambda: datetime(2026, 1, 14, 12, 0, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result["creditRatio"]["provider"], "Yahoo Finance via yfinance")
        self.assertEqual(sequence, ["nasdaq", "nasdaq", "ishares", "ishares", "yahoo"])

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

    def test_fresh_credit_cache_is_used_only_after_all_live_sources_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "market-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "creditRatio": {
                            "savedAt": "2026-01-14T10:00:00Z",
                            "provider": "Nasdaq",
                            "valueBasis": "Close",
                            "sourceUrls": {
                                "HYG": "https://api.nasdaq.com/api/quote/HYG/historical",
                                "LQD": "https://api.nasdaq.com/api/quote/LQD/historical",
                            },
                            "histories": _credit_histories(),
                        },
                    }
                ),
                encoding="utf-8",
            )

            yahoo_attempted = False

            def unavailable_finance_history(_: float) -> dict:
                nonlocal yahoo_attempted
                yahoo_attempted = True
                raise OSError("Yahoo unavailable")

            result = market.collect_market_data(
                "2026-01-14T12:00:00Z",
                fetch_text=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                fetch_bytes=lambda *_: (_ for _ in ()).throw(OSError("unavailable")),
                finance_history=unavailable_finance_history,
                cache_path=cache_path,
                clock=lambda: datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(result["creditRatio"]["status"], "ok")
            self.assertEqual(result["creditRatio"]["cacheStatus"], "fresh-fallback")
            self.assertTrue(yahoo_attempted)
            self.assertEqual(result["creditRatio"]["provider"], "Nasdaq")

    def test_rate_limited_credit_provider_uses_valid_cache(self) -> None:
        class YFRateLimitError(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "market-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "creditRatio": {
                            "savedAt": "2026-01-14T05:00:00Z",
                            "provider": "Nasdaq",
                            "valueBasis": "Close",
                            "sourceUrls": {
                                "HYG": "https://api.nasdaq.com/api/quote/HYG/historical",
                                "LQD": "https://api.nasdaq.com/api/quote/LQD/historical",
                            },
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
            self.assertEqual(saved["schemaVersion"], 2)
            self.assertEqual(saved["creditRatio"]["valueBasis"], "Close")
            self.assertEqual(saved["creditRatio"]["provider"], "Yahoo Finance via yfinance")

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

        fred_batch_urls = [url for url in fred_urls if "fredgraph.csv" in url]
        self.assertEqual(len(fred_batch_urls), 1)
        self.assertIn(
            "NFCIRISK%2CWALCL%2CWDTGAL%2CRRPONTSYD%2CDTWEXBGS",
            fred_batch_urls[0],
        )
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
            [
                "NASDAQ_HYG_LQD",
                "ISHARES_HYG_LQD",
                "YAHOO_HYG_LQD",
                "NASDAQ_RSP_SPY",
                "SP_GLOBAL_RSP_SPY",
                "YAHOO_RSP_SPY",
                "CLUSDT",
                "XAUUSDT",
                "BTCUSDT",
                "QQQUSDT",
                "SPYUSDT",
            ],
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
