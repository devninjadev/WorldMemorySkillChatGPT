# Analysis contract

## Contents

- Material change
- Brief selection and importance
- Cross-asset pulse and data gaps
- Six-hour synthesis and Report v2
- Korean output contracts
- Autopilot allowlist and permission boundary

## Material change

Set `material_change=true` only when verified evidence satisfies at least one gate:

1. An independently cross-confirmed `high`-importance event occurred.
2. An event changes an active state or the base, upside, or downside scenario.
3. Multiple independent sources and a meaningful market reaction confirm the same development.
4. A policy, geopolitical, or corporate event requires a verification or response decision within the next 1–3 hours.

The four gates are independent alternatives. Urgency is not the default or dominant gate. A verified event may be material without requiring action in the next 1–3 hours when another gate is satisfied. Treat the fourth gate as an escalation and notification horizon, not as the definition of durable World Memory importance.

Do not invent numeric price, yield, spread, volatility, or news-count thresholds. Judge materiality from the verified event, transmission path, reaction, and decision horizon. A FEED headline alone does not satisfy a gate.

Material change is the hourly visibility decision, not the durable Memory admission decision. First select verified durable briefs, then connect them to prior current Memory, then decide whether an accumulated state changes, and only then decide notification urgency. A scheduled non-due Run may create verified brief Memory revisions while keeping `Material Change=false`, `Notification Plan=silent`, and no Report when none of the four gates is satisfied.

For a scheduled Run with no gate and no due six-hour report, use notification plan `silent`. A successful due or forced six-hour report is always user-visible even when no hourly material change exists.

## Brief selection and importance

Allow only `high|medium|low`. Select meaningful briefs rather than filling a word or item quota. Prefer 3–8 briefs when that many qualify, but do not pad to three. Keep the same subject to at most two briefs per Run. Balance policy actors, companies, institutions, and industries; compress duplicate headlines into one durable brief.

Judge importance from the event's reach, persistence, transmission path, and whether it strengthens, weakens, or changes an existing state, story, or scenario. Immediate actionability affects notification priority but is not required for brief inclusion.

Record each verified durable event as a brief before considering state or story mutations. A state represents an accumulated regime or active interpretation, not a substitute for the event brief. Create or supersede a state only when verified evidence establishes or changes that accumulated condition. A story-link relates two existing story endpoints; never use it as a substitute for a brief or create it when either endpoint does not exist. Connect each selected brief to prior current Memory when a verified semantic relationship exists, and keep it separate when no truthful relationship exists.

Shape each brief payload with `dedupe_key`, verified `sources`, the required event schema, and at least one semantic anchor from `subjects`, `industries`, or `event_kind`. Do not require all three anchors. Do not create a derived state merely because a brief exists.

Treat an earnings event as at least `medium`. Treat a strong beat/miss, surprise/shock, or guidance raise/cut as `high`. Classify an earnings brief under `stock_bond`, not `emerging`.

## Cross-asset pulse and data gaps

Cover available evidence for equities, market breadth, volatility, rates, credit, the U.S. dollar, oil, gold, and BTC. Connect each event to its transmission path, observed asset response, and confirming or invalidating condition. Never invent a missing market value.

Before treating `NFCIRISK`, `HYG/LQD`, `WALCL`, `WDTGAL`, `RRPONTSYD`, `DTWEXBGS`, `CLUSDT`, `XAUUSDT`, or spot `BTCUSDT` as unavailable, follow the market-data contract: generate the exact packaged public-source plan and execute `PYTHONPATH=<skill-path>/scripts python3 -m world_memory collect-market-data --now UTC [--timeout SEC]`. The plan alone is not an attempt. Use every collector member with `status:"ok"`, including valid lagged FRED observations with their actual dates. A shell/sandbox network denial is not source unavailability: attempt the contract's exact official web/browser fallback, retain every dated observation it exposes, and mark only an unsupported change window as partial. Create a source gap only after both acquisition paths fail. Preserve each actual observation time and fetched time; weekly, daily, and live values form one collection-window snapshot, not one simultaneous timestamp.

Keep these two `signalRadar` axes separate:

- `신용·금융여건`: evaluate NFCIRISK and HYG/LQD. Do not mix U.S. net-liquidity components into this score.
- `미국 순유동성`: evaluate the available `WALCL − TGA − RRP` level and its 1-, 4-, and 13-week changes. Do not treat credit conditions as a substitute.

If any net-liquidity component is missing or `n/a`, do not compute a partial, proxy, synthetic, or neutral estimate. Name every missing component in the note and `dataQuality.gaps`, lower confidence, and represent the axis without a numeric score (`score:null`) or omit the scored signal when the output schema permits. Do not use `50` or another neutral value. For any missing cross-asset input, mark the data gap and distinguish unavailable data from neutral evidence.

Use `DTWEXBGS` only as the Fed nominal broad U.S. dollar index, never as ICE DXY. Use `CLUSDT` and `XAUUSDT` as Binance USDⓈ-M perpetual references with venue/basis/funding caveats, not official WTI settlement or official gold spot/fix. Use `BTCUSDT` from Binance spot and retain its USDT denomination. Binance `priceChangePercent` is a rolling 24-hour change, never a regular-session daily return.

Keep each radar note to one or two plain-language Korean interpretation sentences. Put formulas, scope, and score direction in `methodology`, not the note.

## Six-hour synthesis and Report v2

Use committed Feed Batch items with canonical `fetchedAt` in `(previous committed integration cutoff, current collection cutoff]`, prior current committed Memory revisions, prior committed Reports, current verified sources, and available market data. Items after the cutoff remain for the next integration. Exclude every child whose parent Run is not committed.

Explain what changed since the previous Report, the causal transmission path, observed or expected asset response, counterevidence, and the next verification point. Express portfolio actions as conditional observation, confirmation, sizing, or hedge considerations, not unsupported buy/sell commands.

Store the structured result as the canonical payload of one `WM Reports` child with `schemaVersion:2`. Both `hourly-briefing` and `six-hour` canonical Report payloads use the complete Report-v2 shape below and must return an empty error list from the packaged `world_memory.contracts.validate_report` function before encoding or child creation. There is no `validate-report` CLI subcommand. A six-hour Report has `Report Type="six-hour"`, its trigger-independent `Integration Key`, `User Visible=true`, evidence relations to committed Memory revisions, and a separate Korean rendering after the canonical payload block. The canonical payload is authoritative; the rendering must agree with it.

Report payloads may carry additional analysis/domain top-level fields. The exact forbidden storage-owned Report payload key set is `{runKey, reportKey, integrationKey, materialChange, userVisible, evidenceRecords, coverageStart, coverageEnd, collectionCutoff, notificationPlan}`. Reject any payload containing a member of that set; accept other analysis/domain extras when the required Report-v2 shape and semantic validation pass.

The canonical Report payload has no `runKey`; bind it through the physical Report key, scalar `Run Key`, exact `Run` relation, and fetched parent Run. Project properties deterministically: `As Of = payload.asOf = Coverage End = parent Collection Cutoff`; stance/confidence come from the payload; `Data Gap Count` is the length of `dataQuality.gaps`; and `Material Change` comes from the parent. For a non-genesis six-hour Report, `Coverage Start` is the prior cutoff encoded in the Integration Key. Genesis/hourly start is empty or canonical UTC and, when present, no later than the end.

The direct Report validator also binds the Report type to the fresh parent projection. A `six-hour` Report requires parent `Integration Due=true`, `Integration Performed=true`, `Notification Plan=six-hour`, a nonempty matching canonical Integration Key, and visibility true. An `hourly-briefing` Report requires parent `Integration Due=false`, `Integration Performed=false`, `Material Change=true`, `Notification Plan=hourly-briefing`, empty parent/Report Integration Keys, and visibility true. These booleans and projection fields are type-strict; no payload self-claim substitutes for the parent. At precommit, the exact inventory matrix is one six-hour and no hourly when integration is performed, one hourly and no six-hour for material non-integration, and no Report with `silent` for nonmaterial non-integration.

Every visible Report requires nonempty Korean rendering whose digest and claims match the canonical payload. Resolve each ordered UUID in `Evidence Records` uniquely to either a current expected Memory child under the same parent or a prior committed Memory row. Never cite Memory under another preparing, failed, or superseded Run. An empty evidence relation is valid only when no Memory record truthfully supports the Report.

Every Report-v2 payload has all of these top-level fields:

```json
{
  "schemaVersion": 2,
  "title": "...",
  "asOf": "2026-08-10T00:00:00Z",
  "coverage": "...",
  "dataQuality": {"gaps": []},
  "stance": "neutral",
  "confidence": 0.5,
  "summary": "...",
  "narrative": "...",
  "changesSincePrevious": [],
  "signalRadar": [],
  "highlights": [],
  "memoryChangeSuggestions": [],
  "portfolioSuggestions": [],
  "nextChecks": [],
  "sources": [],
  "scenarios": {
    "기준": {"activation":"...","transmission":"...","invalidation":"...","nextCheck":"..."},
    "낙관": {"activation":"...","transmission":"...","invalidation":"...","nextCheck":"..."},
    "비관": {"activation":"...","transmission":"...","invalidation":"...","nextCheck":"..."}
  }
}
```

`title`, `asOf`, `coverage`, `summary`, and `narrative` are strings; `asOf` is empty or canonical UTC ISO 8601. `dataQuality` is an object with a required `gaps` list whose members are strings. `stance` is `risk-on|neutral|defensive|mixed`. `confidence` is a non-boolean number from 0 through 1. Each of `changesSincePrevious`, `signalRadar`, `highlights`, `memoryChangeSuggestions`, `portfolioSuggestions`, and `nextChecks` is a list; every member is an object containing at least one nonempty string-valued field. If such a member has `score`, it is numeric or null, never boolean. `sources` is a list; every member is an object with nonempty string `name` and `url`, and an optional numeric-or-null non-boolean `score`. Also retain the direct publication time required by the evidence contract when it is available. Empty lists are valid when evidence supports no members.

Run the packaged function for each hourly and six-hour payload, for example from a JSON file:

```bash
PYTHONPATH=<skill-path>/scripts python3 - REPORT.json <<'PY'
import json
import sys
from world_memory.contracts import validate_report

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
errors = validate_report(report)
if errors:
    raise ValueError(errors)
PY
```

Require `scenarios` to have exactly `기준`, `낙관`, and `비관`. Each scenario has these four nonempty string fields:

```json
{
  "activation": "관측 가능한 활성화 조건",
  "transmission": "예상 전달 경로와 자산 영향",
  "invalidation": "무효화 조건",
  "nextCheck": "다음 확인 지점"
}
```

Do not assign unsupported probabilities. Keep `signalRadar` and `highlights` to at most eight each. Keep `portfolioSuggestions` and `nextChecks` to at most six each.

## Korean output contracts

Render a material hourly briefing in Korean with these sections, in order:

1. `한 줄 판단`
2. `새로운 중요 발전` — at most five
3. `교차자산 펄스`
4. `영향 자산·티커`
5. `확인·무효화 조건`
6. `다음 확인 지점`
7. `출처`

Render every successful six-hour report in Korean with these sections, in order:

1. `한 줄 판단`
2. `현재 해석`
3. `직전 대비 변화`
4. `신호 레이더`
5. `핵심 발전`
6. `기준·낙관·비관 시나리오`
7. `월드 메모리 변경 제안`
8. `포트폴리오·관찰 제안`
9. `다음 확인 지점`
10. `출처와 데이터 공백`

Do not expose internal IDs, commands, or connector mechanics in the user rendering. Write `Notification Plan` before commit, then return the prepared rendering only after committed-Run confirmation and cache reconciliation attempt. Do not claim that delivery was observed.

## Autopilot allowlist and permission boundary

Allow only these Memory mutations:

- `brief-add`
- `state-add`
- `state-supersede`
- `story-link`
- `taxonomy-refresh`
- `suggestion-status-update`

Allow only `investigate` as a read-only action. Require a nonempty `target` for every action. Reject every other action, arbitrary shell/file mutation, deletion, and writes outside the registered `WM Installations`, `WM Runs`, `WM Feed Batches`, `WM Memory`, and `WM Reports` data sources.

For an allowed Memory write, require canonical payload subset `schemaVersion:2`, `kind:"memory"`, `recordType`, `action`, nonempty `target`, list `evidence`, non-boolean `confidence` from 0 through 1, and a present JSON `result`, plus the record-type stable/domain field. Do not invent an inner `result` schema. Map record type to action exactly: `brief -> brief-add`, `state -> state-add|state-supersede`, `story-link -> story-link`, `taxonomy -> taxonomy-refresh`, and `suggestion -> suggestion-status-update`. `investigate` never creates Memory.

Every supplied stable identity component must contain at least one non-whitespace character. Reject whitespace-only `dedupe_key`, `state_key`, `continuityId`, suggestion fallback `action`/`target`, `story_key`, or endpoint; preserve their nonblank bytes without trimming or whitespace collapsing before hashing. Every evidence/domain-source entry has a nonempty name and a parsed absolute HTTP(S) URL with a host, no literal whitespace/control character, and no invalid host/port parse. Independently validate the physical optional projections: `Importance` is empty or `high|medium|low`; `Category` is empty or `stock_bond|geopolitics|emerging`; `Region` is empty or `US|KR|GLOBAL`; `Effective At` is empty or canonical second-precision UTC. When the corresponding payload field is present, bind its value to the physical property type-sensitively; absence never permits an invalid physical value.

Memory payloads may carry additional record-type/domain top-level fields. The exact forbidden storage-owned Memory payload key set is `{runKey, recordKey, revisionKey, revision, supersedes, verifiedEvidence, payloadDigest, bodyFormat, pageId, createdAt, updatedAt}`. Reject any payload containing a member of that set; accept other record-type/domain extras when the required Memory subset and semantic validation pass.

Normalize suggestion status to `open|watching|completed`. Treat every model proposal as untrusted: a proposal field such as `mutationSucceeded` is never execution evidence. Keep a read-only investigation `watching`. Mark `completed` only after the caller supplies observed authoritative success from one of the six allowed mutations. Never complete a failed change. Require nonempty verified evidence for brief/state writes; reject a state with empty evidence/domain sources or `Verified Evidence=false`. Bind action, target, confidence, stable-derived Record Key, dedupe/continuity fields, and predecessor relation to the canonical payload and committed revision chain before commit.

Obey the policy categories independently: `schemaMutation`, `childMutation`, `cacheMutation`, `memoryMutation`, and `completeSuggestions`. `Autopilot Enabled=false` makes the last two false while an active enabled Run may still collect, analyze, create Run/Feed Batch/Report children, and reconcile cache. Disabled/paused/error direct invocations are read-only; blocked scheduled invocations make every mutation false. Require verified sources before a state mutation and record action, target, evidence, confidence, and result in the Run audit and canonical Memory payload.
