---
name: world-memory-autopilot
description: Use when handling 월드메모리 or world memory requests, hourly feed monitoring, manual feed refreshes, forced six-hour reports, Notion ledger setup, or autopilot state updates.
metadata:
  version: "0.9.4"
---

# World Memory Autopilot

## Core contract

Operate World Memory only through its registered Notion v2 Hub and five data sources. A child page is authoritative only while its related Run has `Status=committed`; the Installation row is an eventual cache, never the gate authority. Use the packaged deterministic module for registry, policy, key, feed, digest, and precommit decisions.

Read the references at their decision boundary:

- Read [storage-contract.md](references/storage-contract.md) before any setup, schema, registry, query, Run, child, commit, cache, or recovery decision.
- Read [source-contract.md](references/source-contract.md) before collecting or normalizing any FEED.
- Read [analysis-contract.md](references/analysis-contract.md) before judging materiality, creating Memory or Reports, completing a suggestion, or rendering output.
- Read [market-data-contract.md](references/market-data-contract.md) before declaring a cross-asset input unavailable or using market data in materiality, Memory, Reports, or output.

## Invocation policy

Normalize the trigger to `scheduled`, `manual`, or `force-world-memory`. A direct user request defaults to `manual`; choose `force-world-memory` only for an explicit forced full integration.

For every operational invocation, validate the exact supplied registry locally with the packaged module before making any Notion call. A scheduled automation must take that input from the self-contained prompt's `<world_memory_registry>` block and must not depend on project instructions or files; a direct invocation may take it from the project instruction. Only a valid registry permits registry-directed Notion `self` reads, referenced-schema reads, or inspection of its Installation. The separately user-approved, no-registry live initialization follows the deterministic discovery path in the storage contract instead. For an operational Run, query the Installation by exact `Installation Key` and apply the packaged policy:

- A scheduled invocation with an absent/invalid registry, missing Installation, `initializing`, schema drift, or relation drift must not search for a replacement, initialize, repair, collect, or mutate. Return the policy's setup/stored error; never open an unattended approval flow.
- A scheduled paused or disabled Installation is a silent no-op. A direct paused, disabled, or stored-error invocation is read-only and must report that condition.
- Ledger supersession is an exceptional direct repair, never an operational or scheduled-run behavior. It requires the user's explicit approval for the exact observed Run and the packaged `plan-run-supersession` decision. Apply only the returned `Status=superseded` property update, preserve the Run body and every child unchanged, re-read the target and Feed Batch, then rebuild the Installation cache from an empty baseline over the complete remaining committed projection. Keep any paused automation paused until all read-back and cache validators pass.
- An active enabled Installation may collect, analyze, write Run/Feed Batch/Report children, and reconcile cache. Only a Run with `Integration Performed=true` may create Memory revisions or complete suggestions. `Autopilot Enabled=false` blocks those integration-time Memory actions, not collection or reporting.
- Explicit live initialization is a separate, user-approved setup action. It may use `manual` or `force-world-memory` while `initializing`; it is never part of a scheduled run. Accept a Hub anchor only after observing the exact title/markers, workspace-root parent, and explicit not-published state. A partial title/marker identity, wrong/nested/public candidate, unobservable placement, or nonexhaustive search result blocks dependent creation.
- Before any initialization mutation, fetch Notion `self`, observe the workspace ID, confirm current access to `search`, `fetch`, `create_pages`, `create_database`, `update_data_source`, `query_data_sources`, `update_page`, and `create_view`, then fetch `notion://docs/enhanced-markdown-spec`. Any unavailable check is a zero-mutation stop.
- Never create or enable the hourly automation merely because setup verification passed or the Installation became `active`. It becomes eligible only after the validated registry has been rendered into a self-contained automation prompt with `PYTHONPATH=<skill-path>/scripts python3 -m world_memory render-scheduled-prompt PATH|-` and that returned `prompt` value has been installed verbatim. Never hand-compose or shorten the scheduled prompt. When the registry changes, keep the automation paused until the regenerated prompt is installed and its embedded `<world_memory_registry>` block matches the validated registry. Resolve an existing automation privately and require exactly one matching World Memory task before changing only its prompt unless the user requested other task fields.

## Run sequence

Follow this order exactly:

1. For an operational invocation, run the packaged local registry validator. If it fails, stop before reading the source or analysis contracts; in particular, a scheduled invocation makes no Notion `self`/schema call and no other external call. Only after local validation succeeds, validate Notion access, workspace ID, all five data-source schemas, relation targets, and the complete Installation row. Validate raw Notion serialization and registry/Hub bindings at the adapter boundary, then pass only the normalized row to pure policy/gate/cache helpers. Query each data source separately; do not use a cross-source SQL join or Rollup as authority. The explicit live-initialization sequence is the only no-registry exception and never runs on a schedule.
2. Query Runs for the deterministic Slot Key and resolve duplicate exact Run Keys, committed reuse, preparing conflicts, and stale recovery. Before classifying a preparing Run, fetch its own `Started At`: missing/malformed is an integrity conflict, observed age under 65 minutes is fresh, and age at least 65 minutes permits stale inspection. Never substitute the current invocation start. Create one `preparing` Run only when resolution permits it, then requery its exact Run Key.
3. Read [source-contract.md](references/source-contract.md). Query committed Feed Batch checkpoints source-by-source, fetch their parent Runs, and pass only full Feed row snapshots with committed Run relations and verified bodies to the window loader. A multipart checkpoint is authoritative only as a complete group; the newest pre-horizon timestamp unions every co-latest group, and checkpoint/batch Feed page IDs are globally unique. Rebuild the fingerprint window, then attempt all five configured FEEDs independently.
4. Read [analysis-contract.md](references/analysis-contract.md). When market reaction is needed for a materiality decision or a visible Report may be prepared, read [market-data-contract.md](references/market-data-contract.md), generate the packaged public-source plan, then run the packaged bounded collector. Use its successful observations and derived values directly; never turn an unattempted public source into a data gap. Resolve the nominal six-hour gate from committed integration Runs, never Installation cache alone. Treat it as due at 5 hours 45 minutes after the latest committed integration cutoff to prevent a three-hour collection cadence from slipping to nine hours; keep the interval field, Report type, notification name, Korean rendering, and `Next World Memory At` user-facing contract six-hour, with that cache time exactly six hours after the cutoff. Every successful active scheduled Run prepares one visible full-size Report: due/forced Runs use `six-hour`; non-due Runs use `hourly-briefing` over the cumulative range after the latest committed integration cutoff through the current collection cutoff. A force bypasses only the clock; it does not bypass access, policy, schema, uniqueness, or fresh-preparing conflicts.
5. If all five FEEDs failed, create no Feed Batch, Memory, or Report child: write the five outcomes only to the Run audit/`Error Summary`, terminalize that Run as `failed`, and leave the Installation cache unchanged. Otherwise build deterministic Feed Batch parts and, when permitted and supported by verified evidence, Memory revisions and Reports. Query each physical key before and after create. Also query logical Memory revision and six-hour Report identities.
6. Fetch every expected child and preserve its complete post-create snapshot, including observed UUID page ID, all properties, exact ordered relations, body, payload, and Report rendering. Verify parent Run/Installation/Slot/Integration binding, canonical Run audit inventory, digests, Feed window closure, Memory actions/evidence/predecessors, Report projections/evidence/visibility, and Korean rendering. The `audit.feed` required subset is exactly `sourceOutcomes`, `successCount`, `failureCount`, and `newItemCount`; other feed audit fields remain allowed, while that subset, the complete multipart group, and parent Run counts must agree type-sensitively.
7. Set `Output Prepared=true`, fetch the exact Run, and preserve its full post-update Run snapshot including observed `Updated At`. Then perform fresh source-by-source Installation, Slot, exact Run, Integration, child, logical Memory, and logical Report queries. Precommit requires the complete normalized enabled Installation, the current parent Run to remain `Status=preparing` with empty `Finished At` and `Cache Reconciled=false`, `Integration Due` equal to `Integration Performed`, the exact Report/notification matrix, no Memory or completion on a non-integration Run, and no Memory or completion when Autopilot is disabled. `explicit_setup` is valid only for an initializing direct manual/force Run, never scheduled. Any missing, duplicate, unexpected, or mutated observation blocks commit and terminalizes the Run as `failed` when safe.
8. Set `Status=committed` as the final authoritative mutation. Requery and fetch the exact Run and Slot; a post-commit integrity conflict stops cache and output.
9. Reconcile the Installation cache best-effort from the complete relevant Run projection, including noncommitted rows needed for duplicate-key and status-conflict detection. Derive cache facts only from qualifying committed rows. Before every cache write or explicit cache repair, pass the complete normalized Installation result through `PYTHONPATH=<skill-path>/scripts python3 -m world_memory serialize-installation-cache PATH|-` and apply its returned property values exactly; never hand-serialize `Feed Cursor State` or preserve mapping insertion order. Cache failure never invalidates a committed Run, and cache values never override committed evidence.
10. Only after commit confirmation and cache attempt, return the prepared Korean output or policy-required silence/error. Record a notification plan, never an unobservable delivery-success claim.

Do not delete uncommitted children. Exclude them from every authoritative read.

## Deterministic helpers

Use the read-only CLI where it replaces hand calculation. Every helper invocation needs this executable prefix; the bare subcommand names are not commands. In an execution plan, audit, or answer, always spell the full executable form and never abbreviate it to a bare subcommand:

```text
PYTHONPATH=<skill-path>/scripts python3 -m world_memory validate-registry PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory render-scheduled-prompt PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory schema [--database installations|runs|feed_batches|memory|reports]
PYTHONPATH=<skill-path>/scripts python3 -m world_memory relations PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory run-key --installation-key KEY --trigger TRIGGER --now UTC --attempt N
PYTHONPATH=<skill-path>/scripts python3 -m world_memory digest PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory serialize-installation-cache PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory plan-run-supersession PATH|-
PYTHONPATH=<skill-path>/scripts python3 -m world_memory normalize-feed --feed-id ID --payload XML_PATH|- --now UTC [--fingerprint-window JSON_PATH|-]
PYTHONPATH=<skill-path>/scripts python3 -m world_memory gate --installation PATH|- --committed-integrations PATH|- --trigger TRIGGER --now UTC [--registry-valid] [--explicit-setup]
PYTHONPATH=<skill-path>/scripts python3 -m world_memory verify-live [--timeout SEC]
PYTHONPATH=<skill-path>/scripts python3 -m world_memory market-data-plan --now UTC
PYTHONPATH=<skill-path>/scripts python3 -m world_memory collect-market-data --now UTC [--timeout SEC]
```

Treat a nonzero result as a failed decision. The CLI does not mutate Notion or its inputs.

## Safety boundary

Use only the registered World Memory Hub/data sources, packaged `world_memory` module, task-relevant Notion operations, web/finance research, and notification capabilities. Do not invent an opaque ID or unobserved source outcome/cursor, create beside an ambiguous match, alter schema during a scheduled run, assume uniqueness/CAS/transactions, delete ledger rows, execute arbitrary shell/file mutations, apply an unverified state change, invent market data, mark an unsuccessful mutation `completed`, suppress a successful active scheduled Report, or advance authoritative cutoffs after a failed commit.
