# Market data contract

## Contents

- Acquisition boundary
- FRED series
- HYG/LQD
- U.S. equity direction and market breadth
- U.S. net liquidity
- Binance market observations
- Freshness and partial failure
- Report projection

## Acquisition boundary

Before declaring one of these market inputs unavailable, or before using market reaction in a materiality decision or visible Report, generate the exact public-source plan and immediately execute its bounded collector:

```text
PYTHONPATH=<skill-path>/scripts python3 -m world_memory market-data-plan --now UTC
PYTHONPATH=<skill-path>/scripts python3 -m world_memory collect-market-data --now UTC [--timeout SEC]
```

The plan contains request paths and extraction contracts, not observed values. The collector performs the actual keyless public requests, parses each response independently, records the pass start/end and each source's `fetchedAt`/observation time, computes NFCIRISK changes, HYG/LQD, RSP/SPY breadth, and U.S. net liquidity, and preserves every success when another source fails. Treat the collector JSON as the acquisition boundary; do not manually downgrade a successful member to a gap or skip a configured member because another failed. A registry, policy, or schema stop that occurs before analysis still blocks these external calls. A silent non-due Run with no event requiring market-reaction evidence need not fetch or store a market snapshot.

The collector starts the FRED batch, both Nasdaq HYG/LQD histories, both Nasdaq RSP/SPY histories, and all five Binance tickers in one parallel bounded pass. Within either paired-ratio member, request both symbols concurrently at each source tier and advance only when the complete pair is unusable. The timeout is the per-member network ceiling; later tiers add bounded sequential fallback time, while first-use Yahoo dependency bootstrap may add installation time. A lagged but valid FRED observation remains usable with its actual date and a lag warning. For net liquidity, use only `netLiquidity.status:"ok"`; when a required component fails, preserve every other successful FRED member and identify only the missing component. Never replace a collector failure with an unattempted or model-invented value.

Distinguish a source failure from an execution-path denial. When a collector member failed because the local shell or sandbox denied outbound network access, that result proves only that path failed. Before creating a source gap, use an available web-research or browser fetch capability on the same exact public URL. For FRED, the official series pages listed below are the mandatory fallback and expose the latest dated observations even when raw CSV download is blocked. Preserve every visible valid observation and compute every supported window; if only the long history is unavailable, record that window as partial rather than calling the whole source missing. Declare the source failed only after both the packaged request and this exact official fallback fail. Do not use a third-party value while an official page is available.

Do not write API keys or credentials. The FRED graph CSV and the five Binance ticker routes are public. Treat finance-history/Yahoo data as market-price evidence, not Federal Reserve evidence.

## FRED series

The collector uses the plan's exact `fred.batchUrl`, calling `https://fred.stlouisfed.org/graph/fredgraph.csv` with `cosd` and all five comma-separated IDs. FRED returns one ZIP grouped by publication frequency. Parse every CSV member independently, select `observation_date` and the column named by each series ID, discard blank or `.` values, parse the remainder as finite numbers, sort by date, and use only observations on or before the collection cutoff. Preserve the individual `fred.series[].url` values as source and browser-fallback links; do not issue five routine serial graph requests.

| ID | Frequency and unit | Use |
|---|---|---|
| `NFCIRISK` | weekly, ending Friday; index | financial-risk conditions |
| `WALCL` | weekly, Wednesday; USD millions | Fed total assets |
| `WDTGAL` | weekly, Wednesday; USD millions | Treasury General Account |
| `RRPONTSYD` | daily; USD billions | overnight reverse repo |
| `DTWEXBGS` | daily; Jan 2006=100 index | nominal broad U.S. dollar |

For `NFCIRISK`, retain the latest level, observation date, and 1-, 4-, and 13-observation changes. Higher/positive values mean tighter-than-average risk conditions; lower/negative values mean looser-than-average conditions. Do not reverse that sign.

For `DTWEXBGS`, retain the latest level, observation date, and available 1- and 5-session changes. Call it the Fed nominal broad dollar index. It is not ICE DXY and must not be labeled `DXY`.

The series pages are the metadata authority for frequency, units, and release lag:

- `https://fred.stlouisfed.org/series/NFCIRISK`
- `https://fred.stlouisfed.org/series/WALCL`
- `https://fred.stlouisfed.org/series/WDTGAL`
- `https://fred.stlouisfed.org/series/RRPONTSYD`
- `https://fred.stlouisfed.org/series/DTWEXBGS`

## HYG/LQD

Acquire one complete HYG/LQD pair through this exact order; never combine one symbol or value basis from one tier with the other from another tier:

1. Nasdaq public ETF historical endpoints from `creditRatio.nasdaqHistoryUrls`: parse `data.tradesTable.rows[].date` and actual unadjusted `close`. This is the preferred `Close` basis.
2. iShares official fund workbooks from `creditRatio.isharesHistoryUrls`: parse only the `Historical` worksheet's `As Of` and `NAV per Share` columns. This is an official daily `NAV` fallback, not an exchange close. Label the result and formula as NAV and never expose its components as closes.
3. Yahoo Finance: retrieve daily unadjusted `Close` history over three months through yfinance, then use the exact `creditRatio.yahooHistoryUrls` only when yfinance dependency bootstrap itself is unavailable. On first use, check `yfinance`, `pandas`, and `numpy`; if missing, install the pinned requirements into the isolated `.world-memory-runtime/deps` directory with the active interpreter, retry once without the pip cache, prepend that exact directory to `sys.path`, invalidate import caches, and re-import all required modules. Never mutate the system interpreter. Request both symbols concurrently through `Ticker.history(..., raise_errors=True)`. A `YFRateLimitError` is a provider rate limit: do not hammer Yahoo's direct hosts as an immediate retry.
4. Cache: only after all three live tiers fail, use a valid complete paired cache. A cache saved within six hours is `fresh-fallback`; an older cache whose latest common observation is no more than seven calendar days old is `stale-fallback`. Cache never suppresses the live tiers.

Persist the last complete six-session-or-longer live pair in `.world-memory-runtime/market-cache.json`, including provider, `valueBasis`, and both source URLs. A successful live acquisition atomically replaces the cache and is labeled `refreshed`. A future-dated, malformed, partial, schema-mismatched, unsupported-basis, or too-old cache is unusable. Preserve each failed higher tier in `creditRatio.attempts` and `dataQuality.gaps`; retain original observation and fetched times when cache is used.

Intersect the two valid trading-date indexes before division. Compute:

```text
ratio_t = HYG value_t / LQD value_t
change_5_sessions_pct = (ratio_t / ratio_t-5 - 1) * 100
```

Require at least six common sessions. Retain the common observation date, both component values, provider, source URLs, and an exact `valueBasis` of `Close` or `NAV`. Use `HYG Close / LQD Close` only for Nasdaq/Yahoo and `HYG NAV per Share / LQD NAV per Share` only for iShares/cache carrying NAV. A higher ratio or positive five-session change is evidence of stronger high-yield risk appetite relative to investment grade; it is not a direct credit-spread measurement. Never forward-fill one ETF across a trading date missing from the other.

## U.S. equity direction and market breadth

Use `QQQUSDT` and `SPYUSDT` from Binance USDⓈ-M perpetuals as the primary live U.S. growth-equity and large-cap-equity direction proxies. They are 24/7 exchange observations and are preferred for fast repricing, including weekends. They are not official QQQ or SPY ETF closes: retain Binance venue, USDT denomination, perpetual/funding/basis/liquidity caveats, and label `priceChangePercent` as a rolling 24-hour change.

Measure regular-session close-based breadth separately with one complete RSP/SPY pair. Follow exactly: Nasdaq → S&P Dow Jones Indices → Yahoo Finance → cache. At every tier, request both components concurrently and never combine the two legs across providers or value bases:

1. Nasdaq public ETF history: unadjusted `RSP Close / SPY Close`.
2. S&P Dow Jones Indices daily exports: `indexId=370` for the S&P 500 Equal Weight Price Return Index and `indexId=340` for the S&P 500 Price Return Index. Parse the legacy workbook's date and index-level columns and label the basis `Price Return Index`; do not call these ETF closes.
3. Yahoo Finance: unadjusted RSP and SPY `Close` over six months through the isolated yfinance dependency path, with the plan's direct chart URLs as the final live subpath.
4. Cache: only after every live pair fails. Accept only a complete, same-provider pair whose latest common observation is no more than seven calendar days old.

Intersect the two session indexes without forward-filling. Require at least 21 common sessions and compute the level plus 1-, 5-, and 20-session ratio changes. A positive five-session change is `expanding`, a negative change is `contracting`, and an unchanged ratio is `flat`. Treat this as relative breadth, not an advance/decline count. Store it under `equityBreadth`; keep the cache section independent from `creditRatio` so refreshing one pair does not erase the other.

## U.S. net liquidity

The collector uses `WALCL` observation dates as weekly anchors. For each anchor, it selects the last `WDTGAL` and `RRPONTSYD` observation on or before that date; never use a future value. It converts RRP from USD billions to USD millions and computes:

```text
US_NET_LIQUIDITY = WALCL - WDTGAL - (RRPONTSYD * 1000)
```

Retain the anchor date, the actual observation date of every component, the level, and 1-, 4-, and 13-anchor changes. If any component has no valid as-of value, compute no level or change. Do not create a partial, proxy, or neutral substitute.

## Binance market observations

Use these unauthenticated ticker requests from the plan:

| Role | Symbol and market | Endpoint |
|---|---|---|
| oil | `CLUSDT`, USDⓈ-M perpetual | `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=CLUSDT` |
| gold | `XAUUSDT`, USDⓈ-M perpetual | `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=XAUUSDT` |
| BTC | `BTCUSDT`, spot | `https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT` |
| U.S. growth equities | `QQQUSDT`, USDⓈ-M perpetual | `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=QQQUSDT` |
| U.S. large-cap equities | `SPYUSDT`, USDⓈ-M perpetual | `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=SPYUSDT` |

The BTC host is Binance's official market-data-only REST base and requires no API key. Validate the returned `symbol`, parse finite `lastPrice`, `priceChangePercent`, `quoteVolume`, and `count`, and convert `closeTime` from Unix milliseconds to UTC. Record local `fetchedAt` after the response and validate freshness against that response-receipt time, never the earlier feed or integration cutoff. Permit at most two seconds of positive exchange-clock skew; reject a later `closeTime`, a quote older than 300 seconds, a missing/nonpositive price, malformed time, or symbol mismatch. A valid live quote collected after the feed cutoff remains a supplemental market snapshot for the Report and does not enter the feed ledger window.

`priceChangePercent` is a rolling 24-hour change, not a regular-session daily return or prior-settlement change. `CLUSDT`, `XAUUSDT`, `QQQUSDT`, and `SPYUSDT` are Binance TradFi perpetual references; label their basis, funding, venue, liquidity, and USDT risks and never present them as official WTI settlement, official gold spot/fix, or official ETF closes. `BTCUSDT` is Binance spot and may be used as a direct crypto observation, but retain the USDT denomination and venue.

## Freshness and partial failure

Treat the plan's FRED/ETF `freshnessWarningCalendarDays` as warning thresholds, not fabricated newer observations. A lagged value may be discussed only with its actual observation date. A Binance quote failing its 300-second currentness check is unusable as a current price.

Preserve successful observations when another source fails. Record each failed source, attempt time, and reason in `dataQuality.gaps`; do not turn an unattempted source into a neutral signal. Apply these dependency rules:

- missing `NFCIRISK` does not erase a valid `HYG/LQD`, and vice versa;
- one missing net-liquidity component suppresses the entire derived level and all changes;
- a failed Binance ticker does not suppress any other ticker;
- a failed `RSP/SPY` pair does not erase valid `QQQUSDT` or `SPYUSDT` live observations, and live perpetuals never replace the close-based breadth ratio;
- do not substitute DXY for `DTWEXBGS`, a crypto perpetual for BTC spot, or another commodity contract without an explicit contract revision.

## Report projection

Whenever a value appears in a Report, include its direct source URL, observed date/time, fetched time, unit/denomination, market type, and change window in the canonical analysis evidence. Put formulas and proxy limitations in `methodology`; keep the Korean radar note to the plain-language interpretation required by the analysis contract.

Project `QQQUSDT` and `SPYUSDT` into fast direction/repricing commentary only when their observations are current. Project `equityBreadth` as regular-session breadth with its observation date and 1-, 5-, and 20-session changes. Do not repeat unchanged live prices merely to fill an hourly narrative; emphasize a meaningful move, an event reaction, a confirmation/invalidation, or the breadth divergence that changes interpretation.

Only add a data gap after the required bounded attempt failed, returned malformed data, or exceeded the freshness rule. Distinguish `missing`, `lagged`, and `failed` from neutral evidence. Never claim that differently timed weekly, daily, and live observations are simultaneous; call them one collection-window snapshot and expose their individual timestamps.
