"""Deterministic public-source plan and collection for market observations."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
import math
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
)
USER_AGENT = "WorldMemoryAutopilot/2.0 (public market collector)"
FetchText = Callable[[str, float], str]
Clock = Callable[[], datetime]


def _url(base: str, parameters: list[tuple[str, str]]) -> str:
    return f"{base}?{urlencode(parameters)}"


def market_data_plan(now: str) -> dict:
    planned = parse_utc(now)
    start_date = (planned - timedelta(days=180)).date().isoformat()
    fields = ["lastPrice", "priceChangePercent", "closeTime", "quoteVolume", "count"]
    return {
        "schemaVersion": 1,
        "plannedAt": utc_iso(planned),
        "collection": {
            "mode": "single-bounded-pass",
            "binanceWindow": "rolling-24h",
            "recordPerSourceFetchedAt": True,
            "recordObservationAt": True,
        },
        "fred": {
            "auth": "none",
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
        "creditRatio": {
            "provider": "finance-history-or-yfinance",
            "symbols": ["HYG", "LQD"],
            "historyUrls": {
                symbol: _url(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    [
                        ("events", "history"),
                        ("includeAdjustedClose", "true"),
                        ("interval", "1d"),
                        ("range", "3mo"),
                    ],
                )
                for symbol in ("HYG", "LQD")
            },
            "period": "3mo",
            "interval": "1d",
            "priceField": "Close",
            "autoAdjust": False,
            "alignment": "inner-common-session",
            "formula": "HYG Close / LQD Close",
            "change5Sessions": "(ratio_t / ratio_t-5 - 1) * 100",
            "minimumCommonSessions": 6,
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


def _clock_iso(clock: Clock) -> str:
    observed = clock()
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("market collection clock must be timezone-aware")
    return utc_iso(observed.astimezone(timezone.utc))


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
    if age_seconds < 0:
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
    clock: Clock = _utc_now,
) -> dict:
    """Collect every public market source independently and derive stable signals."""

    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    cutoff = parse_utc(now)
    plan = market_data_plan(now)
    started_at = _clock_iso(clock)
    gaps: list[dict] = []
    fred_results: dict[str, dict] = {}
    fred_history: dict[str, list[tuple[date, float]]] = {}

    for source in plan["fred"]["series"]:
        source_id = source["id"]
        fetched_at = _clock_iso(clock)
        try:
            payload = fetch_text(source["url"], timeout)
            observations = _parse_fred_csv(source_id, payload, cutoff)
            fred_history[source_id] = observations
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
    for symbol in plan["creditRatio"]["symbols"]:
        fetched_at = _clock_iso(clock)
        source_url = plan["creditRatio"]["historyUrls"][symbol]
        try:
            payload = fetch_text(source_url, timeout)
            history = _parse_yahoo_history(payload, cutoff, symbol)
            ratio_history[symbol] = history
            observed_date = max(history)
            ratio_sources[symbol] = {
                "sourceId": symbol,
                "status": "ok",
                "sourceUrl": source_url,
                "fetchedAt": fetched_at,
                "observationDate": observed_date.isoformat(),
                "close": history[observed_date],
            }
        except (KeyError, IndexError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            reason = str(exc).strip() or "market source failed"
            ratio_sources[symbol] = {
                "sourceId": symbol,
                "status": "failed",
                "sourceUrl": source_url,
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

    missing_ratio = [symbol for symbol in ("HYG", "LQD") if symbol not in ratio_history]
    if missing_ratio:
        credit_ratio = {
            "status": "failed",
            "missingComponents": missing_ratio,
            "sources": ratio_sources,
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
            credit_ratio = {"status": "failed", "error": reason, "sources": ratio_sources}
        else:
            ratios = [
                ratio_history["HYG"][day] / ratio_history["LQD"][day]
                for day in common_dates
            ]
            credit_ratio = {
                "status": "ok",
                "observationDate": common_dates[-1].isoformat(),
                "unit": "ratio",
                "level": ratios[-1],
                "change5SessionsPct": (ratios[-1] / ratios[-6] - 1) * 100,
                "componentCloses": {
                    "HYG": ratio_history["HYG"][common_dates[-1]],
                    "LQD": ratio_history["LQD"][common_dates[-1]],
                },
                "sources": ratio_sources,
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
        fetched_at = _clock_iso(clock)
        try:
            payload = fetch_text(source["url"], timeout)
            parsed = _parse_binance_ticker(payload, symbol, cutoff)
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
        "creditRatio": credit_ratio,
        "netLiquidity": net_liquidity,
        "binance": binance_results,
        "dataQuality": {"gaps": gaps},
    }
