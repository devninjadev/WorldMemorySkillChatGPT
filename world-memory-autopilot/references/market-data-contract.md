# Market data contract

## Contents

- Acquisition boundary
- FRED series
- HYG/LQD
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

The plan contains request paths and extraction contracts, not observed values. The collector performs the actual keyless public requests, parses each response independently, records the pass start/end and each source's `fetchedAt`/observation time, computes NFCIRISK changes, HYG/LQD, and U.S. net liquidity, and preserves every success when another source fails. Treat the collector JSON as the acquisition boundary; do not manually downgrade a successful member to a gap or skip a configured member because another failed. A registry, policy, or schema stop that occurs before analysis still blocks these external calls. A silent non-due Run with no event requiring market-reaction evidence need not fetch or store a market snapshot.

The collector attempts all five FRED series, both ETF histories, and all three Binance tickers in one pass. A lagged but valid FRED observation remains usable with its actual date and a lag warning. For net liquidity, use only `netLiquidity.status:"ok"`; when a required component fails, preserve every other successful FRED member and identify only the missing component. Never replace a collector failure with an unattempted or model-invented value.

Distinguish a source failure from an execution-path denial. When a collector member failed because the local shell or sandbox denied outbound network access, that result proves only that path failed. Before creating a source gap, use an available web-research or browser fetch capability on the same exact public URL. For FRED, the official series pages listed below are the mandatory fallback and expose the latest dated observations even when raw CSV download is blocked. Preserve every visible valid observation and compute every supported window; if only the long history is unavailable, record that window as partial rather than calling the whole source missing. Declare the source failed only after both the packaged request and this exact official fallback fail. Do not use a third-party value while an official page is available.

Do not write API keys or credentials. The FRED graph CSV and the three Binance ticker routes are public. Treat finance-history/Yahoo data as market-price evidence, not Federal Reserve evidence.

## FRED series

The collector uses the exact `fred.series[].url` values from the plan. They call `https://fred.stlouisfed.org/graph/fredgraph.csv` with `cosd` and one `id`. It parses `observation_date` and the column named by the series ID, discards blank or `.` values, parses the remainder as finite numbers, sorts by date, and uses only observations on or before the collection cutoff.

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

Retrieve daily `Close` history for `HYG` and `LQD` over three months with no automatic adjustment, matching FinanceAgentGUI's `yfinance.download(..., period="3mo", interval="1d", auto_adjust=False)` contract. When a finance history capability is unavailable, use the plan's exact public `creditRatio.historyUrls` and extract each timestamp with `chart.result[0].indicators.quote[0].close`.

Intersect the two valid trading-date indexes before division. Compute:

```text
ratio_t = HYG Close_t / LQD Close_t
change_5_sessions_pct = (ratio_t / ratio_t-5 - 1) * 100
```

Require at least six common sessions. Retain the common observation date and both component closes. A higher ratio or positive five-session change is evidence of stronger high-yield risk appetite relative to investment grade; it is not a direct credit-spread measurement. Never forward-fill one ETF across a trading date missing from the other.

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

The BTC host is Binance's official market-data-only REST base and requires no API key. Validate the returned `symbol`, parse finite `lastPrice`, `priceChangePercent`, `quoteVolume`, and `count`, and convert `closeTime` from Unix milliseconds to UTC. Retain the local `fetchedAt` separately. Reject a missing/nonpositive price, malformed/future `closeTime`, symbol mismatch, or a quote older than 300 seconds as a current observation.

`priceChangePercent` is a rolling 24-hour change, not a regular-session daily return or prior-settlement change. `CLUSDT` and `XAUUSDT` are Binance TradFi perpetual references; label their basis, funding, venue, liquidity, and USDT risks and never present them as official WTI settlement or official gold spot/fix. `BTCUSDT` is Binance spot and may be used as a direct crypto observation, but retain the USDT denomination and venue.

## Freshness and partial failure

Treat the plan's FRED/ETF `freshnessWarningCalendarDays` as warning thresholds, not fabricated newer observations. A lagged value may be discussed only with its actual observation date. A Binance quote failing its 300-second currentness check is unusable as a current price.

Preserve successful observations when another source fails. Record each failed source, attempt time, and reason in `dataQuality.gaps`; do not turn an unattempted source into a neutral signal. Apply these dependency rules:

- missing `NFCIRISK` does not erase a valid `HYG/LQD`, and vice versa;
- one missing net-liquidity component suppresses the entire derived level and all changes;
- a failed `CLUSDT`, `XAUUSDT`, or `BTCUSDT` request does not suppress the other two;
- do not substitute DXY for `DTWEXBGS`, a crypto perpetual for BTC spot, or another commodity contract without an explicit contract revision.

## Report projection

Whenever a value appears in a Report, include its direct source URL, observed date/time, fetched time, unit/denomination, market type, and change window in the canonical analysis evidence. Put formulas and proxy limitations in `methodology`; keep the Korean radar note to the plain-language interpretation required by the analysis contract.

Only add a data gap after the required bounded attempt failed, returned malformed data, or exceeded the freshness rule. Distinguish `missing`, `lagged`, and `failed` from neutral evidence. Never claim that differently timed weekly, daily, and live observations are simultaneous; call them one collection-window snapshot and expose their individual timestamps.
