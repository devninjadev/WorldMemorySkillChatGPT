"""Deterministic public-source plan and collection for market observations."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import html
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .scheduler import parse_utc, utc_iso


FRED_GRAPH_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = (
    ("NFCIRISK", "credit-financial-conditions", "weekly-friday", "index", 14),
    ("WALCL", "us-net-liquidity", "weekly-wednesday", "usd-millions", 14),
    ("WDTGAL", "us-net-liquidity", "weekly-wednesday", "usd-millions", 14),
    ("RRPONTSYD", "us-net-liquidity", "daily", "usd-billions", 5),
    ("DTWEXBGS", "broad-us-dollar", "daily", "index-jan-2006-100", 7),
)
BINANCE_TICKERS = (
    (
        "CLUSDT",
        "oil",
        "usdm-perpetual",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
    ),
    (
        "XAUUSDT",
        "gold",
        "usdm-perpetual",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
    ),
    (
        "BTCUSDT",
        "bitcoin",
        "spot",
        "https://data-api.binance.vision/api/v3/ticker/24hr",
    ),
    (
        "QQQUSDT",
        "us-growth-equity-proxy",
        "usdm-perpetual",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
    ),
    (
        "SPYUSDT",
        "us-large-cap-equity-proxy",
        "usdm-perpetual",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
    ),
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 "
    "WorldMemoryAutopilot/2.0"
)
MAX_EXCHANGE_CLOCK_SKEW_SECONDS = 2.0
FetchText = Callable[[str, float], str]
FetchBytes = Callable[[str, float], bytes]
FinanceHistory = Callable[[float], dict[str, dict[date, float]]]
BreadthFinanceHistory = Callable[[float], dict[str, dict[date, float]]]
Clock = Callable[[], datetime]
MARKET_CACHE_SCHEMA_VERSION = 2
CREDIT_CACHE_REFRESH_SECONDS = 6 * 60 * 60
CREDIT_CACHE_MAX_OBSERVATION_DAYS = 7
CREDIT_SYMBOLS = ("HYG", "LQD")
ISHARES_PORTFOLIO_IDS = {"HYG": "239565", "LQD": "239566"}
BREADTH_SYMBOLS = ("RSP", "SPY")
BREADTH_MINIMUM_COMMON_SESSIONS = 21
BREADTH_CACHE_MAX_OBSERVATION_DAYS = 7
SP_GLOBAL_INDEX_IDS = {"RSP": "370", "SPY": "340"}
TREASURY_TEXT_VIEW_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
)
TREASURY_CSV_BASE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv"
)
TREASURY_XML_URL = (
    "https://home.treasury.gov/sites/default/files/interest-rates/yield.xml"
)
TREASURY_MATURITIES = (
    ("1M", "1 Mo", "BC_1MONTH"),
    ("1.5M", "1.5 Month", "BC_1_5MONTH"),
    ("2M", "2 Mo", "BC_2MONTH"),
    ("3M", "3 Mo", "BC_3MONTH"),
    ("4M", "4 Mo", "BC_4MONTH"),
    ("6M", "6 Mo", "BC_6MONTH"),
    ("1Y", "1 Yr", "BC_1YEAR"),
    ("2Y", "2 Yr", "BC_2YEAR"),
    ("3Y", "3 Yr", "BC_3YEAR"),
    ("5Y", "5 Yr", "BC_5YEAR"),
    ("7Y", "7 Yr", "BC_7YEAR"),
    ("10Y", "10 Yr", "BC_10YEAR"),
    ("20Y", "20 Yr", "BC_20YEAR"),
    ("30Y", "30 Yr", "BC_30YEAR"),
)
TREASURY_REQUIRED_MATURITIES = frozenset(("2Y", "5Y", "10Y", "30Y"))
TREASURY_SPREADS = {
    "2s10s": ("10Y", "2Y"),
    "5s30s": ("30Y", "5Y"),
    "3m10y": ("10Y", "3M"),
}


def _url(base: str, parameters: list[tuple[str, str]]) -> str:
    return f"{base}?{urlencode(parameters)}"


def market_data_plan(now: str) -> dict:
    planned = parse_utc(now)
    start_date = (planned - timedelta(days=180)).date().isoformat()
    end_date = planned.date().isoformat()
    yahoo_history_urls = {
        symbol: _url(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            [
                ("events", "history"),
                ("includeAdjustedClose", "true"),
                ("interval", "1d"),
                ("range", "3mo"),
            ],
        )
        for symbol in CREDIT_SYMBOLS
    }
    nasdaq_history_urls = {
        symbol: _url(
            f"https://api.nasdaq.com/api/quote/{symbol}/historical",
            [
                ("assetclass", "etf"),
                ("fromdate", start_date),
                ("todate", end_date),
                ("limit", "500"),
            ],
        )
        for symbol in CREDIT_SYMBOLS
    }
    ishares_history_urls = {
        symbol: _url(
            "https://www.blackrock.com/varnish-api/blk-one01-product-data/"
            "product-data/api/v1/get-fund-document",
            [
                ("appSubType", "ISHARES"),
                ("appType", "PRODUCT_PAGE"),
                ("component", "fundDownload"),
                ("locale", "en_US"),
                ("portfolioId", ISHARES_PORTFOLIO_IDS[symbol]),
                ("targetSite", "us-ishares"),
                ("userType", "individual"),
            ],
        )
        for symbol in CREDIT_SYMBOLS
    }
    breadth_nasdaq_history_urls = {
        symbol: _url(
            f"https://api.nasdaq.com/api/quote/{symbol}/historical",
            [
                ("assetclass", "etf"),
                ("fromdate", start_date),
                ("todate", end_date),
                ("limit", "500"),
            ],
        )
        for symbol in BREADTH_SYMBOLS
    }
    breadth_yahoo_history_urls = {
        symbol: _url(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            [
                ("events", "history"),
                ("includeAdjustedClose", "true"),
                ("interval", "1d"),
                ("range", "6mo"),
            ],
        )
        for symbol in BREADTH_SYMBOLS
    }
    sp_global_history_urls = {
        symbol: _url(
            "https://www.spglobal.com/spdji/en/idsexport/file.xls",
            [
                ("hostIdentifier", "48190c8c-42c4-46af-8d1a-0cd5db894797"),
                ("indexId", SP_GLOBAL_INDEX_IDS[symbol]),
                ("languageId", "1"),
                ("redesignExport", "true"),
                ("selectedModule", "PerformanceTableView"),
                ("selectedSubModule", "Daily"),
            ],
        )
        for symbol in BREADTH_SYMBOLS
    }
    fields = ["lastPrice", "priceChangePercent", "closeTime", "quoteVolume", "count"]
    treasury_parameters = [
        ("type", "daily_treasury_yield_curve"),
        ("field_tdr_date_value", str(planned.year)),
    ]
    return {
        "schemaVersion": 1,
        "plannedAt": utc_iso(planned),
        "collection": {
            "mode": "parallel-bounded-pass",
            "binanceWindow": "rolling-24h",
            "fredRequestMode": "multi-series-zip",
            "creditCacheRefreshSeconds": CREDIT_CACHE_REFRESH_SECONDS,
            "recordPerSourceFetchedAt": True,
            "recordObservationAt": True,
        },
        "fred": {
            "auth": "none",
            "batchUrl": _url(
                FRED_GRAPH_CSV_URL,
                [
                    ("cosd", start_date),
                    ("id", ",".join(series_id for series_id, *_ in FRED_SERIES)),
                ],
            ),
            "csv": {
                "dateField": "observation_date",
                "missingValues": ["", "."],
                "valueField": "series-id",
            },
            "series": [
                {
                    "id": series_id,
                    "role": role,
                    "frequency": frequency,
                    "unit": unit,
                    "freshnessWarningCalendarDays": warning_days,
                    "url": _url(
                        FRED_GRAPH_CSV_URL,
                        [("cosd", start_date), ("id", series_id)],
                    ),
                }
                for series_id, role, frequency, unit, warning_days in FRED_SERIES
            ],
        },
        "treasuryYieldCurve": {
            "provider": "U.S. Department of the Treasury",
            "auth": "none",
            "sourceOrder": ["treasury-csv", "treasury-xml"],
            "pageUrl": _url(TREASURY_TEXT_VIEW_URL, treasury_parameters),
            "csvUrl": _url(
                f"{TREASURY_CSV_BASE_URL}/{planned.year}/all",
                [*treasury_parameters, ("page", ""), ("_format", "csv")],
            ),
            "xmlUrl": TREASURY_XML_URL,
            "maturities": [name for name, _, _ in TREASURY_MATURITIES],
            "changeSessions": [1, 5],
            "spreads": {
                "2s10s": "10Y - 2Y",
                "5s30s": "30Y - 5Y",
                "3m10y": "10Y - 3M",
            },
            "unit": "percent",
            "valueBasis": "Daily Treasury Par Yield Curve Rate",
            "freshnessWarningCalendarDays": 5,
        },
        "creditRatio": {
            "provider": "priority-fallback",
            "symbols": list(CREDIT_SYMBOLS),
            "sourceOrder": ["nasdaq-close", "ishares-nav", "yahoo-close", "cache"],
            "nasdaqHistoryUrls": nasdaq_history_urls,
            "isharesHistoryUrls": ishares_history_urls,
            "yahooHistoryUrls": yahoo_history_urls,
            # Backward-compatible alias for callers that inspect the Yahoo direct fallback.
            "historyUrls": yahoo_history_urls,
            "period": "3mo",
            "interval": "1d",
            "preferredValueBasis": "Close",
            "priceField": "Close",
            "autoAdjust": False,
            "alignment": "inner-common-session",
            "formula": "HYG Close / LQD Close",
            "formulas": {
                "Close": "HYG Close / LQD Close",
                "NAV": "HYG NAV per Share / LQD NAV per Share",
            },
            "change5Sessions": "(ratio_t / ratio_t-5 - 1) * 100",
            "minimumCommonSessions": 6,
            "freshnessWarningCalendarDays": 7,
        },
        "equityBreadth": {
            "provider": "priority-fallback",
            "symbols": list(BREADTH_SYMBOLS),
            "sourceOrder": [
                "nasdaq-close",
                "sp-global-price-return",
                "yahoo-close",
                "cache",
            ],
            "nasdaqHistoryUrls": breadth_nasdaq_history_urls,
            "spGlobalHistoryUrls": sp_global_history_urls,
            "yahooHistoryUrls": breadth_yahoo_history_urls,
            "alignment": "inner-common-session",
            "formulas": {
                "Close": "RSP Close / SPY Close",
                "Price Return Index": (
                    "S&P 500 Equal Weight Price Return Index / "
                    "S&P 500 Price Return Index"
                ),
            },
            "changeSessions": [1, 5, 20],
            "minimumCommonSessions": BREADTH_MINIMUM_COMMON_SESSIONS,
            "freshnessWarningCalendarDays": 7,
        },
        "derived": [
            {
                "id": "US_NET_LIQUIDITY",
                "requires": ["WALCL", "WDTGAL", "RRPONTSYD"],
                "formula": "WALCL - WDTGAL - (RRPONTSYD * 1000)",
                "unit": "usd-millions",
                "anchor": "WALCL observation dates",
                "alignment": "last observation on or before each anchor date",
                "changeWeeks": [1, 4, 13],
            }
        ],
        "binance": [
            {
                "symbol": symbol,
                "role": role,
                "market": market,
                "auth": "none",
                "url": _url(endpoint, [("symbol", symbol)]),
                "fields": fields,
                "maxQuoteAgeSeconds": 300,
            }
            for symbol, role, market, endpoint in BINANCE_TICKERS
        ],
        "failurePolicy": {
            "attemptIndependently": True,
            "netLiquidityRequiresAllComponents": True,
            "preserveSuccessfulObservations": True,
            "inventSubstitutes": False,
        },
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_text(url: str, timeout: float) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/csv,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def _fetch_bytes(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": (
                "application/zip,application/vnd.ms-excel,application/xml;q=0.9,"
                "text/csv;q=0.8,*/*;q=0.1"
            ),
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _clock_iso(clock: Clock) -> str:
    observed = _clock_utc(clock)
    return utc_iso(observed)


def _clock_utc(clock: Clock) -> datetime:
    observed = clock()
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("market collection clock must be timezone-aware")
    return observed.astimezone(timezone.utc)


def _finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be a finite number")
    return parsed


def _parse_fred_csv(series_id: str, payload: str, cutoff: datetime) -> list[tuple[date, float]]:
    reader = csv.DictReader(StringIO(payload))
    if reader.fieldnames is None or "observation_date" not in reader.fieldnames:
        raise ValueError(f"{series_id} CSV missing observation_date")
    if series_id not in reader.fieldnames:
        raise ValueError(f"{series_id} CSV missing value column")

    observations: dict[date, float] = {}
    for row in reader:
        raw_value = row.get(series_id)
        if raw_value is None or raw_value.strip() in {"", "."}:
            continue
        observed_date = date.fromisoformat((row.get("observation_date") or "").strip())
        if observed_date > cutoff.date():
            continue
        value = _finite_number(raw_value.strip(), field=series_id)
        if observed_date in observations and observations[observed_date] != value:
            raise ValueError(f"{series_id} has conflicting observations for {observed_date}")
        observations[observed_date] = value
    if not observations:
        raise ValueError(f"{series_id} has no observation on or before cutoff")
    return sorted(observations.items())


def _treasury_row_values(
    raw_values: dict[str, object], field_names: dict[str, str]
) -> dict[str, float]:
    values: dict[str, float] = {}
    for maturity, field in field_names.items():
        raw_value = raw_values.get(field)
        if raw_value is None:
            continue
        text_value = str(raw_value).strip()
        if not text_value:
            continue
        value = _finite_number(text_value, field=f"Treasury {maturity}")
        values[maturity] = value
    return values


def _finalize_treasury_history(
    observations: dict[date, dict[str, float]], cutoff: datetime
) -> list[tuple[date, dict[str, float]]]:
    eligible = {
        observed_day: values
        for observed_day, values in observations.items()
        if observed_day <= cutoff.date()
        and TREASURY_REQUIRED_MATURITIES.issubset(values)
    }
    if not eligible:
        raise ValueError(
            "Treasury yield curve has no complete observation on or before cutoff"
        )
    return sorted(eligible.items())


def _parse_treasury_csv(
    payload: str, cutoff: datetime
) -> list[tuple[date, dict[str, float]]]:
    reader = csv.DictReader(StringIO(payload))
    if reader.fieldnames is None or "Date" not in reader.fieldnames:
        raise ValueError("Treasury CSV missing Date")
    required_fields = {csv_name for _, csv_name, _ in TREASURY_MATURITIES}
    if not required_fields.issubset(reader.fieldnames):
        raise ValueError("Treasury CSV missing maturity columns")

    field_names = {name: csv_name for name, csv_name, _ in TREASURY_MATURITIES}
    observations: dict[date, dict[str, float]] = {}
    for row in reader:
        raw_day = (row.get("Date") or "").strip()
        if not raw_day:
            continue
        observed_day = datetime.strptime(raw_day, "%m/%d/%Y").date()
        values = _treasury_row_values(row, field_names)
        if observed_day in observations and observations[observed_day] != values:
            raise ValueError(
                f"Treasury CSV has conflicting observations for {observed_day}"
            )
        observations[observed_day] = values
    return _finalize_treasury_history(observations, cutoff)


def _parse_treasury_xml(
    payload: str, cutoff: datetime
) -> list[tuple[date, dict[str, float]]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("Treasury XML is malformed") from exc
    field_names = {name: xml_name for name, _, xml_name in TREASURY_MATURITIES}
    observations: dict[date, dict[str, float]] = {}
    for row in root.findall(".//G_NEW_DATE"):
        raw_day = (row.findtext("NEW_DATE") or "").strip()
        if raw_day:
            observed_day = datetime.strptime(raw_day, "%m-%d-%Y").date()
        else:
            bid_curve_day = (row.findtext("BID_CURVE_DATE") or "").strip()
            if not bid_curve_day:
                continue
            observed_day = datetime.strptime(bid_curve_day, "%d-%b-%y").date()
        raw_values = {
            xml_name: row.findtext(f".//{xml_name}")
            for xml_name in field_names.values()
        }
        values = _treasury_row_values(raw_values, field_names)
        if observed_day in observations and observations[observed_day] != values:
            raise ValueError(
                f"Treasury XML has conflicting observations for {observed_day}"
            )
        observations[observed_day] = values
    return _finalize_treasury_history(observations, cutoff)


def _treasury_spreads(values: dict[str, float]) -> dict[str, float | None]:
    return {
        spread: round(
            (values[long_maturity] - values[short_maturity]) * 100, 6
        )
        if long_maturity in values and short_maturity in values
        else None
        for spread, (long_maturity, short_maturity) in TREASURY_SPREADS.items()
    }


def _treasury_snapshot(
    history: list[tuple[date, dict[str, float]]]
) -> dict[str, object]:
    observation_day, latest = history[-1]
    changes: dict[str, dict[str, float | None]] = {}
    for maturity, _, _ in TREASURY_MATURITIES:
        changes[maturity] = {}
        for window in (1, 5):
            previous = history[-window - 1][1] if len(history) > window else {}
            changes[maturity][f"{window}-session"] = (
                round((latest[maturity] - previous[maturity]) * 100, 6)
                if maturity in latest and maturity in previous
                else None
            )

    latest_spreads = _treasury_spreads(latest)
    spread_changes: dict[str, dict[str, float | None]] = {}
    for spread in TREASURY_SPREADS:
        spread_changes[spread] = {}
        for window in (1, 5):
            previous_spreads = (
                _treasury_spreads(history[-window - 1][1])
                if len(history) > window
                else {}
            )
            previous = previous_spreads.get(spread)
            current = latest_spreads.get(spread)
            spread_changes[spread][f"{window}-session"] = (
                round(current - previous, 6)
                if current is not None and previous is not None
                else None
            )
    return {
        "observationDate": observation_day.isoformat(),
        "yieldsPct": latest,
        "changesBp": changes,
        "spreadsBp": latest_spreads,
        "spreadChangesBp": spread_changes,
    }


def _change_map(
    values: list[float],
    windows: tuple[int, ...],
    suffix: str,
) -> dict[str, float | None]:
    latest = values[-1]
    return {
        f"{window}-{suffix}": latest - values[-window - 1]
        if len(values) > window
        else None
        for window in windows
    }


def _parse_yahoo_history(payload: str, cutoff: datetime, symbol: str) -> dict[date, float]:
    document = json.loads(payload)
    result = document["chart"]["result"]
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError(f"{symbol} history missing chart result")
    chart = result[0]
    timestamps = chart["timestamp"]
    closes = chart["indicators"]["quote"][0]["close"]
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise ValueError(f"{symbol} history arrays are malformed")
    if len(timestamps) != len(closes):
        raise ValueError(f"{symbol} history arrays differ in length")

    observations: dict[date, float] = {}
    for timestamp, raw_close in zip(timestamps, closes):
        if raw_close is None:
            continue
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise ValueError(f"{symbol} timestamp must be an integer")
        observed = datetime.fromtimestamp(timestamp, timezone.utc)
        if observed > cutoff:
            continue
        close = _finite_number(raw_close, field=f"{symbol} close")
        if close <= 0:
            raise ValueError(f"{symbol} close must be positive")
        observations[observed.date()] = close
    if not observations:
        raise ValueError(f"{symbol} has no close on or before cutoff")
    return observations


def _parse_nasdaq_history(payload: str, cutoff: datetime, symbol: str) -> dict[date, float]:
    document = json.loads(payload)
    data = document.get("data")
    if not isinstance(data, dict) or data.get("symbol") != symbol:
        raise ValueError(f"{symbol} Nasdaq history symbol mismatch")
    table = data.get("tradesTable")
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{symbol} Nasdaq history is missing rows")

    observations: dict[date, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{symbol} Nasdaq history row is malformed")
        raw_day = row.get("date")
        raw_close = row.get("close")
        if not isinstance(raw_day, str) or not isinstance(raw_close, str):
            raise ValueError(f"{symbol} Nasdaq history row is missing date or close")
        observed_day = datetime.strptime(raw_day.strip(), "%m/%d/%Y").date()
        if observed_day > cutoff.date():
            continue
        close = _finite_number(
            raw_close.replace("$", "").replace(",", "").strip(),
            field=f"{symbol} Nasdaq close",
        )
        if close <= 0:
            raise ValueError(f"{symbol} Nasdaq close must be positive")
        if observed_day in observations and observations[observed_day] != close:
            raise ValueError(f"{symbol} Nasdaq has conflicting closes for {observed_day}")
        observations[observed_day] = close
    if not observations:
        raise ValueError(f"{symbol} Nasdaq has no close on or before cutoff")
    return dict(sorted(observations.items()))


def _decode_ishares_workbook(payload: bytes) -> str:
    if not payload:
        raise ValueError("iShares history workbook is empty")
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in payload[:200]:
        return payload.decode("utf-16")
    return payload.decode("utf-8-sig", errors="replace")


def _parse_ishares_history(payload: bytes, cutoff: datetime, symbol: str) -> dict[date, float]:
    document = _decode_ishares_workbook(payload)
    worksheet = re.search(
        r"<(?:\w+:)?Worksheet\b[^>]*(?:\w+:)?Name\s*=\s*['\"]Historical['\"][^>]*>"
        r"(.*?)</(?:\w+:)?Worksheet\s*>",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if worksheet is None:
        raise ValueError(f"{symbol} iShares workbook is missing Historical sheet")

    observations: dict[date, float] = {}
    for row_match in re.finditer(
        r"<(?:\w+:)?Row\b[^>]*>(.*?)</(?:\w+:)?Row\s*>",
        worksheet.group(1),
        flags=re.IGNORECASE | re.DOTALL,
    ):
        cells = [
            html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
            for value in re.findall(
                r"<(?:\w+:)?Data\b[^>]*>(.*?)</(?:\w+:)?Data\s*>",
                row_match.group(1),
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
        if len(cells) < 2:
            continue
        try:
            observed_day = date.fromisoformat(cells[0][:10])
        except ValueError:
            try:
                observed_day = datetime.strptime(cells[0], "%b %d, %Y").date()
            except ValueError:
                continue
        if observed_day > cutoff.date():
            continue
        nav = _finite_number(cells[1].replace(",", ""), field=f"{symbol} iShares NAV")
        if nav <= 0:
            raise ValueError(f"{symbol} iShares NAV must be positive")
        if observed_day in observations and observations[observed_day] != nav:
            raise ValueError(f"{symbol} iShares has conflicting NAVs for {observed_day}")
        observations[observed_day] = nav
    if not observations:
        raise ValueError(f"{symbol} iShares has no NAV on or before cutoff")
    return dict(sorted(observations.items()))


def _parse_sp_global_history(payload: bytes, cutoff: datetime, symbol: str) -> dict[date, float]:
    if not payload:
        raise ValueError(f"{symbol} S&P Global workbook is empty")
    from .bootstrap import ensure_runtime_dependencies

    ensure_runtime_dependencies(required_modules=("pandas", "xlrd"))
    import pandas as pd

    try:
        frame = pd.read_excel(BytesIO(payload), header=None, engine="xlrd")
    except Exception as exc:
        raise ValueError(f"{symbol} S&P Global workbook is unreadable") from exc
    if frame is None or frame.empty:
        raise ValueError(f"{symbol} S&P Global workbook contains no rows")

    header_row = None
    date_column = None
    value_column = None
    for row_index, row in frame.iterrows():
        labels = [str(value).strip().lower() for value in row.tolist()]
        for column_index, label in enumerate(labels):
            if label in {"date", "effective date"} or label.endswith(" date"):
                candidates = [
                    index
                    for index, candidate in enumerate(labels)
                    if index != column_index
                    and any(
                        token in candidate
                        for token in ("index level", "price return", "close", "value")
                    )
                ]
                if candidates:
                    header_row = row_index
                    date_column = column_index
                    value_column = candidates[0]
                    break
        if header_row is not None:
            break
    if header_row is None or date_column is None or value_column is None:
        raise ValueError(f"{symbol} S&P Global workbook is missing date/value headers")

    observations: dict[date, float] = {}
    for row_index in range(int(header_row) + 1, len(frame.index)):
        raw_day = frame.iloc[row_index, date_column]
        raw_value = frame.iloc[row_index, value_column]
        try:
            observed_day = pd.to_datetime(raw_day, errors="raise").date()
            value = _finite_number(raw_value, field=f"{symbol} S&P Global index level")
        except (TypeError, ValueError):
            continue
        if observed_day > cutoff.date() or value <= 0:
            continue
        if observed_day in observations and observations[observed_day] != value:
            raise ValueError(
                f"{symbol} S&P Global has conflicting values for {observed_day}"
            )
        observations[observed_day] = value
    if not observations:
        raise ValueError(f"{symbol} S&P Global has no value on or before cutoff")
    return dict(sorted(observations.items()))


def _normalize_pair_histories(
    raw_histories: object,
    cutoff: datetime,
    symbols: tuple[str, str],
    label: str,
) -> dict[str, dict[date, float]]:
    if not isinstance(raw_histories, dict):
        raise ValueError(f"{label} history provider returned a non-object")
    normalized: dict[str, dict[date, float]] = {}
    for symbol in symbols:
        raw_history = raw_histories.get(symbol)
        if not isinstance(raw_history, dict):
            raise ValueError(f"{label} history provider is missing {symbol}")
        history: dict[date, float] = {}
        for raw_day, raw_value in raw_history.items():
            observed_day = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
            if observed_day > cutoff.date():
                continue
            value = _finite_number(raw_value, field=f"{symbol} value")
            if value <= 0:
                raise ValueError(f"{symbol} value must be positive")
            history[observed_day] = value
        if not history:
            raise ValueError(f"{symbol} has no value on or before cutoff")
        normalized[symbol] = dict(sorted(history.items()))
    return normalized


def _normalize_credit_histories(
    raw_histories: object, cutoff: datetime
) -> dict[str, dict[date, float]]:
    return _normalize_pair_histories(raw_histories, cutoff, CREDIT_SYMBOLS, "HYG/LQD")


def _default_market_cache_path() -> Path:
    root = os.environ.get("WORLD_MEMORY_CACHE_DIR")
    directory = Path(root).expanduser().resolve() if root else Path.cwd() / ".world-memory-runtime"
    return directory / "market-cache.json"


def _load_credit_cache(path: Path | None, cutoff: datetime) -> dict | None:
    if path is None or not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schemaVersion") != MARKET_CACHE_SCHEMA_VERSION:
            return None
        payload = document["creditRatio"]
        saved_at = parse_utc(payload["savedAt"])
        if saved_at > cutoff + timedelta(seconds=MAX_EXCHANGE_CLOCK_SKEW_SECONDS):
            return None
        provider = payload["provider"]
        value_basis = payload["valueBasis"]
        source_urls = payload["sourceUrls"]
        if not isinstance(provider, str) or not provider.strip():
            return None
        if value_basis not in {"Close", "NAV"}:
            return None
        if not isinstance(source_urls, dict) or set(source_urls) != set(CREDIT_SYMBOLS):
            return None
        if not all(isinstance(source_urls[symbol], str) and source_urls[symbol] for symbol in CREDIT_SYMBOLS):
            return None
        histories = _normalize_credit_histories(payload["histories"], cutoff)
        common_dates = sorted(set(histories["HYG"]) & set(histories["LQD"]))
        if len(common_dates) < 6:
            return None
        observation_date = common_dates[-1]
        if (cutoff.date() - observation_date).days > CREDIT_CACHE_MAX_OBSERVATION_DAYS:
            return None
        return {
            "savedAt": utc_iso(saved_at),
            "ageSeconds": max(0.0, (cutoff - saved_at).total_seconds()),
            "observationDate": observation_date,
            "histories": histories,
            "provider": provider,
            "valueBasis": value_basis,
            "sourceUrls": source_urls,
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_credit_cache(
    path: Path | None,
    histories: dict[str, dict[date, float]],
    saved_at: str,
    *,
    provider: str,
    value_basis: str,
    source_urls: dict[str, str],
) -> None:
    if path is None:
        return
    payload = {
        "savedAt": saved_at,
        "provider": provider,
        "valueBasis": value_basis,
        "sourceUrls": source_urls,
        "histories": {
            symbol: {day.isoformat(): value for day, value in history.items()}
            for symbol, history in histories.items()
        },
    }
    _write_market_cache_section(path, "creditRatio", payload)


def _write_market_cache_section(path: Path, section: str, payload: dict) -> None:
    document: dict = {"schemaVersion": MARKET_CACHE_SCHEMA_VERSION}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("schemaVersion") == MARKET_CACHE_SCHEMA_VERSION:
                document.update(existing)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    document["schemaVersion"] = MARKET_CACHE_SCHEMA_VERSION
    document[section] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_breadth_cache(path: Path | None, cutoff: datetime) -> dict | None:
    if path is None or not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schemaVersion") != MARKET_CACHE_SCHEMA_VERSION:
            return None
        payload = document["equityBreadth"]
        saved_at = parse_utc(payload["savedAt"])
        if saved_at > cutoff + timedelta(seconds=MAX_EXCHANGE_CLOCK_SKEW_SECONDS):
            return None
        provider = payload["provider"]
        value_basis = payload["valueBasis"]
        source_urls = payload["sourceUrls"]
        if value_basis not in {"Close", "Price Return Index"}:
            return None
        if not isinstance(provider, str) or not provider.strip():
            return None
        if not isinstance(source_urls, dict) or set(source_urls) != set(BREADTH_SYMBOLS):
            return None
        histories = _normalize_pair_histories(
            payload["histories"], cutoff, BREADTH_SYMBOLS, "RSP/SPY"
        )
        common_dates = sorted(set(histories["RSP"]) & set(histories["SPY"]))
        if len(common_dates) < BREADTH_MINIMUM_COMMON_SESSIONS:
            return None
        observation_date = common_dates[-1]
        if (cutoff.date() - observation_date).days > BREADTH_CACHE_MAX_OBSERVATION_DAYS:
            return None
        return {
            "savedAt": utc_iso(saved_at),
            "ageSeconds": max(0.0, (cutoff - saved_at).total_seconds()),
            "histories": histories,
            "provider": provider,
            "valueBasis": value_basis,
            "sourceUrls": source_urls,
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_breadth_cache(
    path: Path | None,
    histories: dict[str, dict[date, float]],
    saved_at: str,
    *,
    provider: str,
    value_basis: str,
    source_urls: dict[str, str],
) -> None:
    if path is None:
        return
    _write_market_cache_section(
        path,
        "equityBreadth",
        {
            "savedAt": saved_at,
            "provider": provider,
            "valueBasis": value_basis,
            "sourceUrls": source_urls,
            "histories": {
                symbol: {day.isoformat(): value for day, value in history.items()}
                for symbol, history in histories.items()
            },
        },
    )


def _yfinance_pair_history(
    symbols: tuple[str, str], timeout: float, *, period: str
) -> dict[str, dict[date, float]]:
    from .bootstrap import ensure_runtime_dependencies

    ensure_runtime_dependencies()
    import yfinance as yf

    def fetch_symbol(symbol: str) -> tuple[str, object]:
        frame = yf.Ticker(symbol).history(
            period=period,
            interval="1d",
            auto_adjust=False,
            actions=False,
            repair=False,
            raise_errors=True,
            timeout=timeout,
        )
        return symbol, frame

    frames: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(fetch_symbol, symbol) for symbol in symbols]
        for future in futures:
            symbol, frame = future.result()
            frames[symbol] = frame

    histories: dict[str, dict[date, float]] = {}
    for symbol in symbols:
        frame = frames[symbol]
        if frame is None or frame.empty:
            raise ValueError(f"Yahoo returned no usable {symbol} history")
        try:
            closes = frame["Close"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Yahoo history is missing {symbol} Close") from exc
        history: dict[date, float] = {}
        for raw_index, raw_close in closes.items():
            try:
                close = _finite_number(raw_close, field=f"{symbol} close")
            except (TypeError, ValueError):
                continue
            observed_day = raw_index.date()
            if close > 0:
                history[observed_day] = close
        histories[symbol] = history
    return histories


def _yfinance_history(timeout: float) -> dict[str, dict[date, float]]:
    return _yfinance_pair_history(CREDIT_SYMBOLS, timeout, period="3mo")


def _yfinance_breadth_history(timeout: float) -> dict[str, dict[date, float]]:
    return _yfinance_pair_history(BREADTH_SYMBOLS, timeout, period="6mo")


def _parse_fred_batch(payload: bytes, cutoff: datetime) -> dict[str, list[tuple[date, float]]]:
    histories: dict[str, list[tuple[date, float]]] = {}
    try:
        with ZipFile(BytesIO(payload)) as archive:
            for name in archive.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                document = archive.read(name).decode("utf-8-sig")
                reader = csv.DictReader(StringIO(document))
                fields = set(reader.fieldnames or ())
                for series_id, *_ in FRED_SERIES:
                    if series_id in fields:
                        histories[series_id] = _parse_fred_csv(series_id, document, cutoff)
    except (BadZipFile, KeyError, UnicodeError) as exc:
        raise ValueError("FRED batch response is not a valid series ZIP") from exc
    return histories


def _parse_binance_ticker(payload: str, expected_symbol: str, cutoff: datetime) -> dict:
    document = json.loads(payload)
    if document.get("symbol") != expected_symbol:
        raise ValueError(f"{expected_symbol} ticker symbol mismatch")
    price = _finite_number(document.get("lastPrice"), field=f"{expected_symbol} lastPrice")
    change = _finite_number(
        document.get("priceChangePercent"), field=f"{expected_symbol} priceChangePercent"
    )
    quote_volume = _finite_number(
        document.get("quoteVolume"), field=f"{expected_symbol} quoteVolume"
    )
    count = document.get("count")
    close_time = document.get("closeTime")
    if price <= 0 or quote_volume < 0:
        raise ValueError(f"{expected_symbol} ticker has invalid price or volume")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"{expected_symbol} count must be a nonnegative integer")
    if isinstance(close_time, bool) or not isinstance(close_time, int):
        raise ValueError(f"{expected_symbol} closeTime must be an integer")
    observed = datetime.fromtimestamp(close_time / 1000, timezone.utc)
    age_seconds = (cutoff - observed).total_seconds()
    if age_seconds < -MAX_EXCHANGE_CLOCK_SKEW_SECONDS:
        raise ValueError(f"{expected_symbol} closeTime is in the future")
    if age_seconds > 300:
        raise ValueError(f"{expected_symbol} quote is older than 300 seconds")
    return {
        "observationAt": utc_iso(observed),
        "price": price,
        "change24hPct": change,
        "quoteVolume": quote_volume,
        "tradeCount": count,
    }


def _latest_as_of(
    observations: list[tuple[date, float]], anchor: date
) -> tuple[date, float] | None:
    eligible = [item for item in observations if item[0] <= anchor]
    return eligible[-1] if eligible else None


def collect_market_data(
    now: str,
    *,
    timeout: float = 20.0,
    fetch_text: FetchText = _fetch_text,
    fetch_bytes: FetchBytes | None = None,
    finance_history: FinanceHistory | None = None,
    breadth_finance_history: BreadthFinanceHistory | None = None,
    cache_path: Path | None = None,
    clock: Clock = _utc_now,
) -> dict:
    """Collect every public market source independently and derive stable signals."""

    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    cutoff = parse_utc(now)
    plan = market_data_plan(now)
    started_at = _clock_iso(clock)
    resolved_cache_path = cache_path
    if resolved_cache_path is None and fetch_text is _fetch_text:
        resolved_cache_path = _default_market_cache_path()
    cached_credit = _load_credit_cache(resolved_cache_path, cutoff)
    cached_breadth = _load_breadth_cache(resolved_cache_path, cutoff)
    active_finance_history = finance_history
    if active_finance_history is None and fetch_text is _fetch_text:
        active_finance_history = _yfinance_history
    active_breadth_finance_history = breadth_finance_history
    if active_breadth_finance_history is None and fetch_text is _fetch_text:
        active_breadth_finance_history = _yfinance_breadth_history
    gaps: list[dict] = []
    fred_results: dict[str, dict] = {}
    fred_history: dict[str, list[tuple[date, float]]] = {}

    batch_fetch = fetch_bytes
    if batch_fetch is None and fetch_text is _fetch_text:
        batch_fetch = _fetch_bytes

    def attempt_fetch(loader: Callable[[str, float], object], url: str) -> dict:
        try:
            payload = loader(url, timeout)
            return {
                "payload": payload,
                "fetchedAt": _clock_iso(clock),
                "error": None,
                "errorType": None,
                "rateLimited": False,
            }
        except Exception as exc:
            error_type = exc.__class__.__name__
            return {
                "payload": None,
                "fetchedAt": _clock_iso(clock),
                "error": exc,
                "errorType": error_type,
                "rateLimited": error_type == "YFRateLimitError",
            }

    request_specs: list[tuple[str, Callable[[str, float], object], str]] = []
    if batch_fetch is not None:
        request_specs.append(("fred:batch", batch_fetch, plan["fred"]["batchUrl"]))
    else:
        request_specs.extend(
            (f"fred:{source['id']}", fetch_text, source["url"])
            for source in plan["fred"]["series"]
        )
    request_specs.extend(
        (
            f"nasdaq:{symbol}",
            fetch_text,
            plan["creditRatio"]["nasdaqHistoryUrls"][symbol],
        )
        for symbol in plan["creditRatio"]["symbols"]
    )
    request_specs.extend(
        (
            f"breadth-nasdaq:{symbol}",
            fetch_text,
            plan["equityBreadth"]["nasdaqHistoryUrls"][symbol],
        )
        for symbol in plan["equityBreadth"]["symbols"]
    )
    request_specs.append(
        ("treasury:csv", fetch_text, plan["treasuryYieldCurve"]["csvUrl"])
    )
    request_specs.extend(
        (f"binance:{source['symbol']}", fetch_text, source["url"])
        for source in plan["binance"]
    )

    attempts: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(request_specs)) as executor:
        futures = [
            (key, executor.submit(attempt_fetch, loader, url))
            for key, loader, url in request_specs
        ]
        for key, future in futures:
            attempts[key] = future.result()

    treasury_attempts: list[dict] = []
    treasury_history: list[tuple[date, dict[str, float]]] | None = None
    treasury_source_url: str | None = None
    treasury_fetched_at: str | None = None

    def try_treasury_source(
        *, source_id: str, url: str, attempt: dict, parser: Callable
    ) -> bool:
        nonlocal treasury_history, treasury_source_url, treasury_fetched_at
        try:
            if attempt["error"] is not None:
                raise ValueError(
                    str(attempt["error"]).strip() or f"{source_id} request failed"
                )
            history = parser(attempt["payload"], cutoff)
            treasury_history = history
            treasury_source_url = url
            treasury_fetched_at = attempt["fetchedAt"]
            treasury_attempts.append(
                {
                    "sourceId": source_id,
                    "status": "ok",
                    "sourceUrl": url,
                    "fetchedAt": attempt["fetchedAt"],
                }
            )
            return True
        except (KeyError, OSError, TypeError, ValueError) as exc:
            reason = str(exc).strip() or f"{source_id} failed"
            public_attempt = {
                "sourceId": source_id,
                "status": "failed",
                "sourceUrl": url,
                "fetchedAt": attempt["fetchedAt"],
                "reason": reason,
            }
            treasury_attempts.append(public_attempt)
            gaps.append(public_attempt.copy())
            return False

    treasury_plan = plan["treasuryYieldCurve"]
    treasury_ok = try_treasury_source(
        source_id="TREASURY_YIELD_CSV",
        url=treasury_plan["csvUrl"],
        attempt=attempts["treasury:csv"],
        parser=_parse_treasury_csv,
    )
    if not treasury_ok:
        xml_attempt = attempt_fetch(fetch_text, treasury_plan["xmlUrl"])
        treasury_ok = try_treasury_source(
            source_id="TREASURY_YIELD_XML",
            url=treasury_plan["xmlUrl"],
            attempt=xml_attempt,
            parser=_parse_treasury_xml,
        )

    if treasury_ok and treasury_history is not None:
        snapshot = _treasury_snapshot(treasury_history)
        observation_day = date.fromisoformat(str(snapshot["observationDate"]))
        lag_days = (cutoff.date() - observation_day).days
        freshness = (
            "lagged"
            if lag_days > treasury_plan["freshnessWarningCalendarDays"]
            else "current"
        )
        treasury_yield_curve = {
            "sourceId": "US_TREASURY_YIELD_CURVE",
            "status": "ok",
            "provider": treasury_plan["provider"],
            "sourceUrl": treasury_source_url,
            "pageUrl": treasury_plan["pageUrl"],
            "fetchedAt": treasury_fetched_at,
            "unit": treasury_plan["unit"],
            "valueBasis": treasury_plan["valueBasis"],
            **snapshot,
            "lagCalendarDays": lag_days,
            "freshness": freshness,
            "attempts": treasury_attempts,
        }
        if freshness == "lagged":
            gaps.append(
                {
                    "sourceId": "US_TREASURY_YIELD_CURVE",
                    "status": "lagged",
                    "fetchedAt": treasury_fetched_at,
                    "reason": f"latest observation is {lag_days} calendar days old",
                }
            )
    else:
        treasury_yield_curve = {
            "sourceId": "US_TREASURY_YIELD_CURVE",
            "status": "failed",
            "provider": treasury_plan["provider"],
            "pageUrl": treasury_plan["pageUrl"],
            "attempts": treasury_attempts,
        }

    batch_error: Exception | None = None
    if batch_fetch is not None:
        batch_attempt = attempts["fred:batch"]
        fred_fetched_at = batch_attempt["fetchedAt"]
        batch_error = batch_attempt["error"]
        if batch_error is None:
            try:
                fred_history = _parse_fred_batch(batch_attempt["payload"], cutoff)
            except (TypeError, ValueError) as exc:
                batch_error = exc

    for source in plan["fred"]["series"]:
        source_id = source["id"]
        fetched_at: str | None = None
        try:
            if batch_fetch is None:
                attempt = attempts[f"fred:{source_id}"]
                fetched_at = attempt["fetchedAt"]
                if attempt["error"] is not None:
                    raise ValueError(str(attempt["error"]).strip() or "FRED request failed")
                observations = _parse_fred_csv(source_id, attempt["payload"], cutoff)
                fred_history[source_id] = observations
            else:
                fetched_at = fred_fetched_at
                if batch_error is not None:
                    raise ValueError(str(batch_error).strip() or "FRED batch request failed")
                if source_id not in fred_history:
                    raise ValueError(f"FRED batch is missing {source_id}")
                observations = fred_history[source_id]
            observation_date, level = observations[-1]
            lag_days = (cutoff.date() - observation_date).days
            if source_id == "NFCIRISK":
                changes = _change_map(
                    [value for _, value in observations], (1, 4, 13), "observation"
                )
            elif source_id == "DTWEXBGS":
                changes = _change_map(
                    [value for _, value in observations], (1, 5), "session"
                )
            else:
                changes = {}
            freshness = (
                "lagged"
                if lag_days > source["freshnessWarningCalendarDays"]
                else "current"
            )
            fred_results[source_id] = {
                "sourceId": source_id,
                "status": "ok",
                "sourceUrl": source["url"],
                "fetchedAt": fetched_at,
                "observationDate": observation_date.isoformat(),
                "frequency": source["frequency"],
                "unit": source["unit"],
                "level": level,
                "changes": changes,
                "lagCalendarDays": lag_days,
                "freshness": freshness,
            }
            if freshness == "lagged":
                gaps.append(
                    {
                        "sourceId": source_id,
                        "status": "lagged",
                        "fetchedAt": fetched_at,
                        "reason": f"latest observation is {lag_days} calendar days old",
                    }
                )
        except (KeyError, IndexError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            fetched_at = fetched_at or _clock_iso(clock)
            reason = str(exc).strip() or "market source failed"
            fred_results[source_id] = {
                "sourceId": source_id,
                "status": "failed",
                "sourceUrl": source["url"],
                "fetchedAt": fetched_at,
                "error": reason,
            }
            gaps.append(
                {
                    "sourceId": source_id,
                    "status": "failed",
                    "fetchedAt": fetched_at,
                    "reason": reason,
                }
            )

    ratio_sources: dict[str, dict] = {}
    ratio_history: dict[str, dict[date, float]] = {}
    credit_cache_status: str | None = None
    credit_provider: str | None = None
    credit_value_basis: str | None = None
    credit_source_urls: dict[str, str] = {}
    credit_attempts: list[dict] = []

    def record_credit_failure(
        stage_id: str,
        provider: str,
        failed_attempts: list[dict],
    ) -> None:
        fetched_at = max((item["fetchedAt"] for item in failed_attempts), default=started_at)
        reasons = [
            str(item["error"]).strip() or f"{provider} request failed"
            for item in failed_attempts
            if item.get("error") is not None
        ]
        reason = "; ".join(dict.fromkeys(reasons)) or f"{provider} pair is incomplete"
        rate_limited = any(bool(item.get("rateLimited")) for item in failed_attempts)
        error_types = sorted(
            {
                str(item["errorType"])
                for item in failed_attempts
                if item.get("errorType")
            }
        )
        entry = {
            "sourceId": stage_id,
            "status": "failed",
            "provider": provider,
            "fetchedAt": fetched_at,
            "reason": reason,
            "rateLimited": rate_limited,
        }
        if error_types:
            entry["errorTypes"] = error_types
        credit_attempts.append(entry)
        gaps.append(entry.copy())

    def apply_pair(
        *,
        stage_id: str,
        provider: str,
        value_basis: str,
        source_urls: dict[str, str],
        pair_attempts: dict[str, dict],
        parser: Callable[[object, datetime, str], dict[date, float]],
        key_prefix: str,
    ) -> bool:
        nonlocal ratio_history, ratio_sources, credit_cache_status
        nonlocal credit_provider, credit_value_basis, credit_source_urls
        histories: dict[str, dict[date, float]] = {}
        sources: dict[str, dict] = {}
        normalized_attempts: list[dict] = []
        for symbol in CREDIT_SYMBOLS:
            attempt = pair_attempts[f"{key_prefix}:{symbol}"]
            normalized_attempts.append(attempt)
            try:
                if attempt["error"] is not None:
                    raise ValueError(
                        str(attempt["error"]).strip() or f"{provider} request failed"
                    )
                history = parser(attempt["payload"], cutoff, symbol)
                histories[symbol] = history
                observed_date = max(history)
                value = history[observed_date]
                source = {
                    "sourceId": symbol,
                    "status": "ok",
                    "sourceUrl": source_urls[symbol],
                    "provider": provider,
                    "valueBasis": value_basis,
                    "fetchedAt": attempt["fetchedAt"],
                    "observationDate": observed_date.isoformat(),
                    "value": value,
                }
                source["close" if value_basis == "Close" else "nav"] = value
                sources[symbol] = source
            except (KeyError, IndexError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                normalized_attempts[-1] = {
                    **attempt,
                    "error": exc,
                    "errorType": exc.__class__.__name__,
                }
        if len(histories) != len(CREDIT_SYMBOLS):
            record_credit_failure(stage_id, provider, normalized_attempts)
            return False
        common_dates = sorted(set(histories["HYG"]) & set(histories["LQD"]))
        if len(common_dates) < 6:
            reason = ValueError(f"{provider} HYG/LQD requires at least six common sessions")
            normalized_attempts[0] = {
                **normalized_attempts[0],
                "error": reason,
                "errorType": "ValueError",
            }
            record_credit_failure(stage_id, provider, normalized_attempts)
            return False

        ratio_history = histories
        ratio_sources = sources
        credit_provider = provider
        credit_value_basis = value_basis
        credit_source_urls = dict(source_urls)
        credit_cache_status = "refreshed"
        fetched_at = max(source["fetchedAt"] for source in sources.values())
        credit_attempts.append(
            {
                "sourceId": stage_id,
                "status": "ok",
                "provider": provider,
                "fetchedAt": fetched_at,
                "valueBasis": value_basis,
            }
        )
        _write_credit_cache(
            resolved_cache_path,
            ratio_history,
            fetched_at,
            provider=provider,
            value_basis=value_basis,
            source_urls=credit_source_urls,
        )
        return True

    nasdaq_ok = apply_pair(
        stage_id="NASDAQ_HYG_LQD",
        provider="Nasdaq",
        value_basis="Close",
        source_urls=plan["creditRatio"]["nasdaqHistoryUrls"],
        pair_attempts=attempts,
        parser=_parse_nasdaq_history,
        key_prefix="nasdaq",
    )

    ishares_ok = False
    if not nasdaq_ok:
        if batch_fetch is None:
            unavailable_attempt = {
                "payload": None,
                "fetchedAt": _clock_iso(clock),
                "error": ValueError("iShares byte fetcher is unavailable"),
                "errorType": "ValueError",
                "rateLimited": False,
            }
            ishares_attempts = {
                f"ishares:{symbol}": unavailable_attempt for symbol in CREDIT_SYMBOLS
            }
        else:
            ishares_specs = [
                (f"ishares:{symbol}", plan["creditRatio"]["isharesHistoryUrls"][symbol])
                for symbol in CREDIT_SYMBOLS
            ]
            ishares_attempts: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=len(ishares_specs)) as executor:
                futures = [
                    (key, executor.submit(attempt_fetch, batch_fetch, url))
                    for key, url in ishares_specs
                ]
                for key, future in futures:
                    ishares_attempts[key] = future.result()
        ishares_ok = apply_pair(
            stage_id="ISHARES_HYG_LQD",
            provider="iShares",
            value_basis="NAV",
            source_urls=plan["creditRatio"]["isharesHistoryUrls"],
            pair_attempts=ishares_attempts,
            parser=_parse_ishares_history,
            key_prefix="ishares",
        )

    yahoo_ok = False
    if not nasdaq_ok and not ishares_ok:
        if active_finance_history is not None:
            yahoo_attempt = attempt_fetch(
                lambda _url, active_timeout: active_finance_history(active_timeout),
                "yfinance://HYG,LQD",
            )
            if yahoo_attempt["error"] is None:
                try:
                    histories = _normalize_credit_histories(yahoo_attempt["payload"], cutoff)
                    yahoo_attempts = {
                        f"yfinance:{symbol}": {**yahoo_attempt, "payload": histories[symbol]}
                        for symbol in CREDIT_SYMBOLS
                    }
                    yahoo_ok = apply_pair(
                        stage_id="YAHOO_HYG_LQD",
                        provider="Yahoo Finance via yfinance",
                        value_basis="Close",
                        source_urls=plan["creditRatio"]["yahooHistoryUrls"],
                        pair_attempts=yahoo_attempts,
                        parser=lambda payload, _cutoff, _symbol: payload,
                        key_prefix="yfinance",
                    )
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    yahoo_attempt = {
                        **yahoo_attempt,
                        "error": exc,
                        "errorType": exc.__class__.__name__,
                    }
            if not yahoo_ok and yahoo_attempt["errorType"] != "DependencyBootstrapError":
                record_credit_failure(
                    "YAHOO_HYG_LQD", "Yahoo Finance via yfinance", [yahoo_attempt]
                )
        if active_finance_history is None or (
            not yahoo_ok and yahoo_attempt["errorType"] == "DependencyBootstrapError"
        ):
            yahoo_specs = [
                (f"yahoo:{symbol}", plan["creditRatio"]["yahooHistoryUrls"][symbol])
                for symbol in CREDIT_SYMBOLS
            ]
            yahoo_attempts: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=len(yahoo_specs)) as executor:
                futures = [
                    (key, executor.submit(attempt_fetch, fetch_text, url))
                    for key, url in yahoo_specs
                ]
                for key, future in futures:
                    yahoo_attempts[key] = future.result()
            yahoo_ok = apply_pair(
                stage_id="YAHOO_HYG_LQD",
                provider="Yahoo Finance direct",
                value_basis="Close",
                source_urls=plan["creditRatio"]["yahooHistoryUrls"],
                pair_attempts=yahoo_attempts,
                parser=_parse_yahoo_history,
                key_prefix="yahoo",
            )

    if not nasdaq_ok and not ishares_ok and not yahoo_ok and cached_credit is not None:
        ratio_history = cached_credit["histories"]
        credit_provider = cached_credit["provider"]
        credit_value_basis = cached_credit["valueBasis"]
        credit_source_urls = cached_credit["sourceUrls"]
        credit_cache_status = (
            "fresh-fallback"
            if cached_credit["ageSeconds"] <= CREDIT_CACHE_REFRESH_SECONDS
            else "stale-fallback"
        )
        for symbol, history in ratio_history.items():
            observed_date = max(history)
            value = history[observed_date]
            ratio_sources[symbol] = {
                "sourceId": symbol,
                "status": "ok",
                "sourceUrl": credit_source_urls[symbol],
                "provider": credit_provider,
                "valueBasis": credit_value_basis,
                "fetchedAt": cached_credit["savedAt"],
                "cacheReadAt": started_at,
                "cacheStatus": credit_cache_status,
                "observationDate": observed_date.isoformat(),
                "value": value,
                "close" if credit_value_basis == "Close" else "nav": value,
            }
        credit_attempts.append(
            {
                "sourceId": "CACHE_HYG_LQD",
                "status": "ok",
                "provider": credit_provider,
                "fetchedAt": cached_credit["savedAt"],
                "valueBasis": credit_value_basis,
                "cacheStatus": credit_cache_status,
            }
        )

    missing_ratio = [symbol for symbol in ("HYG", "LQD") if symbol not in ratio_history]
    if missing_ratio:
        credit_ratio = {
            "status": "failed",
            "missingComponents": missing_ratio,
            "sources": ratio_sources,
            "attempts": credit_attempts,
        }
    else:
        common_dates = sorted(set(ratio_history["HYG"]) & set(ratio_history["LQD"]))
        if len(common_dates) < 6:
            reason = "HYG/LQD requires at least six common sessions"
            fetched_at = _clock_iso(clock)
            gaps.append(
                {
                    "sourceId": "HYG/LQD",
                    "status": "failed",
                    "fetchedAt": fetched_at,
                    "reason": reason,
                }
            )
            credit_ratio = {
                "status": "failed",
                "error": reason,
                "sources": ratio_sources,
                "attempts": credit_attempts,
            }
        else:
            ratios = [
                ratio_history["HYG"][day] / ratio_history["LQD"][day]
                for day in common_dates
            ]
            credit_ratio = {
                "status": "ok",
                "cacheStatus": credit_cache_status or "disabled",
                "provider": credit_provider,
                "valueBasis": credit_value_basis,
                "formula": plan["creditRatio"]["formulas"][credit_value_basis],
                "observationDate": common_dates[-1].isoformat(),
                "unit": "ratio",
                "level": ratios[-1],
                "change5SessionsPct": (ratios[-1] / ratios[-6] - 1) * 100,
                "componentValues": {
                    "HYG": ratio_history["HYG"][common_dates[-1]],
                    "LQD": ratio_history["LQD"][common_dates[-1]],
                },
                "sources": ratio_sources,
                "attempts": credit_attempts,
            }
            if credit_value_basis == "Close":
                credit_ratio["componentCloses"] = dict(credit_ratio["componentValues"])

    breadth_history: dict[str, dict[date, float]] = {}
    breadth_sources: dict[str, dict] = {}
    breadth_attempts: list[dict] = []
    breadth_provider: str | None = None
    breadth_value_basis: str | None = None
    breadth_source_urls: dict[str, str] = {}
    breadth_cache_status: str | None = None

    def record_breadth_failure(
        stage_id: str, provider: str, failed_attempts: list[dict]
    ) -> None:
        fetched_at = max((item["fetchedAt"] for item in failed_attempts), default=started_at)
        reasons = [
            str(item["error"]).strip() or f"{provider} request failed"
            for item in failed_attempts
            if item.get("error") is not None
        ]
        entry = {
            "sourceId": stage_id,
            "status": "failed",
            "provider": provider,
            "fetchedAt": fetched_at,
            "reason": "; ".join(dict.fromkeys(reasons)) or f"{provider} pair is incomplete",
            "rateLimited": any(bool(item.get("rateLimited")) for item in failed_attempts),
        }
        breadth_attempts.append(entry)
        gaps.append(entry.copy())

    def apply_breadth_pair(
        *,
        stage_id: str,
        provider: str,
        value_basis: str,
        source_urls: dict[str, str],
        pair_attempts: dict[str, dict],
        parser: Callable[[object, datetime, str], dict[date, float]],
        key_prefix: str,
    ) -> bool:
        nonlocal breadth_history, breadth_sources, breadth_provider
        nonlocal breadth_value_basis, breadth_source_urls, breadth_cache_status
        histories: dict[str, dict[date, float]] = {}
        sources: dict[str, dict] = {}
        normalized_attempts: list[dict] = []
        for symbol in BREADTH_SYMBOLS:
            attempt = pair_attempts[f"{key_prefix}:{symbol}"]
            normalized_attempts.append(attempt)
            try:
                if attempt["error"] is not None:
                    raise ValueError(
                        str(attempt["error"]).strip() or f"{provider} request failed"
                    )
                history = parser(attempt["payload"], cutoff, symbol)
                histories[symbol] = history
                observed_date = max(history)
                sources[symbol] = {
                    "sourceId": symbol,
                    "status": "ok",
                    "sourceUrl": source_urls[symbol],
                    "provider": provider,
                    "valueBasis": value_basis,
                    "fetchedAt": attempt["fetchedAt"],
                    "observationDate": observed_date.isoformat(),
                    "value": history[observed_date],
                }
            except (KeyError, IndexError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                normalized_attempts[-1] = {
                    **attempt,
                    "error": exc,
                    "errorType": exc.__class__.__name__,
                }
        if len(histories) != len(BREADTH_SYMBOLS):
            record_breadth_failure(stage_id, provider, normalized_attempts)
            return False
        common_dates = sorted(set(histories["RSP"]) & set(histories["SPY"]))
        if len(common_dates) < BREADTH_MINIMUM_COMMON_SESSIONS:
            reason = ValueError(
                f"{provider} RSP/SPY requires at least "
                f"{BREADTH_MINIMUM_COMMON_SESSIONS} common sessions"
            )
            normalized_attempts[0] = {
                **normalized_attempts[0],
                "error": reason,
                "errorType": "ValueError",
            }
            record_breadth_failure(stage_id, provider, normalized_attempts)
            return False
        breadth_history = histories
        breadth_sources = sources
        breadth_provider = provider
        breadth_value_basis = value_basis
        breadth_source_urls = dict(source_urls)
        breadth_cache_status = "refreshed"
        fetched_at = max(source["fetchedAt"] for source in sources.values())
        breadth_attempts.append(
            {
                "sourceId": stage_id,
                "status": "ok",
                "provider": provider,
                "fetchedAt": fetched_at,
                "valueBasis": value_basis,
            }
        )
        _write_breadth_cache(
            resolved_cache_path,
            breadth_history,
            fetched_at,
            provider=provider,
            value_basis=value_basis,
            source_urls=breadth_source_urls,
        )
        return True

    breadth_nasdaq_ok = apply_breadth_pair(
        stage_id="NASDAQ_RSP_SPY",
        provider="Nasdaq",
        value_basis="Close",
        source_urls=plan["equityBreadth"]["nasdaqHistoryUrls"],
        pair_attempts=attempts,
        parser=_parse_nasdaq_history,
        key_prefix="breadth-nasdaq",
    )

    breadth_sp_ok = False
    if not breadth_nasdaq_ok:
        if batch_fetch is None:
            unavailable = {
                "payload": None,
                "fetchedAt": _clock_iso(clock),
                "error": ValueError("S&P Global byte fetcher is unavailable"),
                "errorType": "ValueError",
                "rateLimited": False,
            }
            sp_attempts = {
                f"breadth-sp:{symbol}": unavailable for symbol in BREADTH_SYMBOLS
            }
        else:
            sp_specs = [
                (
                    f"breadth-sp:{symbol}",
                    plan["equityBreadth"]["spGlobalHistoryUrls"][symbol],
                )
                for symbol in BREADTH_SYMBOLS
            ]
            sp_attempts: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=len(sp_specs)) as executor:
                futures = [
                    (key, executor.submit(attempt_fetch, batch_fetch, url))
                    for key, url in sp_specs
                ]
                for key, future in futures:
                    sp_attempts[key] = future.result()
        breadth_sp_ok = apply_breadth_pair(
            stage_id="SP_GLOBAL_RSP_SPY",
            provider="S&P Dow Jones Indices",
            value_basis="Price Return Index",
            source_urls=plan["equityBreadth"]["spGlobalHistoryUrls"],
            pair_attempts=sp_attempts,
            parser=_parse_sp_global_history,
            key_prefix="breadth-sp",
        )

    breadth_yahoo_ok = False
    if not breadth_nasdaq_ok and not breadth_sp_ok:
        if active_breadth_finance_history is not None:
            yf_attempt = attempt_fetch(
                lambda _url, active_timeout: active_breadth_finance_history(active_timeout),
                "yfinance://RSP,SPY",
            )
            if yf_attempt["error"] is None:
                try:
                    histories = _normalize_pair_histories(
                        yf_attempt["payload"], cutoff, BREADTH_SYMBOLS, "RSP/SPY"
                    )
                    yf_attempts = {
                        f"breadth-yfinance:{symbol}": {
                            **yf_attempt,
                            "payload": histories[symbol],
                        }
                        for symbol in BREADTH_SYMBOLS
                    }
                    breadth_yahoo_ok = apply_breadth_pair(
                        stage_id="YAHOO_RSP_SPY",
                        provider="Yahoo Finance via yfinance",
                        value_basis="Close",
                        source_urls=plan["equityBreadth"]["yahooHistoryUrls"],
                        pair_attempts=yf_attempts,
                        parser=lambda payload, _cutoff, _symbol: payload,
                        key_prefix="breadth-yfinance",
                    )
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    yf_attempt = {
                        **yf_attempt,
                        "error": exc,
                        "errorType": exc.__class__.__name__,
                    }
            if not breadth_yahoo_ok:
                record_breadth_failure(
                    "YAHOO_RSP_SPY", "Yahoo Finance via yfinance", [yf_attempt]
                )
        if not breadth_yahoo_ok:
            yahoo_specs = [
                (
                    f"breadth-yahoo:{symbol}",
                    plan["equityBreadth"]["yahooHistoryUrls"][symbol],
                )
                for symbol in BREADTH_SYMBOLS
            ]
            yahoo_attempts: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=len(yahoo_specs)) as executor:
                futures = [
                    (key, executor.submit(attempt_fetch, fetch_text, url))
                    for key, url in yahoo_specs
                ]
                for key, future in futures:
                    yahoo_attempts[key] = future.result()
            breadth_yahoo_ok = apply_breadth_pair(
                stage_id="YAHOO_RSP_SPY",
                provider="Yahoo Finance direct",
                value_basis="Close",
                source_urls=plan["equityBreadth"]["yahooHistoryUrls"],
                pair_attempts=yahoo_attempts,
                parser=_parse_yahoo_history,
                key_prefix="breadth-yahoo",
            )

    if (
        not breadth_nasdaq_ok
        and not breadth_sp_ok
        and not breadth_yahoo_ok
        and cached_breadth is not None
    ):
        breadth_history = cached_breadth["histories"]
        breadth_provider = cached_breadth["provider"]
        breadth_value_basis = cached_breadth["valueBasis"]
        breadth_source_urls = cached_breadth["sourceUrls"]
        breadth_cache_status = (
            "fresh-fallback"
            if cached_breadth["ageSeconds"] <= CREDIT_CACHE_REFRESH_SECONDS
            else "stale-fallback"
        )
        for symbol, history in breadth_history.items():
            observed_date = max(history)
            breadth_sources[symbol] = {
                "sourceId": symbol,
                "status": "ok",
                "sourceUrl": breadth_source_urls[symbol],
                "provider": breadth_provider,
                "valueBasis": breadth_value_basis,
                "fetchedAt": cached_breadth["savedAt"],
                "cacheReadAt": started_at,
                "cacheStatus": breadth_cache_status,
                "observationDate": observed_date.isoformat(),
                "value": history[observed_date],
            }
        breadth_attempts.append(
            {
                "sourceId": "CACHE_RSP_SPY",
                "status": "ok",
                "provider": breadth_provider,
                "fetchedAt": cached_breadth["savedAt"],
                "valueBasis": breadth_value_basis,
                "cacheStatus": breadth_cache_status,
            }
        )

    if not all(symbol in breadth_history for symbol in BREADTH_SYMBOLS):
        equity_breadth = {
            "status": "failed",
            "missingComponents": [
                symbol for symbol in BREADTH_SYMBOLS if symbol not in breadth_history
            ],
            "sources": breadth_sources,
            "attempts": breadth_attempts,
        }
    else:
        common_dates = sorted(
            set(breadth_history["RSP"]) & set(breadth_history["SPY"])
        )
        ratios = [
            breadth_history["RSP"][day] / breadth_history["SPY"][day]
            for day in common_dates
        ]
        changes = {
            f"{window}-session": (ratios[-1] / ratios[-window - 1] - 1) * 100
            for window in (1, 5, 20)
        }
        change5 = changes["5-session"]
        direction = "flat"
        if change5 > 1e-12:
            direction = "expanding"
        elif change5 < -1e-12:
            direction = "contracting"
        equity_breadth = {
            "status": "ok",
            "cacheStatus": breadth_cache_status or "disabled",
            "provider": breadth_provider,
            "valueBasis": breadth_value_basis,
            "formula": plan["equityBreadth"]["formulas"][breadth_value_basis],
            "observationDate": common_dates[-1].isoformat(),
            "unit": "ratio",
            "level": ratios[-1],
            "changesPct": changes,
            "direction5Sessions": direction,
            "componentValues": {
                symbol: breadth_history[symbol][common_dates[-1]]
                for symbol in BREADTH_SYMBOLS
            },
            "sources": breadth_sources,
            "attempts": breadth_attempts,
        }

    missing_liquidity = [
        source_id
        for source_id in ("WALCL", "WDTGAL", "RRPONTSYD")
        if source_id not in fred_history
    ]
    if missing_liquidity:
        net_liquidity = {
            "id": "US_NET_LIQUIDITY",
            "status": "failed",
            "missingComponents": missing_liquidity,
            "formula": "WALCL - WDTGAL - (RRPONTSYD * 1000)",
        }
    else:
        liquidity_history: list[tuple[date, float, dict[str, str]]] = []
        for anchor, walcl in fred_history["WALCL"]:
            tga = _latest_as_of(fred_history["WDTGAL"], anchor)
            rrp = _latest_as_of(fred_history["RRPONTSYD"], anchor)
            if tga is None or rrp is None:
                continue
            component_dates = {
                "WALCL": anchor.isoformat(),
                "WDTGAL": tga[0].isoformat(),
                "RRPONTSYD": rrp[0].isoformat(),
            }
            liquidity_history.append(
                (anchor, walcl - tga[1] - (rrp[1] * 1000), component_dates)
            )
        if not liquidity_history:
            net_liquidity = {
                "id": "US_NET_LIQUIDITY",
                "status": "failed",
                "missingComponents": ["as-of-aligned-observations"],
                "formula": "WALCL - WDTGAL - (RRPONTSYD * 1000)",
            }
        else:
            net_liquidity = {
                "id": "US_NET_LIQUIDITY",
                "status": "ok",
                "anchorDate": liquidity_history[-1][0].isoformat(),
                "componentObservationDates": liquidity_history[-1][2],
                "unit": "usd-millions",
                "level": liquidity_history[-1][1],
                "changes": _change_map(
                    [value for _, value, _ in liquidity_history], (1, 4, 13), "anchor"
                ),
                "formula": "WALCL - WDTGAL - (RRPONTSYD * 1000)",
            }

    binance_results: dict[str, dict] = {}
    for source in plan["binance"]:
        symbol = source["symbol"]
        attempt = attempts[f"binance:{symbol}"]
        fetched_at = attempt["fetchedAt"]
        try:
            if attempt["error"] is not None:
                raise ValueError(str(attempt["error"]).strip() or "Binance request failed")
            received_at = parse_utc(fetched_at)
            parsed = _parse_binance_ticker(attempt["payload"], symbol, received_at)
            binance_results[symbol] = {
                "sourceId": symbol,
                "status": "ok",
                "sourceUrl": source["url"],
                "fetchedAt": fetched_at,
                "role": source["role"],
                "market": source["market"],
                "denomination": "USDT",
                **parsed,
            }
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            reason = str(exc).strip() or "market source failed"
            binance_results[symbol] = {
                "sourceId": symbol,
                "status": "failed",
                "sourceUrl": source["url"],
                "fetchedAt": fetched_at,
                "error": reason,
            }
            gaps.append(
                {
                    "sourceId": symbol,
                    "status": "failed",
                    "fetchedAt": fetched_at,
                    "reason": reason,
                }
            )

    return {
        "schemaVersion": 1,
        "cutoff": utc_iso(cutoff),
        "collectionStartedAt": started_at,
        "collectionEndedAt": _clock_iso(clock),
        "fred": fred_results,
        "treasuryYieldCurve": treasury_yield_curve,
        "creditRatio": credit_ratio,
        "equityBreadth": equity_breadth,
        "netLiquidity": net_liquidity,
        "binance": binance_results,
        "dataQuality": {"gaps": gaps},
    }
