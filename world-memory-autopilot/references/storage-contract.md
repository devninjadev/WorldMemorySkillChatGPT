# Storage contract

## Contents

- Fixed installation identity and registry
- Explicit live initialization and partial recovery
- Operational Installation validation and adapter boundary
- Exact database schemas, relations, and views
- Notion serialization and canonical page bodies
- Source-by-source queries and committed authority
- Policy, slots, attempts, and stale recovery
- Child physical and logical identities
- Feed checkpoints and integration range
- Read-back and precommit snapshots
- Commit, cache reconciliation, notification, and failures

## Fixed installation identity and registry

For a Notion workspace ID `<workspace_id>`, derive:

```text
Installation Key = wm:<workspace_id>:default
installation-hash12 = first 12 lowercase hex characters of SHA-256(UTF-8 Installation Key)
Hub title = World Memory Hub · <installation-hash12>
```

The Hub body begins with a section containing these exact marker lines:

```text
WM_BOOTSTRAP_KEY: wm:<workspace_id>:default
WM_SCHEMA_VERSION: 2
```

The Hub is a standalone workspace-private root page. Accept a bootstrap candidate only when its fetched object exposes the workspace-root parent (`parent={"type":"workspace","workspace":true}`) and `public_url=null`, or connector-equivalent explicit not-published evidence. Any candidate carrying part of the identity but not the complete identity is a partial identity conflict, never evidence of zero: this includes an exact-title-only page, a marker-only page, either single marker, or a root/private candidate with a corrupt/missing title or marker. A matching title or marker under another page/database/data source, a public candidate, or an unobservable root/publication state is also an integrity conflict or verification blocker, not a zero-match result. Ranked or semantic search order, highlights, and an empty result are not proofs of exhaustive absence.

The Hub has exactly these registered database roles and titles:

| Registry key | Database title |
|---|---|
| `installations` | `WM Installations` |
| `runs` | `WM Runs` |
| `feed_batches` | `WM Feed Batches` |
| `memory` | `WM Memory` |
| `reports` | `WM Reports` |

Require this exact World Memory registry shape. Reject missing or extra keys at every level:

```json
{
  "world_memory": {
    "skill": "world-memory-autopilot",
    "installation_key": "wm:<workspace_id>:default",
    "notion_workspace_id": "<workspace-uuid>",
    "hub_page_id": "<hub-page-uuid>",
    "hub_url": "https://...",
    "schema_version": 2,
    "skill_contract_version": "notion-v2",
    "bootstrap_allowed": false,
    "scheduled_schema_mutation_allowed": false,
    "data_sources": {
      "installations": {"database_id":"<uuid>","data_source_id":"<uuid>","url":"https://..."},
      "runs": {"database_id":"<uuid>","data_source_id":"<uuid>","url":"https://..."},
      "feed_batches": {"database_id":"<uuid>","data_source_id":"<uuid>","url":"https://..."},
      "memory": {"database_id":"<uuid>","data_source_id":"<uuid>","url":"https://..."},
      "reports": {"database_id":"<uuid>","data_source_id":"<uuid>","url":"https://..."}
    }
  }
}
```

Every ID parses as a UUID; every URL is nonempty HTTP(S); `installation_key` is derived from `notion_workspace_id`; Notion `self` must report the same workspace. The two mutation flags remain exactly false after setup. Never infer, translate, or invent an opaque ID.

At the start of every operational invocation, first run the local packaged validator as `PYTHONPATH=<skill-path>/scripts python3 -m world_memory validate-registry PATH|-`. Never execute or report this as the bare `validate-registry` subcommand. This first step reads only the supplied registry; it does not call Notion. An absent or invalid registry stops a scheduled invocation immediately after that local result: do not read the source or analysis contracts, call Notion `self`, read a schema, collect a FEED, or make any other external call. Only a valid registry permits registry-directed Notion `self` and referenced-schema reads. A scheduled invocation with a missing Installation or schema/relation drift performs zero collection and zero Notion mutation. It returns the exact policy error and never initializes or repairs anything. The separately user-approved no-registry initialization below is the sole exception: it uses deterministic workspace discovery to create/recover the registry and can never be entered by a scheduled invocation.

## Explicit live initialization and partial recovery

Initialization is a separate user-approved live action, never a scheduled-run side effect. Before any mutation, perform this step 0:

- Fetch Notion `self`, observe the workspace ID, and derive the Installation identity from that observation.
- Inspect current tool access and require these semantic capabilities: `search`, `fetch`, `create_pages`, `create_database`, `update_data_source`, `query_data_sources`, `update_page`, and `create_view`.
- Fetch the exact resource `notion://docs/enhanced-markdown-spec` and use it for subsequent page bodies.

If `self`, the workspace ID, any required capability, or that exact specification is unavailable, stop with zero mutation. Do not substitute similarly named capabilities or a remembered Markdown contract.

Use this deterministic recovery sequence:

1. Search the workspace separately for the exact Hub title and exact bootstrap marker. Fetch the union of every candidate; accept only a page whose title, both body marker lines, workspace-root parent, and explicit not-published observation match exactly. Search highlights and result ranking are discovery hints only.
2. First classify every title/marker candidate. Any exact-title-only, marker-only, one-marker, corrupt-marker, wrong-location, public, or unobservable-root/publication candidate is a partial identity/integrity conflict and blocks setup; never discard it to manufacture a zero. Classify accepted Hubs as exact 0/1/N only when the connector surface can establish that result and no partial conflict exists. On proven 0, create one standalone workspace-private Hub and re-run discovery; on 1, reuse it; on N, stop without selecting or merging. If exact absence or uniqueness cannot be established, stop before creation.
3. Fetch the Hub children. For each exact database title, classify 0/1/N. A duplicate title is an integrity conflict; do not create beside it.
4. Acquire `WM Installations` first. If its database is absent, create it from the exact base DDL below; after an uncertain create response, re-fetch the Hub title set before considering another create.
5. Query `WM Installations` by exact `Installation Key`. On 0 rows, create one `initializing` row and requery the key. On 1, reuse it. On N, stop. An uncertain row-create response is resolved only by this same 0/1/N requery.
6. Create only the missing remaining databases from their exact base DDL. After every uncertain response, re-fetch the Hub children before retrying.
7. Fetch every data source ID. Add relations in dependency order using exactly one missing `ADD COLUMN` statement per update call. Re-fetch and validate that data source after every statement before applying the next. Never send a multi-statement relation repair.
8. Re-fetch all five schemas and compare property names, types, SELECT options, relation targets, DUAL inverse names, and one-way relations exactly. Create the exact views only after schema validation.
9. Verify Hub markers, row round-trip, canonical body round-trip, and relations. Query and fully validate committed integration Runs before testing the clock. With no committed cutoff, do not seed a fictional success/cache time or suppress due: use the user-approved explicit-setup path to commit one ordinary `manual` genesis integration with its Feed Batch, evidence-supported Memory revisions, one schema-v2 six-hour Report with Korean rendering, and cache-reconciliation attempt. Its `Collection Cutoff` becomes the authoritative anchor. If partial setup already has exactly one valid committed genesis integration, reuse it; zero after an uncertain response requires requery, while duplicate, ambiguous, or invalid anchors stop setup. Then run the original three checks in order: (a) a later `manual` Run while the packaged gate reports not due, which commits Feed Batch only and no six-hour Report; (b) a later direct minute-slot Run over the identical captured FEED input, which commits `newItemCount=0`; (c) a `force-world-memory` Run before the ordinary six-hour due time, which integrates the committed range under the prior-cutoff Integration Key, creates verified Memory revisions when evidence permits, and creates one schema-v2 six-hour Report with Korean rendering. Each Run uses the ordinary post-create, read-back, precommit, commit-confirmation, and cache rules. A truly fresh installation therefore has four committed verification Runs. On partial reentry, credit only already committed Runs whose complete audit, children, relations, bodies, digests, and snapshots prove the relevant check, then continue at the first missing check. Change the Installation from `initializing` to `active` only after the anchor, all three later checks, and every structural verification succeed.
10. Emit the real registry. Leave `bootstrap_allowed:false` and `scheduled_schema_mutation_allowed:false`. Render it with `PYTHONPATH=<skill-path>/scripts python3 -m world_memory render-scheduled-prompt PATH|-`, install the returned self-contained automation prompt verbatim, and verify that its embedded `<world_memory_registry>` block matches the validated registry before enabling the hourly automation.

The initial Installation values are:

```text
Name=wm:<workspace_id>:default
Status=initializing
Enabled=true
Autopilot Enabled=true
Timezone=Asia/Seoul
Hourly Interval Minutes=60
World Memory Interval Hours=6
Schema Version=2
Skill Contract Version=notion-v2
Feed Cursor State={}
```

Set `Name` and `Installation Key` to the same exact derived Installation Key. Set its `Hub Page ID` and `Hub URL` from observed objects. Do not use search order as identity.

## Operational Installation validation and adapter boundary

Before reusing the singleton Installation or passing it to policy, gate, Run binding, or cache reconciliation, preserve and validate this complete flattened Notion projection:

```text
page_id, Name, Installation Key, Hub Page ID, Hub URL, Status, Enabled,
Autopilot Enabled, Timezone, Hourly Interval Minutes, World Memory Interval Hours,
Schema Version, Skill Contract Version, Feed Cursor State, Last Feed Attempt,
Last Feed Success, Last World Memory Success, Last Report Success,
Next World Memory At, Last Briefing At, Last Error, Created At, Updated At
```

Require `page_id`, `Hub Page ID`, and the registry IDs to be observed UUIDs. Require `Name` and `Installation Key` to equal the registry-derived Installation Key and require `Hub Page ID`/`Hub URL` to equal the validated registry and Hub observation. Require an exact declared `Status`, exact booleans for both checkboxes, `Timezone=Asia/Seoul`, non-boolean integer values `60`, `6`, and `2` for the two intervals and schema version, and `Skill Contract Version=notion-v2`. Dates are empty or canonical UTC; observed system `Created At`/`Updated At` are canonical UTC; `Last Error` is a string. The inverse DUAL `Runs` relation, when returned, is optional and nonauthoritative and is never used to prove singleton identity or completeness.

At the raw Notion adapter boundary, require `Feed Cursor State` to be canonical compact JSON RICH_TEXT for an ordinary normalized row. It decodes to an object containing only configured feed IDs, with each value empty or lowercase 64-hex; `{}` is valid before any committed source cursor exists. Pure policy, gate, and cache functions receive normalized values and never parse raw RICH_TEXT. Before writing any normalized Installation cache, run `PYTHONPATH=<skill-path>/scripts python3 -m world_memory serialize-installation-cache PATH|-` and apply the returned property values exactly. This adapter sorts cursor object keys, emits compact UTF-8 JSON, flattens nonempty DATE values, and emits a null DATE start to clear an empty cache date; never substitute a hand-written or insertion-order serialization. A missing, extra, malformed, mismatched, or type-changed identity/configuration field is a conflict, not a partial row that can grant mutation rights.

Singleton reuse and ordinary policy/mutation require the raw Installation validator to return zero errors and the normalized row validator to pass; never silently accept malformed advisory serialization as a valid operational row. Separately, damaged cursor/date/error cache cannot override committed Run authority. When identity/configuration is valid and only advisory cache serialization is damaged, explicit authority/reconciliation recovery functions may compute the committed cutoff, reconstruct a normalized repair baseline from the complete committed projection, rewrite the cache, and re-read it. That recovery does not grant schema/child/Memory mutation. Ordinary mutation resumes only after the full raw row is canonical again.

### Explicit status-only Run supersession

This is a direct, exceptional ledger repair and is never available to `scheduled`, normal `manual`, normal `force-world-memory`, initialization, stale recovery, or automatic cache reconciliation. It requires explicit user approval for the exact observed Run. Do not discover a replacement Hub, change schema, create a Run or child, delete a page, edit a child, rewrite the Run body, or infer missing evidence.

Before mutation, build the exact repair bundle and run `PYTHONPATH=<skill-path>/scripts python3 -m world_memory plan-run-supersession PATH|-`. Continue only when it returns `action:"supersede-run"` and a single `propertyUpdates:{"Status":"superseded"}`. The planner requires all of these facts simultaneously:

- `invocation=manual`, `explicitApproval=true`, and one fully valid identity/configuration Installation;
- exactly one matching Slot row, one exact Run Key row, and one exact target member in the complete Run authority projection;
- target `Status=committed`, nonempty canonical `Finished At`, `Integration Key=""`, `Material Change=false`, `Integration Due=false`, `Integration Performed=false`, `Output Prepared=true`, `Cache Reconciled=false`, and `Notification Plan=silent`;
- one single-part Feed Batch child, no Memory child, no Report child, and a valid canonical Run audit whose inventory and feed facts exactly bind that child;
- the Feed Batch body, digest, relation, keys, counts, outcomes, and all properties are valid except for exactly one `Fetched At` mismatch: the physical property equals the parent `Collection Cutoff`, while the canonical payload carries a different valid `fetchedAt`;
- no later `preparing` or `committed` Run in `(Collection Cutoff, Run Key)` order.

Any absent, extra, duplicate, malformed, changed, or differently corrupted fact blocks repair. Do not broaden the exception or attempt another fix.

Apply only `Status=superseded` to the exact target page. Re-fetch the Run and its Feed Batch. `verify_run_supersession_readback` must confirm that the Run changed only `Status` plus Notion's system `Updated At`, that the page ID and every other Run field/body stayed exact, and that the Feed Batch snapshot stayed byte-for-byte equivalent. Never revert a confirmed supersession if a later step fails.

After successful read-back, call `reconstruct_installation_cache(current, authoritative_runs)` with the complete Run projection, including noncommitted rows for duplicate/status validation and validated five-source outcomes for every remaining committed Run. This recovery starts cursor replay from `{}`; it does not inherit any current cursor or cache timestamp. Serialize the complete normalized result through `serialize-installation-cache`, apply only those returned cache properties, and re-read both raw and normalized Installation forms. Resume a paused automation only after the Run/Feed read-back, reconstructed cache, canonical raw serialization, normalized Installation, registry, schemas, and relations all pass. If any check fails, leave the automation paused and report the policy error.

## Exact database schemas, relations, and views

Create the base databases without relations using these exact DDL statements. `PYTHONPATH=<skill-path>/scripts python3 -m world_memory schema` is the executable source of the same strings.

### `WM Installations`

```sql
CREATE TABLE (
"Name" TITLE, "Installation Key" RICH_TEXT, "Hub Page ID" RICH_TEXT,
"Hub URL" URL, "Status" SELECT('initializing':yellow, 'active':green, 'paused':gray, 'error':red),
"Enabled" CHECKBOX, "Autopilot Enabled" CHECKBOX, "Timezone" SELECT('Asia/Seoul':blue),
"Hourly Interval Minutes" NUMBER, "World Memory Interval Hours" NUMBER,
"Schema Version" NUMBER, "Skill Contract Version" RICH_TEXT, "Feed Cursor State" RICH_TEXT,
"Last Feed Attempt" DATE, "Last Feed Success" DATE, "Last World Memory Success" DATE,
"Last Report Success" DATE, "Next World Memory At" DATE, "Last Briefing At" DATE,
"Last Error" RICH_TEXT, "Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)
```

### `WM Runs`

```sql
CREATE TABLE (
"Name" TITLE, "Slot Key" RICH_TEXT, "Run Key" RICH_TEXT, "Integration Key" RICH_TEXT, "Attempt" NUMBER,
"Trigger" SELECT('scheduled':blue, 'manual':green, 'force-world-memory':orange),
"Status" SELECT('preparing':yellow, 'committed':green, 'failed':red, 'superseded':gray),
"Started At" DATE, "Scheduled Slot" DATE, "Collection Cutoff" DATE, "Finished At" DATE,
"Feed Success Count" NUMBER, "Feed Failure Count" NUMBER, "New Item Count" NUMBER,
"Material Change" CHECKBOX, "Integration Due" CHECKBOX, "Integration Performed" CHECKBOX,
"Output Prepared" CHECKBOX, "Cache Reconciled" CHECKBOX,
"Notification Plan" SELECT('silent':gray, 'hourly-briefing':blue, 'six-hour':purple, 'error':red),
"Input Digest" RICH_TEXT, "Output Digest" RICH_TEXT, "Error Summary" RICH_TEXT,
"Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)
```

### `WM Feed Batches`

```sql
CREATE TABLE (
"Name" TITLE, "Batch Key" RICH_TEXT, "Run Key" RICH_TEXT, "Payload Digest" RICH_TEXT,
"Fingerprint Window Digest" RICH_TEXT, "Body Format" RICH_TEXT,
"Part Index" NUMBER, "Part Count" NUMBER, "Feed Success Count" NUMBER,
"Feed Failure Count" NUMBER, "New Item Count" NUMBER, "Item Count" NUMBER,
"Fetched At" DATE, "All Sources Failed" CHECKBOX, "Created At" CREATED_TIME)
```

### `WM Memory`

```sql
CREATE TABLE (
"Name" TITLE, "Record Key" RICH_TEXT, "Revision Key" RICH_TEXT, "Run Key" RICH_TEXT,
"Dedupe Key" RICH_TEXT, "Continuity ID" RICH_TEXT, "Target" RICH_TEXT,
"Payload Digest" RICH_TEXT, "Body Format" RICH_TEXT,
"Record Type" SELECT('brief':blue, 'state':purple, 'story-link':green, 'taxonomy':orange, 'suggestion':yellow),
"Record Status" SELECT('active':green, 'open':yellow, 'watching':blue, 'completed':gray),
"Importance" SELECT('high':red, 'medium':yellow, 'low':gray),
"Category" SELECT('stock_bond':blue, 'geopolitics':red, 'emerging':purple),
"Region" SELECT('US':blue, 'KR':green, 'GLOBAL':purple),
"Action" SELECT('brief-add':blue, 'state-add':green, 'state-supersede':orange,
'story-link':purple, 'taxonomy-refresh':yellow, 'suggestion-status-update':gray, 'investigate':default),
"Revision" NUMBER, "Confidence" NUMBER, "Effective At" DATE,
"Verified Evidence" CHECKBOX, "Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)
```

### `WM Reports`

```sql
CREATE TABLE (
"Name" TITLE, "Report Key" RICH_TEXT, "Run Key" RICH_TEXT, "Integration Key" RICH_TEXT, "Payload Digest" RICH_TEXT,
"Rendering Digest" RICH_TEXT, "Body Format" RICH_TEXT,
"Report Type" SELECT('hourly-briefing':blue, 'six-hour':purple),
"As Of" DATE, "Coverage Start" DATE, "Coverage End" DATE,
"Stance" SELECT('risk-on':green, 'neutral':gray, 'defensive':red, 'mixed':yellow),
"Confidence" NUMBER, "Data Gap Count" NUMBER, "Material Change" CHECKBOX,
"User Visible" CHECKBOX, "Created At" CREATED_TIME)
```

After all five data sources exist, recover relations with these exact independent statements, substituting observed data source UUIDs:

| Target source | One update statement |
|---|---|
| `runs` | `ADD COLUMN "Installation" RELATION('<installations-id>', DUAL 'Runs')` |
| `feed_batches` | `ADD COLUMN "Run" RELATION('<runs-id>', DUAL 'Feed Batches')` |
| `memory` | `ADD COLUMN "Run" RELATION('<runs-id>', DUAL 'Memory Records')` |
| `memory` | `ADD COLUMN "Supersedes" RELATION('<memory-id>')` |
| `reports` | `ADD COLUMN "Run" RELATION('<runs-id>', DUAL 'Reports')` |
| `reports` | `ADD COLUMN "Evidence Records" RELATION('<memory-id>')` |

`Supersedes` and `Evidence Records` are one-way. Do not create a reverse DUAL property for either. Do not add Rollups. The DUAL statements automatically create `Installations.Runs`, `Runs.Feed Batches`, `Runs.Memory Records`, and `Runs.Reports`.

Create only these table views, with `type:"table"` and the exact filter/sort DSL shown:

- Installations `Active`: `FILTER "Status" = "active"`
- Runs `Recent`: `SORT BY "Started At" DESC`
- Runs `Failures`: `FILTER "Status" = "failed"; SORT BY "Started At" DESC`
- Feed Batches `Recent`: `SORT BY "Fetched At" DESC`
- Memory `Recent Revisions`: `SORT BY "Effective At" DESC`
- Reports `Latest`: `SORT BY "As Of" DESC`

## Notion serialization and canonical page bodies

Use the actual TITLE property name `Name` when creating a page. Serialize properties exactly:

- DATE: for a nonempty value, `date:<Property>:start=<canonical UTC>` plus `date:<Property>:is_datetime=1`; to clear an empty cache date, `date:<Property>:start=null` with no `is_datetime` key
- CHECKBOX true: `__YES__`; CHECKBOX false: `__NO__`
- RELATION: an array of observed related page IDs only; never serialize a page URL as a relation value
- NUMBER: a JavaScript number; never a string or boolean
- RICH_TEXT, URL, and SELECT: their exact string values
- page body: enhanced Markdown written in the exact `wm-body-v2` form below; accept `wm-body-v1` only when reading an existing page

For every relation round-trip and every fresh read-back, compare the exact ordered page-ID array against the preserved expected page IDs. A URL, missing/extra ID, duplicate ID, or reordered array is a mismatch; do not normalize any of those observations into equality.

Canonical JSON uses UTF-8, `ensure_ascii=false`, sorted object keys, compact separators, and `allow_nan=false`. Reject non-string object keys, non-JSON objects, nonfinite numbers, invalid UTF-8, and timezone-naive timestamps. `Payload Digest` is the lowercase SHA-256 of those canonical bytes.

Every newly written child body begins exactly with this block. The final line is the canonical UTF-8 JSON itself, not Base64, so Notion and model searches can see titles, entities, and URLs:

````text
## Canonical Payload
```text
wm-body-v2
sha256:<lowercase payload digest>
<canonical JSON>
```
````

A Report may append only:

```markdown
## Korean Rendering
<Korean Markdown>
```

Reject rendering before the canonical block, a rendering section without content, or trailing content without that exact header. For `wm-body-v2`, parse the raw JSON, canonicalize it again, and compare the exact bytes, embedded digest, and `Payload Digest`. For an existing `wm-body-v1` page, decode its 76-column Base64 payload and apply the same canonical-byte and digest checks. Never write a new `wm-body-v1` page. For Reports, `Rendering Digest` is the lowercase SHA-256 of the Korean Markdown UTF-8 bytes alone.

The final Feed Batch wrapper has these exact base keys:

```text
schemaVersion, kind, runKey, batchKey, partIndex, partCount,
fetchedAt, newItemCount, sourceOutcomes, items
```

Only part 1 adds `fingerprintWindow`. Require `schemaVersion:2`, `kind:"feed-batch"`, canonical UTC `fetchedAt`, a non-boolean nonnegative integer `newItemCount`, and the configured-order five-source outcomes from the source contract. Every `items` member is a normalized FEED item with `schemaVersion:1`, belongs to a source whose outcome is `ok`, has `fetchedAt` equal to the wrapper time, and satisfies canonical `publishedAt <= fetchedAt`. Derive and cross-check every Feed Batch property from the canonical payload. Set part 1 `Fingerprint Window Digest` to `canonical_digest(fingerprintWindow)` and set that property to the empty string on every later part.

A complete part group repeats identical `fetchedAt`, `newItemCount`, and `sourceOutcomes`; has exact contiguous parts `1..Part Count`; and has a unique item total equal to `newItemCount`. Across the whole multipart group, the unique item count for each feed is at most that successful outcome's observed `itemCount`, and the total is at most the sum of all successful outcome counts. Outcome `itemCount` is the observed collection count and need not equal the retained new-item count. A committable group has five exact outcomes, success plus failure equal to five, at least one success, `All Sources Failed=false`, and at least part 1 even when `newItemCount=0`. The all-five-failed path has no Feed Batch wrapper or child at all.

Cross-bind the validated complete multipart group to its parent Run and canonical audit. Parent Run `Feed Success Count` equals the number of `ok` outcomes, `Feed Failure Count` equals the number of `error` outcomes, and `New Item Count` equals the group's shared `newItemCount` and complete-group unique item total. The `audit.feed required subset` is exactly `sourceOutcomes`, `successCount`, `failureCount`, and `newItemCount`; other feed audit fields remain allowed. Its outcomes are the same configured-order five exact objects, and its non-boolean integer counts are derived from them and equal the parent/group values type-sensitively. Never accept mutually consistent child parts whose parent or audit records different facts. In the all-five-failed exception, the failed parent/audit records success `0`, failure `5`, new items `0`, and the five observed `error` outcomes, but there is no child group or precommit path.

A Report canonical payload uses `schemaVersion:2` and the analysis contract. Its optional Korean rendering is separate from its structured payload.

## Source-by-source queries and committed authority

Never use a cross-data-source SQL join, Rollup, or Installation relation aggregate as an integrity decision. Query one registered data source at a time, then fetch related pages and application-join by observed page ID.

Apply this authority filter before every selection:

1. Query the child source for candidate rows.
2. Fetch each candidate's exact `Run` relation.
3. Keep the child only if that parent exists uniquely and has `Status=committed`.
4. Validate the child's key, relation, canonical body, digest, and properties before use.

This applies to fingerprint checkpoints, integration inputs, current Memory revisions, evidence relations, Reports, due gates, and cache reconstruction. Children under `preparing`, `failed`, or `superseded` Runs remain nonauthoritative even when their own fields are valid. Do not delete them.

`WM Runs.Status=committed` is the authoritative marker. `WM Installations` success times, next time, cursors, and last error are eventual best-effort cache fields. Gate and cursor decisions always read committed Runs and committed Feed Batch outcomes. The six-hour gate never falls back to `Last World Memory Success`: when the validated projection has no unique committed `Integration Performed=true` Run, the effective cutoff is the exact empty string and genesis is due regardless of cache contents. Duplicate committed logical Integration Keys are corruption, never a reason to choose one cutoff.

## Policy, slots, attempts, and stale recovery

Use the packaged policy result exactly. Its permission keys are `schemaMutation`, `childMutation`, `cacheMutation`, `memoryMutation`, and `completeSuggestions`.

Every policy result has exactly these keys:

```text
action, reason, run, collect, analyze, schemaMutation, childMutation,
cacheMutation, memoryMutation, completeSuggestions, notification
```

For a scheduled invalid registry, return `action:"setup-required"`, `reason:"registry-invalid"`, `notification:"error"`, and false for `run`, `collect`, `analyze`, and every mutation. A missing Installation uses `reason:"installation-missing"`; a non-explicit initializing row uses `reason:"initializing"`. This is an error result, not silence, but it performs no Notion or FEED work. Paused/disabled scheduled results use `action:"silent-noop"` and `notification:"silent"`. Stored-error scheduled results use `action:"stored-error"` and `notification:"error"`.

For the scheduled `registry-invalid` case, render exactly: `월드 메모리 설정이 필요합니다. 예약 본문에 유효한 World Memory 레지스트리가 없어 이번 예약 실행을 중단했습니다. 초기화·복구·수집·변경은 수행하지 않았습니다.` Do not replace this error with silence or an approval request.

| Condition | Scheduled | Direct manual/force |
|---|---|---|
| Registry invalid or Installation missing | setup-required error; no reads beyond validation, no mutation | setup-required error; no mutation |
| `initializing` | setup-required error; no mutation | only user-approved `explicit_setup` may validate/write; otherwise setup-required |
| `Enabled=false` | silent no-op | read-only, disabled result |
| `Status=paused` | silent no-op | read-only, disabled result |
| `Status=error` | stored error; no mutation | read-only, error result |
| active, enabled | run | run |
| active with `Autopilot Enabled=false` | Run/Feed Batch/Report/cache allowed; Memory/completion blocked | same |

Schema mutation is false for every operational invocation. Explicit live initialization owns schema changes outside this policy.

Derive Slot Keys as:

```text
wms_<installation-hash12>_<trigger>_<slot-utc>
```

- `scheduled`: floor actual job start UTC to the hour, `YYYYMMDDTHH0000Z`
- `manual|force-world-memory`: floor actual start UTC to the minute, `YYYYMMDDTHHmm00Z`

A delayed scheduled invocation belongs to its actual start-hour slot. Direct invocations in the same minute intentionally coalesce. The physical Run Key is `<slot-key>_a<attempt-3digits>`, with attempts 001 through 999.

Before a Run can participate in Slot resolution, authority, or precommit, bind its observed fields to the validated Installation and invocation. Require an observed UUID `page_id`; `Installation=[<validated Installation page_id>]`; canonical second-precision `Started At` no later than the observation time; `Scheduled Slot` equal to the trigger-specific UTC floor of `Started At`; `Slot Key=slot_key(Installation Key, Trigger, Started At)`; a non-boolean integer `Attempt`; and `Run Key=run_key(Slot Key, Attempt)`. A nonempty `Integration Key` must carry the same Installation hash12. Preserve `Name` as an observed, type-sensitive snapshot value; do not invent a `Name == Run Key` rule. Missing/defaulted fields, a future `Started At`, a URL in the Installation relation, or a key derived from another Installation is a conflict.

Query the Slot Key before creation and validate each row structurally. Detect a duplicate exact Run Key before applying status precedence:

- Any exact Run Key with 2 or more rows is an integrity conflict, regardless of statuses.
- Exactly one committed Run and only failed/superseded companions reuses the committed result; do not create another Run.
- A committed Run mixed with any preparing Run is a conflict; do not reuse, terminalize, or create.
- Two or more committed Runs are a conflict; never choose a winner.
- Any fresh preparing Run blocks a new attempt. Return in-progress/conflict and do not adopt its children.
- With no committed or preparing Run, create `max(existing Attempt)+1`.

The child 0/1/N resolution below is available only after Slot resolution authorizes the current preparing Run, either as a newly created singleton or a valid stale resume. A fresh preparing Run left by another invocation does not become resumable merely because its child query returns 0 or 1; it still blocks every new attempt and commit.

After creating a preparing Run, requery its exact Run Key. Continue only on exactly one row with the expected page ID and snapshot. On zero after an uncertain create, requery before considering another create. On two or more, commit none.

A singleton preparing Run becomes stale only when the current observed time is at least 65 minutes after that Run's own observed canonical `Started At`. Never infer its `Started At` from the current invocation time, Slot, `Created At`, or another timestamp; an absent or malformed value is an integrity conflict, not evidence of freshness or staleness. Fetch a provably stale singleton and its expected child set:

- Resume from precommit only when `Output Prepared=true` and every expected child is complete, unique, related, and valid.
- Otherwise first re-confirm that no committed Run exists, record the error, terminalize the stale Run as `failed`, confirm the terminal state by fetch, requery the Slot, and only then create the next attempt.
- Never automatically resume or terminalize multiple preparing Runs.

Confirmed collection, body, digest, relation, revision, or precommit failures should terminalize their Run as `failed` when safe. If an update response is uncertain, fetch the Run and confirm its terminal state before taking another action.

## Child physical and logical identities

Query every exact physical key immediately before create and immediately after create:

- 0 matches before create permits one create; an uncertain response returns to the exact query.
- 1 match permits reuse only when page ID, parent relation, exact properties, canonical body, and digests equal the preserved expected snapshot.
- 2 or more matches block the parent Run from commit. Do not select, merge, or delete.

Every reused or newly created child has an observed UUID `page_id`, an exact one-element `Run=[<parent page_id>]` relation, and a scalar `Run Key` equal to the fetched parent Run's `Run Key`. The Feed Batch canonical payload also has that exact `runKey`. Report-v2 and Memory payloads do not gain an invented `runKey` field; their parent binding comes from the physical key, scalar property, exact relation, and fetched parent snapshot.

### Feed Batch

```text
Batch Key = <run-key>:feed:<part-index-3digits>
```

Sort new items deterministically by fingerprint and split into at most 100 items per part. When at least one source succeeded, even zero new items creates part 1. The all-five-failed exception creates no child page. `Part Index` starts at 1, and all parts record the same Run Key, part count, fetched time, new count, and source outcomes.

### Reports and Integration

The six-hour logical Integration Key is independent of trigger and Slot. Its suffix is either the literal `genesis` when no committed integration cutoff exists, or the literal prefix `previous-cutoff-` followed by the prior cutoff converted to compact UTC:

```text
no prior cutoff: wmi_<installation-hash12>_genesis
prior cutoff 2026-08-10T00:00:00Z: wmi_<installation-hash12>_previous-cutoff-20260810T000000Z
```

The suffix uses the latest committed `Integration Performed=true` Run's collection cutoff; report-only committed Runs do not advance it. Compute the provisional due result and Integration Key from the latest committed cutoff observed before Run creation, and record them on a due or forced preparing Run. Immediately after Run create, query Runs by that key and fetch every owner. If the only owner is the exact current preparing Run, the identity is stable. If exactly one other owner has newly become committed, with no fresh preparing or ambiguous mixture, fetch and fully validate it, recompute the authoritative latest cutoff, due result, and Integration Key, and update the still-preparing current Run before creating integration children or setting `Output Prepared=true`. When the recomputed non-force Run is no longer due, clear its Integration Key and set both `Integration Due` and `Integration Performed` false; when still due or forced, replace the provisional key and gate/audit expectations with the recomputed values. Requery the Slot, exact Run Key, and recomputed Integration Key and repeat until the observed cutoff and current preparing snapshot are stable. A force bypasses only the clock.

A fresh competing preparing owner, multiple newly committed owners, or any preparing/committed mixture whose single authoritative cutoff cannot be proven is an integrity conflict; do not choose a winner. This post-create stabilization is the only committed-owner recomputation window. Immediately before commit, query the final Integration Key again: any other preparing or committed owner blocks commit, including a newly committed owner. Never rebase prepared children at precommit.

Physical Report keys are:

```text
hourly: <run-key>:report:hourly
six-hour: <integration-key>:report:six-hour:<run-key>
```

The six-hour logical Report identity is `Integration Key`. Before commit, query `WM Reports` by that key and fetch every parent Run. Ignore only rows under failed/superseded parents; any other preparing/committed page besides the current expected page blocks commit. A failed attempt's physical Report does not block a later attempt.

Validate every Report projection against its canonical payload and fetched parent Run; the Report-v2 payload itself has no `runKey`. Require `As Of = payload.asOf = Coverage End = parent Collection Cutoff`, `Stance=payload.stance`, `Confidence=payload.confidence`, `Data Gap Count=len(payload.dataQuality.gaps)`, and `Material Change=parent Material Change`. A non-genesis six-hour `Coverage Start` is exactly the prior cutoff encoded by the Integration Key. Genesis/hourly `Coverage Start` is present as empty or canonical UTC and, when nonempty, is no later than `Coverage End`; freeze the observed value without inventing a payload field.

The storage boundary allows additional Report analysis/domain top-level fields. The exact forbidden storage-owned Report payload key set is `{runKey, reportKey, integrationKey, materialChange, userVisible, evidenceRecords, coverageStart, coverageEnd, collectionCutoff, notificationPlan}`. Reject any payload containing a member of that set; do not treat another analysis/domain extra as a storage-owned claim.

A six-hour Report has its parent's nonempty Integration Key, `Report Type=six-hour`, and `User Visible=true`. An hourly Report has empty Integration Key and also has `User Visible=true`. Every successful active scheduled non-integration Run creates exactly one hourly Report even when `Material Change=false`; a direct non-integration Run creates one only when `Material Change=true`. The scheduled hourly Report is a cumulative full-size view over the latest committed integration cutoff through the current collection cutoff, not a delta-only alert. Every visible Report has nonempty Korean rendering after the canonical block and a matching rendering digest; an empty, stale, or payload-contradicting rendering is invalid. `Evidence Records` is an exact ordered unique UUID page-ID array. Each ID resolves uniquely either to a current expected Memory child under this same parent or to a previously committed Memory row; a row under another preparing/failed/superseded parent is not evidence. An empty evidence array is allowed when no Memory record truthfully supports the Report.

### Memory revisions

Derive `Record Key` as `wmrec_<record-type>_<hash18>`, where `hash18` is the first 18 lowercase hex characters of SHA-256 over UTF-8 `record type + "\n" + stable identity`.

| Record type | Stable identity |
|---|---|
| `brief` | `dedupe_key` |
| `state` | `state_key` |
| `suggestion` | existing `continuityId`; otherwise `action + "\n" + target` |
| `taxonomy` | literal `world-memory-taxonomy` |
| `story-link` | `story_key`; otherwise the two endpoint keys sorted deterministically |

Every supplied stable identity component must be a string with at least one non-whitespace character. This applies to `dedupe_key`, `state_key`, `continuityId`, suggestion fallback `action` and `target`, `story_key`, and both endpoint keys. Reject whitespace-only components; preserve their nonblank bytes without trimming or whitespace collapsing before hashing. Do not create a revision without its required stable identity. The physical Revision Key is:

```text
<record-key>:r<revision-6digits>:<run-key>
```

The logical identity is `(Record Key, Revision)`. Select current Memory only after the committed-parent filter, then require one unique maximum Revision per Record Key. First revision is 1 with no predecessor. Revision n may have exactly one one-way `Supersedes` relation to the unique committed n-1 page of the same Record Key. Reject duplicate committed logical identities, gaps, cycles, another Record Key predecessor, or a wrong relation direction. Never mutate a predecessor to point to an uncommitted successor.

Before commit, query both the physical Revision Key and `(Record Key, Revision)`, fetch parent Runs, and ignore only rows under failed/superseded parents. Any other preparing/committed logical peer besides the current expected page blocks commit. Thus a failed attempt's physical revision cannot hide or block the prior committed current revision, while a concurrent preparing successor cannot commit twice.

Every Memory canonical payload contains this required subset plus the stable/domain field needed for its record type:

```text
schemaVersion=2, kind="memory", recordType, action, target,
evidence, confidence, result
```

Require nonempty string `target`, list `evidence`, non-boolean numeric `confidence` in `[0,1]`, and a present JSON `result`; do not invent an inner `result` schema. Map actions exactly: `brief -> brief-add`, `state -> state-add|state-supersede`, `story-link -> story-link`, `taxonomy -> taxonomy-refresh`, and `suggestion -> suggestion-status-update`. `investigate` is read-only and creates no Memory child. Recompute `Record Key` from the type-specific stable identity and type-sensitively bind payload record type/action/target/confidence, `Dedupe Key`, and `Continuity ID` to properties; optional identity values are the exact payload value or the empty string, never an inferred substitute.

The storage boundary allows additional Memory record-type/domain top-level fields. The exact forbidden storage-owned Memory payload key set is `{runKey, recordKey, revisionKey, revision, supersedes, verifiedEvidence, payloadDigest, bodyFormat, pageId, createdAt, updatedAt}`. Reject any payload containing a member of that set; do not treat another record-type/domain extra as a storage-owned claim.

Require a brief to have nonempty valid evidence and `Verified Evidence=true`. Require a state to have the same valid evidence plus a separate nonempty valid domain-source list and `Verified Evidence=true`. Validate evidence and domain sources independently against their contracts; do not require those two lists to be exactly equal in membership or order. Each entry has a nonempty string `name` and a parsed absolute HTTP(S) URL with a host; reject a missing host, literal whitespace/control character, malformed URL, or invalid host/port parse. Nonsuggestion records have `Record Status=active`; suggestions use only `open|watching|completed`. `completed` is valid only after the caller supplies observed authoritative success from an allowed mutation; a payload's own success claim is not execution evidence.

Validate optional Memory properties even when the payload omits the corresponding field: `Importance is empty or high|medium|low`, `Category` is empty or `stock_bond|geopolitics|emerging`, `Region` is empty or `US|KR|GLOBAL`, and `Effective At` is empty or canonical second-precision UTC. If `importance`, `category`, `region`, or `effectiveAt` is present in the payload, require type-sensitive exact equality to its property. Payload omission never legalizes an out-of-domain physical value. Revision 1 has `Supersedes=[]`. Revision n>1 has exactly one ordered UUID relation to the unique committed n-1 page of the same Record Key; a preparing/failed/superseded row, another Record Key, a gap, cycle, or arbitrary singleton cannot serve as predecessor.

## Feed checkpoints and integration range

Follow the source contract for normalization and configured outcomes. A Feed Batch part-1 checkpoint retains the latest 2,000 exact `{sourceFingerprint,publishedAt}` entries sorted by `(publishedAt,sourceFingerprint)`.

For a new collection, source-by-source query checkpoint and recent-batch rows and pass `checkpoint_rows` as full Feed row snapshots, never detached payloads. Each candidate has the exact full Feed field set, observed UUID `page_id`, one exact `Run=[<page-id>]` relation, observed `Created At`, and verified canonical body/payload/property digests; its fetched parent must be committed before body corruption is authoritative. A multipart checkpoint is authoritative only when every contiguous part of its same-parent Run Key is present and the complete group validates; standalone part 1 is insufficient when `Part Count>1`.

Use the inclusive `[now-12h, now]` horizon for checkpoint/group observation times. Union every valid committed complete checkpoint group in that horizon with every valid complete committed batch item in the same horizon. If the horizon contains no valid checkpoint, find the maximum valid pre-horizon `fetchedAt`, union all co-latest pre-horizon groups at that timestamp, and ignore every older group. Never choose just one recent branch or break a maximum-timestamp tie. Across the authoritative checkpoint and recent-batch inputs, enforce global checkpoint/batch Feed page-ID uniqueness; any repeated UUID is corruption and contributes no window authority. Rebuild malformed or missing state from valid committed groups and record `fingerprint-window-rebuilt` as a data gap.

One fingerprint may collapse identical duplicate observations only when their `publishedAt` values agree; the same fingerprint with conflicting timestamps is corruption. A checkpoint/window fingerprint with `publishedAt > now`, a checkpoint/group with `fetchedAt > now`, a malformed/incomplete group, or a bad body/digest is invalid. Raw-source clock-skew handling occurs before durable normalization and cannot bypass these stored invariants. For each complete multipart group, recompute the expected next window from the retained prior observations plus items from every part, then sort and apply the latest-2,000 cap. Part 1's `fingerprintWindow` and digest must equal that complete-group result; validating closure against part 1 items alone is insufficient.

During a six-hour integration, select complete valid committed Feed Batch groups whose canonical `fetchedAt` lies in:

```text
(latest committed integration Collection Cutoff, current Collection Cutoff]
```

Validate the complete group before applying the cutoff; a mismatched property timestamp is corruption, not a reason to omit the group. Deduplicate again by full fingerprint. A processed duplicate wins over pending. Later groups remain physically present for the next integration.

For every scheduled non-integration Report, use the same cumulative range start but do not mark items processed and do not advance integration authority. Select complete valid committed Feed Batch groups after the latest committed integration cutoff, add the current Run's complete verified Feed Batch group, cap the range at the current `Collection Cutoff`, and deduplicate by full fingerprint. Combine that cumulative feed evidence with prior current committed Memory. Only an `Integration Performed=true` Run may create Memory revisions or complete suggestions.

Partial FEED failure may commit successful-source items and the failed outcome. Preserve the failed source's prior cursor and last error. If all five sources fail, record all five attempt/error outcomes only in the failed Run audit and `Error Summary`, create no Feed Batch, Memory, or Report child page, and terminalize the Run as `failed`. Do not change Installation `Last Feed Attempt`, `Last Feed Success`, cursor state, integration/report success times, or any other cache field for that failed attempt.

## Read-back and precommit snapshots

Preserve the complete original post-create snapshot used to create every child, including its observed UUID `page_id`. The exact field sets are:

```text
Feed = {page_id,Name,Batch Key,Run Key,Payload Digest,Fingerprint Window Digest,
Body Format,Part Index,Part Count,Feed Success Count,Feed Failure Count,
New Item Count,Item Count,Fetched At,All Sources Failed,Created At,Run,body,payload}

Memory = {page_id,Name,Record Key,Revision Key,Run Key,Dedupe Key,Continuity ID,
Target,Payload Digest,Body Format,Record Type,Record Status,Importance,Category,
Region,Action,Revision,Confidence,Effective At,Verified Evidence,Created At,
Updated At,Run,Supersedes,body,payload}

Report = {page_id,Name,Report Key,Run Key,Integration Key,Payload Digest,
Rendering Digest,Body Format,Report Type,As Of,Coverage Start,Coverage End,Stance,
Confidence,Data Gap Count,Material Change,User Visible,Created At,Run,
Evidence Records,body,payload,rendering}
```

Compare these sets and all values type-sensitively; a missing or extra snapshot field is invalid. `Name`, `Created At`, and `Updated At` are observed/frozen values, not values to reconstruct from a physical key. Feed/Memory body decoding must return exact empty rendering. Relations are exact ordered unique UUID page-ID arrays. The physical-key-to-page-ID maps in `expected_child_ids` and the complete snapshots must have identical kinds, keys, and page IDs.

Fetch every expected page and validate it against that snapshot before setting `Output Prepared=true`:

- exact physical key and expected page ID
- exact `Run Key` property and one-element parent `Run` relation
- exact properties with type-sensitive equality
- `Body Format` equals the body's embedded readable format: `wm-body-v2` for every new page, or `wm-body-v1` only for an existing legacy page
- decoded canonical payload and embedded/property digest
- Report rendering and rendering digest
- Feed part index/count/item count, configured outcomes, fingerprint window digest, and complete-group totals
- Memory Record Key, integer non-boolean Revision, predecessor relation, and revision-chain validity
- Report v2 payload, exact scenario fields, logical Integration Key, and evidence relations

Preserve the original post-output-prepared Run snapshot with these exact fields and body:

```text
Name, Slot Key, Run Key, Integration Key, Attempt, Trigger, Status, Installation,
Started At, Scheduled Slot, Collection Cutoff, Finished At,
Feed Success Count, Feed Failure Count, New Item Count,
Material Change, Integration Due, Integration Performed, Output Prepared,
Cache Reconciled, Notification Plan, Input Digest, Output Digest,
Error Summary, Created At, Updated At, body
```

That original snapshot has the exact observed `Name`, `Created At`, and post-`Output Prepared` `Updated At`, plus `Status=preparing`, `Output Prepared=true`, one exact Installation relation, and canonical Run Key/Attempt/Integration Key. `Started At`, `Scheduled Slot`, and `Collection Cutoff` are nonempty canonical second-precision UTC. `Finished At` alone may be empty while preparing.

Keep `page_id` outside that field list. Preserve the separately observed parent Run UUID as `expected_run_page_id`. Every fresh Slot Key, exact Run Key, and current Integration Key query must return the expected current row with `page_id=expected_run_page_id`; any additional or differently identified row is a conflict. Every expected child's exact `Run` relation must be `[expected_run_page_id]`. Apply this page-ID binding before comparing the field-only `expected_run_snapshot`, so a different page with identical properties cannot pass.

The Run body is written as canonical `wm-body-v2`; an existing canonical `wm-body-v1` Run remains readable. Its decoded payload has the exact top-level set `timestamp,trigger,feed,materialChange,worldMemory,notification,audit,commit`. Within `feed`, require the subset `sourceOutcomes,successCount,failureCount,newItemCount` while allowing other feed audit fields. `sourceOutcomes` is the exact configured-order five-outcome list and obeys the durable `ok|error` matrix; the three counts are type-strict non-boolean non-negative integers derived from it. All-five-failed audit facts are exactly `0/5/0`. Bind children only through `audit.expectedChildren`, with this exact object shape:

```text
feed:   [{key,pageId,payloadDigest,fingerprintWindowDigest}, ...]
memory: [{key,pageId,payloadDigest}, ...]
report: [{key,pageId,payloadDigest,renderingDigest}, ...]
```

Each array is sorted by `key`; duplicate keys or page IDs anywhere in the three-array inventory are invalid. The inventory kind/key/page-ID/digest values must exactly equal the complete preserved child snapshots and `expected_child_ids`. The audit also records the validated registry digest, configured source outcomes, gate evidence, prior integration cutoff, autopilot permissions/decisions, notification plan, and errors in its already validated sections; do not invent new top-level business keys. This canonical inventory is used for stale inspection and precommit. Never reconstruct a smaller inventory from whatever children happen to remain visible.

Immediately before commit, perform new queries separately against every relevant source:

1. Runs by Slot Key
2. Runs by exact Run Key
3. Runs by Integration Key when present
4. each expected child physical key
5. each Memory logical `(Record Key, Revision)`
6. six-hour Report logical `Integration Key`
7. the complete child projections required to detect unexpected rows

Fetch fresh pages and compare every observed Run field/body type-sensitively to the preserved original Run snapshot. Compare every child to its preserved original property/payload/rendering snapshot using the same full child validator. Revalidate complete Feed groups, Run/attempt key syntax, Integration identity, relations, parent statuses, logical Memory/Report uniqueness, and exact expected key/page-ID sets.

Precommit receives the complete fresh projections needed for those decisions: the complete normalized Installation singleton; Slot, exact Run Key, and current Integration Key Run rows; every child physical-key row; Memory logical revision peers and predecessor rows; Report logical Integration peers and evidence Memory rows; and parent statuses for every related page. Revalidate every Installation field and require `Enabled=true`. Its phase is either `Status=active`, or `Status=initializing` only with `explicit_setup=true` and direct `manual|force-world-memory`; scheduled `explicit_setup` is always invalid. When `Autopilot Enabled=false`, all current observed/expected Memory child projections and authoritative completion IDs are empty; prior committed Memory rows queried solely as Report evidence remain allowed.

The current parent Run remains Status=preparing with `Output Prepared=true`, `Finished At=""`, and `Cache Reconciled=false`. Require exact booleans and enforce `Integration Due must equal Integration Performed`; `force-world-memory` requires true. The exact Report/notification matrix is: performed integration has a nonempty canonical Integration Key, one six-hour Report, no hourly Report, and `Notification Plan=six-hour`; scheduled non-integration has an empty Integration Key, one hourly Report, no six-hour Report, and `Notification Plan=hourly-briefing` regardless of Material Change; direct non-integration material change has the same hourly inventory; direct non-integration nonmaterial has no Report and `Notification Plan=silent`. A non-integration Run has no Memory child and completes no suggestion. The direct Report validator enforces the same per-type parent projection: six-hour requires parent Due/Performed true and six-hour notification; hourly requires parent Due/Performed false, hourly notification, empty parent/Report Integration Keys, and either a scheduled parent or `Material Change=true`.

Precommit must bind the canonical audit inventory to the full snapshots, bind every child to the same parent Run/Installation, cross-bind the exact `audit.feed` subset and parent counts to one complete committable Feed group with five exact outcomes and at least one success, and enforce the matrix above. The all-five-failed path never enters precommit.

Any zero/multiple match, unexpected child, changed body/digest/property, mutually agreeing observations that differ from the original snapshot, malformed group, noncanonical key, boolean numeric field, or competing preparing/committed logical row blocks commit. Terminalize the Run as failed when safe. Never weaken this check because multiple fresh queries agree with one another.

## Commit, cache reconciliation, notification, and failures

Set `Status=committed` only after the full precommit gate passes. This status update is the final authoritative mutation. If its response is uncertain, query the exact Run Key and Slot and fetch the page; do not claim success or failure until the status is observed. After an observed commit, requery the exact key and Slot again. A duplicate or competing committed/preparing observation is an integrity error: stop without cache mutation or user success output.

After commit confirmation, reconcile the Installation cache best-effort from a complete relevant Run projection. Include committed and noncommitted rows required to detect duplicate Run Keys and invalid status mixtures; do not prefilter the projection to successful committed rows. The pure reconciliation boundary uses decoded `{feedId:cursor}` rather than the RICH_TEXT form. Persisted Feed Batch payloads retain the configured-order `sourceOutcomes` list. For every committed row, the adapter must convert its validated list to a per-Run mapping with exactly the five configured `feedId` keys, with each inner object containing exactly `status`, `itemCount`, `cursor`, and `error`; noncommitted rows do not require decoded outcomes. Pass the complete projection as `authoritative_runs` to `reconcile_installation_cache(current, candidate, authoritative_runs)`. A committed candidate must type-sensitively match its unique projection member. Pass the resulting complete normalized Installation through `serialize-installation-cache` before the Notion update and use its canonical cursor RICH_TEXT unchanged.

- Reject duplicate Run Keys, duplicate committed nonempty logical Integration Keys, malformed configured outcomes, unknown sources, invalid cursor case, boolean counts, and status/error inconsistencies.
- Validate duplicate Run Keys and row statuses across the complete projection before candidate eligibility. Thus a committed row plus a failed row with the same Run Key is a conflict, not a cache no-op.
- After that projection validation, a failed/noncommitted candidate or a committed candidate absent from the projection leaves cache unchanged. A committed all-source-failed row is corruption; a failed all-source attempt remains audit-only.
- A present committed candidate must occur uniquely and every supplied fact must type-sensitively match its authoritative Run row. A duplicate/nonunique or mismatching present candidate raises a reconciliation conflict; it is not a cache no-op.
- Rebuild successful cursors in `(Collection Cutoff, Run Key)` order. A successful empty cursor and every failed source preserve the prior cursor. A missing or extra source in a committed mapping is corruption because the mapping must contain exactly the five configured IDs.
- Derive `Last Feed Attempt`, `Last Feed Success`, cursors, integration success/next time, and last partial-source error only from committed Runs having at least one successful configured source, ordered by `(Collection Cutoff, Run Key)`. A failed all-source attempt remains visible only in its failed Run audit/`Error Summary` and never advances or clears the Installation cache.
- Derive Report/briefing success from the prepared `Notification Plan` and `(Finished At, Run Key)` order. Report-only Runs do not advance the integration cutoff.
- Qualifying committed facts from the complete relevant projection may correct an Installation cache backward or forward. A candidate by itself never regresses newer authority.

This is eventual repair, not compare-and-swap and not a crash-safe monotonic guarantee. A cache write failure or late older candidate never invalidates a committed Run; another reconciliation may repair it. Every later due/cursor read repeats the committed-source query.

Keep collection and report clocks distinct:

- Feed Batch `Fetched At` and Run `Collection Cutoff` define the integration snapshot boundary.
- Report `As Of` and `Coverage End` use that collection cutoff, not the later rendering finish time.
- `Last World Memory Success` uses the committed integration collection cutoff; `Next World Memory At` is exactly six hours later.
- Run `Finished At`, Installation `Last Report Success`, and Installation `Updated At` use the later successful report-finish time.
- A report-only committed Run may advance `Last Report Success` but never `Last World Memory Success` or the Integration Key boundary.
- A failed Run or failed commit advances no authoritative cutoff or successful cache time.

The terminal order is:

```text
commit Run -> confirm exact Run/Slot -> reconcile cache best-effort -> return output
```

Record `Notification Plan` as `silent|hourly-briefing|six-hour|error`; never record an unobservable `sent` claim. Every successful active scheduled Run is visible: non-due uses the cumulative full-size hourly Report and due/forced uses the six-hour Report. Paused or disabled scheduled no-ops remain silent. A manual Run returns its direct result. Surface source failures and data gaps in visible output without inventing evidence.

Failure boundaries:

- MCP access failure: zero mutation.
- ambiguous Hub/database/Installation/Run/child key: choose none; commit none.
- scheduled schema/version/relation drift: zero mutation; return setup/stored error.
- body/digest/relation/revision/precommit failure: terminalize the Run as failed when safe; cache unchanged.
- uncommitted child: retain it physically, exclude it from authority.
- post-commit cache failure: preserve the committed Run and report the cache warning internally; do not reverse authority.
- output delivery: return only prepared committed content; do not fabricate delivery observation.
