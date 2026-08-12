# Source contract

## Contents

- Exact FEEDs
- Direct HTTP acquisition boundary
- Normalization and identity
- Configured-order outcomes and cursor cache
- Fingerprint checkpoints
- Evidence use

## Exact FEEDs

Fetch exactly these five RSS.app CSV sources independently, in this configured order:

| `feedId` | Title | URL | Offset minutes |
|---|---|---|---:|
| `financial_juice` | FinancialJuice | `https://rss.app/feeds/5VaycMAa8SwPhOAP.csv` | 0 |
| `walter_bloomberg` | Walter Bloomberg | `https://rss.app/feeds/YcRRdWN5eSO3o2LP.csv` | 0 |
| `wall_st_engine` | Wall St Engine | `https://rss.app/feeds/Hf52VRUllNu7gABF.csv` | 0 |
| `first_squawk` | First Squawk | `https://rss.app/feeds/d68ow40E3dkwaEvN.csv` | -540 |
| `unusual_whales` | unusual_whales | `https://rss.app/feeds/nikLNBATmLDuprRz.csv` | -540 |

Do not add, substitute, reorder, change the extension, or correct another source unless this contract is deliberately revised. XML is not a configured fallback.

## Direct HTTP acquisition boundary

Acquire the five RSS.app CSV URLs only through the packaged direct-HTTP path using Python `urllib.request` with the configured user agent and bounded timeout. Attempt every source independently even when another request or CSV validation fails.

Generic web fetch, web search, and browser navigation must not be used as an RSS.app fallback. A blocked direct-HTTP execution path, HTTP failure, malformed response, or invalid CSV is the observed error for that configured source; do not convert it into an inferred success or attempt another format. This FEED-specific boundary does not change the separate official-web fallback rules for market-data collection.

## Normalization and identity

Decode the response as UTF-8 without a BOM and require this exact ordered header with no missing, extra, reordered, or duplicate column:

```text
ID, Feed URL, Feed Link, Feed Title, Feed Description, Feed Icon, Title, Link, Description, Image, Plain Description, Author, Date
```

For every RSS.app CSV row, require a nonempty whitespace-collapsed `Title` and raw `Date`. Choose item identity as nonempty `Link`, else whitespace-collapsed `Title`. Parse raw `Date` as the publication timestamp. Reject malformed UTF-8, a BOM, a wrong column count, empty required fields, or an invalid date.

Build the fingerprint bytes exactly as UTF-8:

```text
feedId + "\n" + identity + "\n" + raw Date
```

Set `sourceFingerprint` to the lowercase 64-character SHA-256 hex digest. Set `id` to `nf_` plus the first 18 hex characters of that digest. Deduplicate only on the complete `sourceFingerprint`; a processed row wins over a duplicate pending row.

Parse the raw `Date` into UTC and retain it as `sourcePublishedAt`. Set `publishedAt` to `sourcePublishedAt + publishedAtOffsetMinutes`; only `first_squawk` and `unusual_whales` use `-540`. Preserve the literal raw `Date` text for fingerprinting even though stored timestamps are canonical UTC.

Use `Link` as `sourceUrl`; fall back to the configured CSV URL only when `Link` is empty. Record the configured CSV URL separately as `feedSourceUrl`. A normalized item retains `schemaVersion:1`, `status:"pending"`, and `importanceCandidate:"unassessed"` until analysis changes its role.

## Configured-order outcomes and cursor cache

Attempt all five FEEDs even when another fails. Store an exact configured-order `sourceOutcomes` list in every Feed Batch part. It contains each configured feed ID exactly once, with each object having exactly:

```json
{"feedId":"...","status":"ok|error","itemCount":0,"cursor":"","error":""}
```

- `itemCount` is a non-boolean integer at least zero.
- `ok` requires an empty `error` and a `cursor` that is empty or lowercase 64-hex.
- `error` requires `itemCount:0`, an empty `cursor`, and a nonempty `error`.

Every status, count, cursor, and error must come from an observed attempt. Never turn an unstated or unavailable result into `ok`. A committed Feed Batch requires one fully observed valid outcome for each configured source; an incomplete observation cannot be filled by inference and cannot pass child validation.

Derive Feed Batch success/failure counts and `All Sources Failed` from these outcomes; never enter them independently. Repeated parts must have identical outcomes. Every stored item belongs to an `ok` outcome, has `fetchedAt` equal to the wrapper, and satisfies canonical `publishedAt <= fetchedAt`. Across the complete multipart group, the retained unique item count for each feed is at most that outcome's observed `itemCount`, and the total retained count is at most the sum of successful outcome counts. The observed collection count need not equal the new-item count after dedupe.

A committable Run has all five exact outcomes, success plus failure equal to five, at least one success, and a Feed Batch part 1 even when no items are new. An all-error list is audit evidence for a failed Run, never a valid child payload.

The Run audit's `feed` object has the required subset `sourceOutcomes`, `successCount`, `failureCount`, and `newItemCount`; other feed audit fields remain allowed. The outcomes are the same configured-order five exact objects above, success/failure are non-boolean non-negative integers derived from their statuses, and newItemCount is a non-boolean non-negative integer. Cross-bind those four facts type-sensitively to the complete Feed group and parent Run. The all-five-failed failed-Run audit is exactly success `0`, failure `5`, and new items `0` with five `error` outcomes.

`WM Installations.Feed Cursor State` is canonical compact JSON text containing a `{feedId: cursor}` cache. Its adapter decodes to that object before pure reconciliation. Persisted Feed Batch outcomes remain the configured-order list above. For each committed Run, convert its validated list to a mapping keyed by `feedId`; that mapping has exactly all five configured IDs, and each value has exactly `status`, `itemCount`, `cursor`, and `error`, with no inner `feedId`. Supply the complete relevant Run projection—including noncommitted rows needed for duplicate-key and status detection—to `reconcile_installation_cache`; noncommitted rows do not require decoded outcomes. Validate the full projection first, then require a present committed candidate to occur uniquely and match its projection row type-sensitively; nonunique or mismatching present candidates raise a conflict rather than returning a no-op. Advance a successful source to its returned nonempty cursor; a successful empty cursor or failed source preserves its prior cursor. A missing/extra source is corruption rather than an implicit failed outcome. Derive Installation `Last Feed Attempt`, `Last Feed Success`, and cursors only from committed Runs with at least one successful source. A committed all-source-failed row is corruption. If every source fails, record every attempt/error only in the failed Run audit and `Error Summary`, create no Feed Batch, Memory, or Report child page, terminalize the Run as failed, and leave the entire Installation cache unchanged. After full-projection conflict checks, a failed/noncommitted or absent candidate also leaves it unchanged. A partial failure may commit the successful evidence while retaining the failed cursor and error context for the next hour. Before persisting the reconciled cache, use the packaged `serialize-installation-cache` command and copy its returned cursor text exactly; configured order applies to outcome lists, not to JSON object serialization.

## Fingerprint checkpoints

Feed Batch part 1 carries `fingerprintWindow`; every part carries the complete source outcomes. A window entry is exactly `{sourceFingerprint,publishedAt}`, sorted by `(publishedAt,sourceFingerprint)` and capped to the latest 2,000. Identical duplicate fingerprints collapse only when their timestamps agree; the same fingerprint paired with different `publishedAt` values is corruption. Set part 1 `Fingerprint Window Digest` to `canonical_digest(fingerprintWindow)` and set the property to the empty string on every later part.

The checkpoint loader's first input is `checkpoint_rows`, never detached payloads. Each candidate is a full Feed row snapshot with the exact Feed field set, observed UUID `page_id`, one exact `Run=[<page-id>]` relation to a fetched committed Run, observed `Created At`, and verified canonical body/payload/property digests. A part-1 row with `Part Count>1` is not independently authoritative: supply and validate every contiguous part of the same parent/Run Key before using its window. Enforce global checkpoint/batch Feed page-ID uniqueness across both authoritative input collections; a duplicate UUID is corruption and contributes no authority.

Build the next window from all valid committed complete checkpoint groups whose observation times are in inclusive `[now-12h,now]`, plus every item from every valid complete committed Feed Batch group in that horizon. When that horizon has no valid checkpoint, find the maximum valid pre-horizon checkpoint `fetchedAt`, union all co-latest pre-horizon groups at that exact timestamp, and ignore every older group. Fetch every related Run and exclude noncommitted, incomplete, malformed, or bad-digest groups. Reject a checkpoint/window fingerprint whose canonical `publishedAt` is after observed `now`, and reject a group/checkpoint whose `fetchedAt` is after `now`. Any raw-source clock-skew handling must happen before durable normalization and cannot bypass these stored invariants.

For each complete multipart group, compute the expected next window from retained prior observations plus items from every part, then apply canonical sorting and the latest-2,000 cap. Part 1's window/digest must equal that complete-group result; a window closed only over part 1 is invalid. Mark a damaged/missing checkpoint rebuild as the `fingerprint-window-rebuilt` data gap.

Different slots may commit divergent windows from the same starting point; the next load unions all committed branches. Within a collection, deduplicate again before counting `newItemCount`. During integration, merge committed batches in the cutoff range and deduplicate again. Do not rewrite or delete prior parts.

## Evidence use

Use FEEDs as fast discovery evidence. Do not add a confirmed durable brief, change a state, or trigger a material notification from an unconfirmed headline alone. Re-open the original issuing source when available; otherwise confirm with a high-trust traditional outlet. Record outlet, direct URL, and publication time in canonical Memory/Report sources.

Prefer official releases and filings for policy, central-bank, regulator, company, earnings, and guidance facts. Use reputable traditional media to corroborate contested or fast-moving claims. State the gap and keep the candidate unpromoted when confirmation is unavailable.
