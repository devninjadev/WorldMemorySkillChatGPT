"""Deterministic public-source plan and collection for market observations."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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
)
USER_AGENT = "WorldMemoryAutopilot/2.0 (public market collector)"
MAX_EXCHANGE_CLOCK_SKEW_SECONDS = 2.0
FetchText = Callable[[str, float], str]
FetchBytes = Callable[[str, float], bytes]
FinanceHistory = Callable[[float], dict[str, dict[date, float]]]
Clock = Callable[[], datetime]
MARKET_CACHE_SCHEMA_VERSION = 1
CREDIT_CACHE_REFRESH_SECONDS = 6 * 60 * 60
CREDIT_CACHE_MAX_OBSERVATION_DAYS = 7


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


def _fetch_bytes(url: str, timeout: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/zip,text/csv;q=0.9,*/*;q=0.1",
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


def _normalize_credit_histories(
    raw_histories: object, cutoff: datetime
) -> dict[str, dict[date, float]]:
    if not isinstance(raw_histories, dict):
        raise ValueError("HYG/LQD history provider returned a non-object")
    normalized: dict[str, dict[date, float]] = {}
    for symbol in ("HYG", "LQD"):
        raw_history = raw_histories.get(symbol)
        if not isinstance(raw_history, dict):
            raise ValueError(f"HYG/LQD history provider is missing {symbol}")
        history: dict[date, float] = {}
        for raw_day, raw_close in raw_history.items():
            observed_day = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
            if observed_day > cutoff.date():
                continue
            close = _finite_number(raw_close, field=f"{symbol} close")
            if close <= 0:
                raise ValueError(f"{symbol} close must be positive")
            history[observed_day] = close
        if not history:
            raise ValueError(f"{symbol} has no close on or before cutoff")
        normalized[symbol] = dict(sorted(history.items()))
    return normalized


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
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_credit_cache(path: Path | None, histories: dict[str, dict[date, float]], saved_at: str) -> None:
    if path is None:
        return
    document = {
        "schemaVersion": MARKET_CACHE_SCHEMA_VERSION,
        "creditRatio": {
            "savedAt": saved_at,
            "histories": {
                symbol: {day.isoformat(): value for day, value in history.items()}
                for symbol, history in histories.items()
            },
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _yfinance_history(timeout: float) -> dict[str, dict[date, float]]:
    from .bootstrap import ensure_runtime_dependencies

    ensure_runtime_dependencies()
    import yfinance as yf

    def fetch_symbol(symbol: str) -> tuple[str, object]:
        frame = yf.Ticker(symbol).history(
            period="3mo",
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
        futures = [executor.submit(fetch_symbol, symbol) for symbol in ("HYG", "LQD")]
        for future in futures:
            symbol, frame = future.result()
            frames[symbol] = frame

    histories: dict[str, dict[date, float]] = {}
    for symbol in ("HYG", "LQD"):
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
    fresh_credit_cache = bool(
        cached_credit
        and cached_credit["ageSeconds"] <= CREDIT_CACHE_REFRESH_SECONDS
    )
    active_finance_history = finance_history
    if active_finance_history is None and fetch_text is _fetch_text:
        active_finance_history = _yfinance_history
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
    if not fresh_credit_cache:
        if active_finance_history is not None:
            request_specs.append(
                (
                    "credit:history",
                    lambda _url, active_timeout: active_finance_history(active_timeout),
                    "yfinance://HYG,LQD",
                )
            )
        else:
            request_specs.extend(
                (f"yahoo:{symbol}", fetch_text, plan["creditRatio"]["historyUrls"][symbol])
                for symbol in plan["creditRatio"]["symbols"]
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

    def apply_credit_cache(status: str) -> None:
        nonlocal credit_cache_status
        if cached_credit is None:
            raise ValueError("credit cache is unavailable")
        credit_cache_status = status
        ratio_history.update(cached_credit["histories"])
        for symbol, history in cached_credit["histories"].items():
            observed_date = max(history)
            ratio_sources[symbol] = {
                "sourceId": symbol,
                "status": "ok",
                "sourceUrl": plan["creditRatio"]["historyUrls"][symbol],
                "fetchedAt": cached_credit["savedAt"],
                "cacheReadAt": started_at,
                "cacheStatus": status,
                "observationDate": observed_date.isoformat(),
                "close": history[observed_date],
            }

    def apply_direct_yahoo(direct_attempts: dict[str, dict]) -> None:
        nonlocal credit_cache_status, ratio_history
        ratio_history = {}
        for symbol in plan["creditRatio"]["symbols"]:
            source_url = plan["creditRatio"]["historyUrls"][symbol]
            attempt = direct_attempts[f"yahoo:{symbol}"]
            fetched_at = attempt["fetchedAt"]
            try:
                if attempt["error"] is not None:
                    raise ValueError(str(attempt["error"]).strip() or "Yahoo request failed")
                history = _parse_yahoo_history(attempt["payload"], cutoff, symbol)
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
        if len(ratio_history) == 2:
            credit_cache_status = "refreshed"
            _write_credit_cache(
                resolved_cache_path,
                ratio_history,
                max(ratio_sources["HYG"]["fetchedAt"], ratio_sources["LQD"]["fetchedAt"]),
            )
        elif cached_credit is not None:
            apply_credit_cache("stale-fallback")

    if fresh_credit_cache:
        apply_credit_cache("fresh-hit")
    elif active_finance_history is not None:
        attempt = attempts["credit:history"]
        if attempt["error"] is None:
            try:
                ratio_history = _normalize_credit_histories(attempt["payload"], cutoff)
                credit_cache_status = "refreshed"
                for symbol, history in ratio_history.items():
                    observed_date = max(history)
                    ratio_sources[symbol] = {
                        "sourceId": symbol,
                        "status": "ok",
                        "sourceUrl": plan["creditRatio"]["historyUrls"][symbol],
                        "provider": "Yahoo Finance via yfinance",
                        "fetchedAt": attempt["fetchedAt"],
                        "cacheStatus": credit_cache_status,
                        "observationDate": observed_date.isoformat(),
                        "close": history[observed_date],
                    }
                _write_credit_cache(resolved_cache_path, ratio_history, attempt["fetchedAt"])
            except (KeyError, OSError, TypeError, ValueError) as exc:
                attempt = {
                    **attempt,
                    "error": exc,
                    "errorType": exc.__class__.__name__,
                    "rateLimited": False,
                }
        if attempt["error"] is not None:
            if attempt["errorType"] == "DependencyBootstrapError":
                fallback_specs = [
                    (f"yahoo:{symbol}", plan["creditRatio"]["historyUrls"][symbol])
                    for symbol in plan["creditRatio"]["symbols"]
                ]
                fallback_attempts: dict[str, dict] = {}
                with ThreadPoolExecutor(max_workers=len(fallback_specs)) as executor:
                    fallback_futures = [
                        (key, executor.submit(attempt_fetch, fetch_text, url))
                        for key, url in fallback_specs
                    ]
                    for key, future in fallback_futures:
                        fallback_attempts[key] = future.result()
                apply_direct_yahoo(fallback_attempts)
                if len(ratio_history) == 2:
                    attempt = {**attempt, "error": None}
        if attempt["error"] is not None:
            reason = str(attempt["error"]).strip() or "Yahoo history provider failed"
            if cached_credit is not None:
                apply_credit_cache("stale-fallback")
                gaps.append(
                    {
                        "sourceId": "YAHOO_HYG_LQD",
                        "status": "degraded",
                        "fetchedAt": attempt["fetchedAt"],
                        "reason": reason,
                        "errorType": attempt["errorType"],
                        "rateLimited": attempt["rateLimited"],
                    }
                )
            else:
                for symbol in plan["creditRatio"]["symbols"]:
                    source_url = plan["creditRatio"]["historyUrls"][symbol]
                    ratio_sources[symbol] = {
                        "sourceId": symbol,
                        "status": "failed",
                        "sourceUrl": source_url,
                        "fetchedAt": attempt["fetchedAt"],
                        "error": reason,
                        "errorType": attempt["errorType"],
                        "rateLimited": attempt["rateLimited"],
                    }
                    gaps.append(
                        {
                            "sourceId": symbol,
                            "status": "failed",
                            "fetchedAt": attempt["fetchedAt"],
                            "reason": reason,
                            "errorType": attempt["errorType"],
                            "rateLimited": attempt["rateLimited"],
                        }
                    )
    else:
        apply_direct_yahoo(attempts)

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
                "cacheStatus": credit_cache_status or "disabled",
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
        "creditRatio": credit_ratio,
        "netLiquidity": net_liquidity,
        "binance": binance_results,
        "dataQuality": {"gaps": gaps},
    }
