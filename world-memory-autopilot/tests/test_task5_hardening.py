from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from world_memory import contracts, scheduler, storage


WORKSPACE_ID = "123e4567-e89b-42d3-a456-426614174000"
INSTALLATION_KEY = "wm:123e4567-e89b-42d3-a456-426614174000:default"
INSTALLATION_HASH = "b12ee94ad696"
INSTALLATION_PAGE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
HUB_PAGE_ID = "11111111-1111-4111-8111-111111111111"
RUN_PAGE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
FEED_PAGE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SLOT_KEY = f"wms_{INSTALLATION_HASH}_scheduled_20260810T020000Z"
RUN_KEY = f"{SLOT_KEY}_a001"

FEED_IDS = (
    "financial_juice",
    "walter_bloomberg",
    "wall_st_engine",
    "first_squawk",
    "unusual_whales",
)


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def installation(**overrides: object) -> dict:
    value = {
        "page_id": INSTALLATION_PAGE_ID,
        "Name": INSTALLATION_KEY,
        "Installation Key": INSTALLATION_KEY,
        "Hub Page ID": HUB_PAGE_ID,
        "Hub URL": "https://www.notion.so/11111111111141118111111111111111",
        "Status": "active",
        "Enabled": True,
        "Autopilot Enabled": True,
        "Timezone": "Asia/Seoul",
        "Hourly Interval Minutes": 60,
        "World Memory Interval Hours": 6,
        "Schema Version": 2,
        "Skill Contract Version": "notion-v2",
        "Feed Cursor State": {},
        "Last Feed Attempt": "",
        "Last Feed Success": "",
        "Last World Memory Success": "",
        "Last Report Success": "",
        "Next World Memory At": "",
        "Last Briefing At": "",
        "Last Error": "",
        "Created At": "2026-08-10T01:00:00Z",
        "Updated At": "2026-08-10T01:00:00Z",
        "Runs": [],
    }
    value.update(overrides)
    return value


def parent_run(**overrides: object) -> dict:
    value = {
        "page_id": RUN_PAGE_ID,
        "Name": RUN_KEY,
        "Slot Key": SLOT_KEY,
        "Run Key": RUN_KEY,
        "Integration Key": f"wmi_{INSTALLATION_HASH}_genesis",
        "Attempt": 1,
        "Trigger": "scheduled",
        "Status": "preparing",
        "Started At": "2026-08-10T02:00:00Z",
        "Scheduled Slot": "2026-08-10T02:00:00Z",
        "Collection Cutoff": "2026-08-10T02:00:00Z",
        "Finished At": "",
        "Feed Success Count": 5,
        "Feed Failure Count": 0,
        "New Item Count": 1,
        "Material Change": True,
        "Integration Due": True,
        "Integration Performed": True,
        "Output Prepared": True,
        "Cache Reconciled": False,
        "Notification Plan": "six-hour",
        "Input Digest": "1" * 64,
        "Output Digest": "2" * 64,
        "Error Summary": "",
        "Created At": "2026-08-10T02:00:00Z",
        "Updated At": "2026-08-10T02:00:02Z",
        "Installation": [INSTALLATION_PAGE_ID],
        "body": "placeholder until audit tests",
    }
    value.update(overrides)
    return value


def source_outcomes(*, failed: tuple[str, ...] = ()) -> list[dict]:
    rows = []
    for index, feed_id in enumerate(FEED_IDS):
        if feed_id in failed:
            rows.append({
                "feedId": feed_id,
                "status": "error",
                "itemCount": 0,
                "cursor": "",
                "error": "timeout",
            })
        else:
            rows.append({
                "feedId": feed_id,
                "status": "ok",
                "itemCount": 1 if index == 0 else 0,
                "cursor": "",
                "error": "",
            })
    return rows


def mapped_outcomes(*, failed: tuple[str, ...] = ()) -> dict[str, dict]:
    return {
        row["feedId"]: {
            "status": row["status"],
            "itemCount": row["itemCount"],
            "cursor": row["cursor"],
            "error": row["error"],
        }
        for row in source_outcomes(failed=failed)
    }


def feed_item(
    fingerprint: str = "1" * 64,
    *,
    feed_id: str = "financial_juice",
    published_at: str = "2026-08-10T01:55:00Z",
    fetched_at: str = "2026-08-10T02:00:00Z",
) -> dict:
    source = {
        "financial_juice": (
            "FinancialJuice",
            "https://rss.app/feeds/5VaycMAa8SwPhOAP.xml",
            0,
        ),
        "walter_bloomberg": (
            "Walter Bloomberg",
            "https://rss.app/feeds/YcRRdWN5eSO3o2LP.xml",
            0,
        ),
        "wall_st_engine": (
            "Wall St Engine",
            "https://rss.app/feeds/Hf52VRUllNu7gABF.xml",
            0,
        ),
        "first_squawk": (
            "First Squawk",
            "https://rss.app/feeds/d68ow40E3dkwaEvN.xml",
            -540,
        ),
        "unusual_whales": (
            "unusual_whales",
            "https://rss.app/feeds/nikLNBATmLDuprRz.xml",
            -540,
        ),
    }[feed_id]
    source_published = utc(published_at) - timedelta(minutes=source[2])
    return {
        "schemaVersion": 1,
        "id": f"nf_{fingerprint[:18]}",
        "sourceFingerprint": fingerprint,
        "feedId": feed_id,
        "feedTitle": source[0],
        "feedSourceUrl": source[1],
        "sourceUrl": "https://example.com/item",
        "title": "Observed headline",
        "sourcePublishedAt": source_published.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "publishedAt": published_at,
        "publishedAtOffsetMinutes": source[2],
        "fetchedAt": fetched_at,
        "status": "pending",
        "importanceCandidate": "unassessed",
    }


def feed_payload(
    *,
    items: list[dict] | None = None,
    outcomes: list[dict] | None = None,
    fetched_at: str = "2026-08-10T02:00:00Z",
    fingerprint_window: list[dict] | None = None,
) -> dict:
    current_items = [feed_item(fetched_at=fetched_at)] if items is None else items
    window = (
        [
            {
                "sourceFingerprint": item["sourceFingerprint"],
                "publishedAt": item["publishedAt"],
            }
            for item in current_items
        ]
        if fingerprint_window is None
        else fingerprint_window
    )
    return {
        "schemaVersion": 2,
        "kind": "feed-batch",
        "runKey": RUN_KEY,
        "batchKey": f"{RUN_KEY}:feed:001",
        "partIndex": 1,
        "partCount": 1,
        "fetchedAt": fetched_at,
        "newItemCount": len(current_items),
        "sourceOutcomes": source_outcomes() if outcomes is None else outcomes,
        "items": current_items,
        "fingerprintWindow": window,
    }


def feed_page(payload: dict | None = None) -> tuple[dict, dict]:
    current = feed_payload() if payload is None else payload
    success_count = sum(row["status"] == "ok" for row in current["sourceOutcomes"])
    batch_key = current["batchKey"]
    page = {
        "page_id": FEED_PAGE_ID,
        "Name": batch_key,
        "Batch Key": batch_key,
        "Run Key": current["runKey"],
        "Payload Digest": storage.canonical_digest(current),
        "Fingerprint Window Digest": (
            storage.canonical_digest(current["fingerprintWindow"])
            if current["partIndex"] == 1
            else ""
        ),
        "Body Format": storage.BODY_FORMAT,
        "Part Index": current["partIndex"],
        "Part Count": current["partCount"],
        "Feed Success Count": success_count,
        "Feed Failure Count": len(current["sourceOutcomes"]) - success_count,
        "New Item Count": current["newItemCount"],
        "Item Count": len(current["items"]),
        "Fetched At": current["fetchedAt"],
        "All Sources Failed": success_count == 0,
        "Created At": "2026-08-10T02:00:01Z",
        "Run": [RUN_PAGE_ID],
        "body": storage.encode_notion_body(current),
        "payload": current,
    }
    expected = deepcopy(page)
    return page, expected


def valid_report_payload() -> dict:
    return {
        "schemaVersion": 2,
        "title": "World Memory",
        "asOf": "2026-08-10T02:00:00Z",
        "coverage": "six hours",
        "dataQuality": {"gaps": []},
        "stance": "neutral",
        "confidence": 0.7,
        "summary": "요약",
        "narrative": "서사",
        "changesSincePrevious": [],
        "signalRadar": [],
        "highlights": [],
        "memoryChangeSuggestions": [],
        "portfolioSuggestions": [],
        "nextChecks": [],
        "sources": [],
        "scenarios": {
            name: {
                "activation": f"{name} 활성화",
                "transmission": f"{name} 전달",
                "invalidation": f"{name} 무효화",
                "nextCheck": f"{name} 다음 확인",
            }
            for name in ("기준", "낙관", "비관")
        },
    }


def report_page() -> tuple[dict, dict]:
    import hashlib

    payload = valid_report_payload()
    rendering = "## 한 줄 판단\n중립입니다."
    integration = f"wmi_{INSTALLATION_HASH}_genesis"
    key = f"{integration}:report:six-hour:{RUN_KEY}"
    page = {
        "page_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "Name": key,
        "Report Key": key,
        "Run Key": RUN_KEY,
        "Integration Key": integration,
        "Payload Digest": storage.canonical_digest(payload),
        "Rendering Digest": hashlib.sha256(rendering.encode("utf-8")).hexdigest(),
        "Body Format": storage.BODY_FORMAT,
        "Report Type": "six-hour",
        "As Of": "2026-08-10T02:00:00Z",
        "Coverage Start": "2026-08-09T20:00:00Z",
        "Coverage End": "2026-08-10T02:00:00Z",
        "Stance": "neutral",
        "Confidence": 0.7,
        "Data Gap Count": 0,
        "Material Change": True,
        "User Visible": True,
        "Created At": "2026-08-10T02:00:03Z",
        "Run": [RUN_PAGE_ID],
        "Evidence Records": [],
        "body": storage.encode_notion_body(payload, rendering),
        "payload": payload,
        "rendering": rendering,
    }
    return page, deepcopy(page)


def hourly_report_page() -> tuple[dict, dict]:
    page, _expected = report_page()
    page.update(
        {
            "Name": "Hourly briefing",
            "Report Key": storage.report_key(RUN_KEY, "hourly-briefing"),
            "Integration Key": "",
            "Report Type": "hourly-briefing",
            "Coverage Start": "",
        }
    )
    return page, deepcopy(page)


def memory_payload() -> dict:
    evidence = [{
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/example",
    }]
    return {
        "schemaVersion": 2,
        "kind": "memory",
        "recordType": "state",
        "action": "state-add",
        "target": "rates-policy-state",
        "evidence": evidence,
        "sources": evidence,
        "confidence": 0.8,
        "result": {"observed": "state recorded"},
        "state_key": "rates-policy-state",
        "recordStatus": "active",
        "importance": "high",
        "category": "stock_bond",
        "region": "US",
        "effectiveAt": "2026-08-10T02:00:00Z",
    }


def memory_page() -> tuple[dict, dict]:
    payload = memory_payload()
    record = storage.memory_record_key("state", payload)
    key = storage.revision_key(record, 1, RUN_KEY)
    page = {
        "page_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "Name": key,
        "Record Key": record,
        "Revision Key": key,
        "Run Key": RUN_KEY,
        "Dedupe Key": "",
        "Continuity ID": "",
        "Target": payload["target"],
        "Payload Digest": storage.canonical_digest(payload),
        "Body Format": storage.BODY_FORMAT,
        "Record Type": "state",
        "Record Status": "active",
        "Importance": "high",
        "Category": "stock_bond",
        "Region": "US",
        "Action": "state-add",
        "Revision": 1,
        "Confidence": 0.8,
        "Effective At": "2026-08-10T02:00:00Z",
        "Verified Evidence": True,
        "Created At": "2026-08-10T02:00:03Z",
        "Updated At": "2026-08-10T02:00:03Z",
        "Run": [RUN_PAGE_ID],
        "Supersedes": [],
        "body": storage.encode_notion_body(payload),
        "payload": payload,
    }
    return page, deepcopy(page)


def run_audit(*pages: dict) -> dict:
    inventory = {"feed": [], "memory": [], "report": []}
    for page in pages:
        if "Batch Key" in page:
            inventory["feed"].append({
                "key": page["Batch Key"],
                "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
                "fingerprintWindowDigest": page["Fingerprint Window Digest"],
            })
        elif "Revision Key" in page:
            inventory["memory"].append({
                "key": page["Revision Key"],
                "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
            })
        else:
            inventory["report"].append({
                "key": page["Report Key"],
                "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
                "renderingDigest": page["Rendering Digest"],
            })
    for rows in inventory.values():
        rows.sort(key=lambda row: row["key"])
    feed_pages = [page for page in pages if "Batch Key" in page]
    if feed_pages:
        feed_payload_value = feed_pages[0]["payload"]
        outcomes = deepcopy(feed_payload_value["sourceOutcomes"])
        new_item_count = feed_payload_value["newItemCount"]
    else:
        outcomes = source_outcomes(failed=FEED_IDS)
        new_item_count = 0
    success_count = sum(outcome["status"] == "ok" for outcome in outcomes)
    return {
        "timestamp": "2026-08-10T02:00:02Z",
        "trigger": "scheduled",
        "feed": {
            "sourceOutcomes": outcomes,
            "successCount": success_count,
            "failureCount": len(outcomes) - success_count,
            "newItemCount": new_item_count,
        },
        "materialChange": {},
        "worldMemory": {},
        "notification": {},
        "audit": {"expectedChildren": inventory},
        "commit": {},
    }


def precommit_bundle(*pages: dict, include_default_report: bool = True) -> dict:
    prepared_pages = list(pages)
    has_feed = any("Batch Key" in page for page in prepared_pages)
    has_memory = any("Revision Key" in page for page in prepared_pages)
    has_report = any("Report Key" in page for page in prepared_pages)
    if include_default_report and has_feed and not has_report:
        default_report, _expected = (
            report_page() if has_memory else hourly_report_page()
        )
        if not has_memory:
            default_report["Material Change"] = False
        prepared_pages.append(default_report)

    children = {"feed": [], "memory": [], "report": []}
    child_ids = {"feed": {}, "memory": {}, "report": {}}
    child_pages = {"feed": {}, "memory": {}, "report": {}}
    physical = {
        "feed": "Batch Key",
        "memory": "Revision Key",
        "report": "Report Key",
    }
    for page in prepared_pages:
        kind = (
            "feed" if "Batch Key" in page
            else "memory" if "Revision Key" in page
            else "report"
        )
        key = page[physical[kind]]
        children[kind].append(deepcopy(page))
        child_ids[kind][key] = page["page_id"]
        child_pages[kind][key] = deepcopy(page)
    feeds = children["feed"]
    first_feed = feeds[0] if feeds else None
    success_count = first_feed["Feed Success Count"] if first_feed else 0
    failure_count = first_feed["Feed Failure Count"] if first_feed else 0
    new_count = first_feed["New Item Count"] if first_feed else 0
    six_hour_reports = [
        page for page in children["report"] if page.get("Report Type") == "six-hour"
    ]
    visible_reports = children["report"]
    integration = (
        six_hour_reports[0]["Integration Key"] if six_hour_reports else ""
    )
    run = parent_run(
        **{
            "Integration Key": integration,
            "Feed Success Count": success_count,
            "Feed Failure Count": failure_count,
            "New Item Count": new_count,
            "Material Change": any(
                page.get("Material Change") is True for page in visible_reports
            ),
            "Integration Due": bool(six_hour_reports),
            "Integration Performed": bool(six_hour_reports),
            "Notification Plan": (
                "six-hour" if six_hour_reports
                else "hourly-briefing" if visible_reports
                else "silent"
            ),
            "body": storage.encode_notion_body(run_audit(*prepared_pages)),
        }
    )
    return {
        "slot_rows": [deepcopy(run)],
        "exact_run_rows": [deepcopy(run)],
        "expected_run_page_id": RUN_PAGE_ID,
        "child_rows_by_kind": children,
        "expected_child_ids": child_ids,
        "memory_logical_rows": deepcopy(children["memory"]),
        "parent_status_by_id": {RUN_PAGE_ID: "preparing"},
        "report_logical_rows": deepcopy(six_hour_reports),
        "integration_rows": [deepcopy(run)] if six_hour_reports else [],
        "expected_child_pages_by_kind": child_pages,
        "expected_run_snapshot": {
            key: deepcopy(value)
            for key, value in run.items()
            if key != "page_id"
        },
        "installation_snapshot": installation(),
    }


def cache_run(
    run_key: str,
    cutoff: str,
    *,
    integration_key: str = "",
    integration_performed: bool = False,
    outcomes: dict[str, dict] | None = None,
) -> dict:
    return {
        "Run Key": run_key,
        "Status": "committed",
        "Collection Cutoff": cutoff,
        "Finished At": cutoff,
        "Integration Key": integration_key,
        "Integration Performed": integration_performed,
        "Notification Plan": "silent",
        "sourceOutcomes": mapped_outcomes() if outcomes is None else outcomes,
    }


class InstallationAndAuthorityTests(unittest.TestCase):
    def test_raw_installation_validator_binds_registry_and_canonical_cursor_text(self):
        raw = installation(**{"Feed Cursor State": "{}"})
        self.assertEqual(
            scheduler.validate_installation_row(
                raw,
                INSTALLATION_KEY,
                HUB_PAGE_ID,
                raw["Hub URL"],
            ),
            [],
        )
        for cursor in ({}, "{ }", '{"unknown":""}'):
            with self.subTest(cursor=cursor):
                changed = {**raw, "Feed Cursor State": cursor}
                self.assertTrue(
                    scheduler.validate_installation_row(
                        changed,
                        INSTALLATION_KEY,
                        HUB_PAGE_ID,
                        raw["Hub URL"],
                    )
                )
        self.assertTrue(
            scheduler.validate_installation_row(
                raw,
                INSTALLATION_KEY,
                HUB_PAGE_ID,
                "https://www.notion.so/different-hub",
            )
        )

    def test_raw_installation_rejects_duplicate_nonobject_and_bad_cursor_json(self):
        raw = installation(**{"Feed Cursor State": "{}"})
        invalid_cursor_texts = (
            '{"financial_juice":"","financial_juice":""}',
            "[]",
            '{"financial_juice":"UPPERCASE"}',
        )
        for cursor_text in invalid_cursor_texts:
            with self.subTest(cursor_text=cursor_text):
                changed = {**raw, "Feed Cursor State": cursor_text}
                self.assertTrue(
                    scheduler.validate_installation_row(
                        changed, INSTALLATION_KEY, HUB_PAGE_ID, raw["Hub URL"]
                    )
                )
        self.assertTrue(
            scheduler.validate_installation_row(
                raw,
                "wm:00000000-0000-4000-8000-000000000000:default",
                HUB_PAGE_ID,
                raw["Hub URL"],
            )
        )

    def test_installation_validators_do_not_mutate_observed_rows(self):
        normalized = installation()
        normalized_before = deepcopy(normalized)
        scheduler.validate_operational_installation(normalized)
        self.assertEqual(normalized, normalized_before)

        raw = installation(**{"Feed Cursor State": "{}"})
        raw_before = deepcopy(raw)
        scheduler.validate_installation_row(
            raw, INSTALLATION_KEY, HUB_PAGE_ID, raw["Hub URL"]
        )
        self.assertEqual(raw, raw_before)

    def test_operational_installation_requires_exact_complete_row(self):
        self.assertEqual(
            scheduler.validate_operational_installation(installation()),
            installation(),
        )
        invalid_rows = []
        for field in (
            "page_id",
            "Name",
            "Installation Key",
            "Hub Page ID",
            "Hub URL",
            "Timezone",
            "Hourly Interval Minutes",
            "World Memory Interval Hours",
            "Schema Version",
            "Skill Contract Version",
            "Created At",
            "Updated At",
        ):
            row = installation()
            row.pop(field)
            invalid_rows.append(row)
        invalid_rows.extend(
            (
                installation(Name="not-the-installation-key"),
                installation(**{"Installation Key": "wm:not-a-uuid:default"}),
                installation(**{"Hub Page ID": "https://www.notion.so/not-a-page-id"}),
                installation(Timezone="UTC"),
                installation(**{"Hourly Interval Minutes": True}),
                installation(**{"World Memory Interval Hours": 5}),
                installation(**{"Schema Version": 1}),
                installation(**{"Skill Contract Version": "legacy"}),
                installation(**{"Created At": "2026-08-10T01:00Z"}),
                installation(**{"Updated At": "2026-08-10 01:00:00Z"}),
                installation(
                    **{
                        "Name": f"wm:{WORKSPACE_ID.upper()}:default",
                        "Installation Key": f"wm:{WORKSPACE_ID.upper()}:default",
                    }
                ),
                installation(Runs=["opaque-page-id"]),
                {**installation(), "unexpected": "field"},
            )
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    scheduler.validate_operational_installation(row)
        without_runs = installation()
        without_runs.pop("Runs")
        self.assertEqual(
            scheduler.validate_operational_installation(without_runs), without_runs
        )
        fractional = installation(
            **{
                "Created At": "2026-08-10T01:00:00.123Z",
                "Updated At": "2026-08-10T01:00:00.123456Z",
            }
        )
        self.assertEqual(
            scheduler.validate_operational_installation(fractional), fractional
        )

    def test_run_policy_requires_complete_normalized_operational_installation(self):
        incomplete = installation()
        incomplete.pop("Schema Version")
        with self.assertRaisesRegex(ValueError, "Schema Version"):
            scheduler.run_policy(incomplete, "manual", registry_valid=True)

        malformed = installation(**{"Feed Cursor State": {"financial_juice": "BAD"}})
        with self.assertRaisesRegex(ValueError, "Cursor"):
            scheduler.run_policy(malformed, "manual", registry_valid=True)

        # Registry invalidity takes precedence and cannot leak malformed row details.
        self.assertEqual(
            scheduler.run_policy(incomplete, "manual", registry_valid=False)["reason"],
            "registry-invalid",
        )

    def test_committed_runs_are_the_only_integration_gate_authority(self):
        stale_cache = installation(
            **{"Last World Memory Success": "2026-08-10T00:00:00Z"}
        )
        self.assertEqual(scheduler.effective_last_integration(stale_cache, []), "")
        self.assertTrue(
            scheduler.world_memory_due(
                stale_cache,
                [],
                utc("2026-08-10T01:00:00Z"),
                "scheduled",
            )
        )

    def test_committed_nonintegration_run_cannot_claim_an_integration_key(self):
        contradictory = cache_run(
            "run-one",
            "2026-08-10T02:00:00Z",
            integration_key=f"wmi_{INSTALLATION_HASH}_genesis",
            integration_performed=False,
        )
        with self.assertRaisesRegex(ValueError, "Integration Key"):
            scheduler.effective_last_integration(installation(), [contradictory])

    def test_cache_projection_requires_exactly_five_source_outcomes(self):
        current = installation()
        row = cache_run("run-one", "2026-08-10T02:00:00Z")
        row["sourceOutcomes"].pop("unusual_whales")
        with self.assertRaisesRegex(ValueError, "configured sources"):
            scheduler.reconcile_installation_cache(current, row, [row])

    def test_cache_projection_rejects_duplicate_committed_integration_identity(self):
        key = f"wmi_{INSTALLATION_HASH}_genesis"
        first = cache_run(
            "run-one",
            "2026-08-10T00:00:00Z",
            integration_key=key,
            integration_performed=True,
        )
        second = cache_run(
            "run-two",
            "2026-08-10T01:00:00Z",
            integration_key=key,
            integration_performed=True,
        )
        with self.assertRaisesRegex(ValueError, "duplicate committed Integration Key"):
            scheduler.reconcile_installation_cache(
                installation(), second, [first, second]
            )

    def test_malformed_advisory_cache_does_not_block_authority_or_repair(self):
        key = f"wmi_{INSTALLATION_HASH}_genesis"
        row = cache_run(
            "run-one",
            "2026-08-10T02:00:00Z",
            integration_key=key,
            integration_performed=True,
        )
        row["sourceOutcomes"]["financial_juice"]["cursor"] = "a" * 64
        malformed = installation(
            **{
                "Feed Cursor State": {"financial_juice": "MALFORMED"},
                "Last World Memory Success": "not-a-time",
            }
        )
        self.assertEqual(
            scheduler.effective_last_integration(malformed, [row]),
            "2026-08-10T02:00:00Z",
        )
        repaired = scheduler.reconcile_installation_cache(malformed, row, [row])
        self.assertEqual(repaired["Feed Cursor State"], {"financial_juice": "a" * 64})
        self.assertEqual(repaired["Last World Memory Success"], "2026-08-10T02:00:00Z")


class SlotAndRelationTests(unittest.TestCase):
    def test_slot_key_rejects_unhashable_trigger_as_value_error(self):
        for trigger in ([], {}):
            with self.subTest(trigger=trigger):
                with self.assertRaisesRegex(ValueError, "trigger"):
                    storage.slot_key(
                        INSTALLATION_KEY,
                        trigger,
                        utc("2026-08-10T02:00:00Z"),
                    )

    def test_slot_resolution_requires_installation_relation_and_bound_integration(self):
        missing_relation = parent_run(Status="committed")
        missing_relation.pop("Installation")
        foreign_integration = parent_run(
            Status="committed",
            **{"Integration Key": "wmi_000000000000_genesis"},
        )
        for row in (missing_relation, foreign_integration):
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, "Installation|Integration"):
                    storage.resolve_slot_runs(
                        [row],
                        SLOT_KEY,
                        utc("2026-08-10T02:01:00Z"),
                        installation_key=INSTALLATION_KEY,
                        installation_page_id=INSTALLATION_PAGE_ID,
                    )

    def test_slot_resolution_rejects_unhashable_status_as_validation_error(self):
        with self.assertRaisesRegex(ValueError, "Status"):
            storage.resolve_slot_runs(
                [parent_run(Status=[])],
                SLOT_KEY,
                utc("2026-08-10T02:01:00Z"),
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )

    def test_slot_resolution_binds_started_at_to_the_slot_instant(self):
        row = parent_run(
            Status="committed",
            **{"Started At": "2026-08-10T01:00:00Z"},
        )
        with self.assertRaisesRegex(ValueError, "Started At"):
            storage.resolve_slot_runs(
                [row],
                SLOT_KEY,
                utc("2026-08-10T02:01:00Z"),
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )

    def test_slot_resolution_rejects_noncanonical_or_future_started_at(self):
        base = {
            "page_id": RUN_PAGE_ID,
            "Name": RUN_KEY,
            "Slot Key": SLOT_KEY,
            "Run Key": RUN_KEY,
            "Attempt": 1,
            "Trigger": "scheduled",
            "Status": "preparing",
            "Started At": "2026-08-10T01:00:00Z",
            "Scheduled Slot": "2026-08-10T02:00:00Z",
            "Installation": [INSTALLATION_PAGE_ID],
            "Integration Key": "",
        }
        for value in (
            "2026-08-10T01:00:00+00:00",
            "2026-08-10T01:00:00.000Z",
            "2026-08-10T03:00:00Z",
        ):
            with self.subTest(started_at=value):
                row = {**base, "Started At": value}
                with self.assertRaisesRegex(ValueError, "Started At"):
                    storage.resolve_slot_runs(
                        [row],
                        SLOT_KEY,
                        utc("2026-08-10T02:00:00Z"),
                        installation_key=INSTALLATION_KEY,
                        installation_page_id=INSTALLATION_PAGE_ID,
                    )

    def test_slot_resolution_requires_observed_name_trigger_and_scheduled_slot(self):
        base = {
            "page_id": RUN_PAGE_ID,
            "Name": RUN_KEY,
            "Slot Key": SLOT_KEY,
            "Run Key": RUN_KEY,
            "Attempt": 1,
            "Trigger": "scheduled",
            "Status": "committed",
            "Started At": "2026-08-10T02:00:00Z",
            "Scheduled Slot": "2026-08-10T02:00:00Z",
            "Installation": [INSTALLATION_PAGE_ID],
            "Integration Key": "",
        }
        for field in ("Name", "Trigger", "Scheduled Slot"):
            with self.subTest(field=field):
                row = deepcopy(base)
                row.pop(field)
                with self.assertRaisesRegex(ValueError, field):
                    storage.resolve_slot_runs(
                        [row],
                        SLOT_KEY,
                        utc("2026-08-10T02:01:00Z"),
                        installation_key=INSTALLATION_KEY,
                        installation_page_id=INSTALLATION_PAGE_ID,
                    )

    def test_slot_resolution_binds_slot_hash_trigger_and_instant_to_installation(self):
        wrong_slot = "wms_000000000000_scheduled_20260810T020000Z"
        row = {
            "page_id": RUN_PAGE_ID,
            "Slot Key": wrong_slot,
            "Run Key": f"{wrong_slot}_a001",
            "Attempt": 1,
            "Trigger": "scheduled",
            "Scheduled Slot": "2026-08-10T02:00:00Z",
            "Started At": "2026-08-10T02:00:00Z",
            "Status": "committed",
        }
        with self.assertRaisesRegex(ValueError, "Installation Key"):
            storage.resolve_slot_runs(
                [row],
                wrong_slot,
                utc("2026-08-10T02:01:00Z"),
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )

    def test_child_and_relation_page_ids_must_parse_as_uuids(self):
        page, _expected = feed_page()
        page["Run"] = ["https://www.notion.so/not-a-page-id"]
        errors = storage.verify_child_set(
            {page["Batch Key"]}, [page], RUN_PAGE_ID
        )
        self.assertTrue(any("UUID" in error or "page ID" in error for error in errors))

        page, _expected = feed_page()
        page["page_id"] = "feed-page-alias"
        errors = storage.verify_child_set(
            {page["Batch Key"]}, [page], RUN_PAGE_ID
        )
        self.assertTrue(any("UUID" in error or "page_id" in error for error in errors))

        opaque = {
            "page_id": "child-alias",
            "Batch Key": "batch",
            "Run": ["parent-alias"],
        }
        with self.assertRaisesRegex(ValueError, "UUID"):
            storage._single_parent_id(opaque)

        valid_page, _expected = feed_page()
        errors = storage.verify_child_set(
            {valid_page["Batch Key"]}, [valid_page], "parent-alias"
        )
        self.assertTrue(any("expected parent" in error for error in errors))

    def test_valid_uuid_observations_are_compared_without_normalization(self):
        undashed = INSTALLATION_PAGE_ID.replace("-", "")
        current_installation = installation(page_id=undashed)
        run = parent_run(Installation=[undashed])
        page, expected = feed_page()
        page["Run"] = [RUN_PAGE_ID.replace("-", "")]
        expected = deepcopy(page)
        run["page_id"] = RUN_PAGE_ID.replace("-", "")
        self.assertEqual(
            storage.validate_child_page(
                "feed", page, expected, run, current_installation
            ),
            [],
        )

    def test_direct_child_validation_requires_complete_installation_snapshot(self):
        page, expected = feed_page()
        for incomplete_installation in (
            {
                "page_id": INSTALLATION_PAGE_ID,
                "Installation Key": INSTALLATION_KEY,
            },
            {"page_id": INSTALLATION_PAGE_ID},
        ):
            with self.subTest(incomplete_installation=incomplete_installation):
                errors = storage.validate_child_page(
                    "feed", page, expected, parent_run(), incomplete_installation
                )
                self.assertTrue(
                    any("Installation" in error for error in errors), errors
                )

    def test_run_name_is_a_nonempty_frozen_label_not_a_derived_key(self):
        row = parent_run(Name="Human-readable run title", Status="committed")
        result = storage.resolve_slot_runs(
            [row],
            SLOT_KEY,
            utc("2026-08-10T02:01:00Z"),
            installation_key=INSTALLATION_KEY,
            installation_page_id=INSTALLATION_PAGE_ID,
        )
        self.assertEqual(result["action"], "reuse-committed")
        page, expected = feed_page()
        self.assertEqual(
            storage.validate_child_page(
                "feed", page, expected, parent_run(Name="Readable"), installation()
            ),
            [],
        )


class FeedIntegrityTests(unittest.TestCase):
    def test_later_part_item_cannot_be_published_after_batch_fetch(self):
        payload = feed_payload(
            items=[feed_item(published_at="2026-08-10T02:00:01Z")]
        )
        payload.update(
            {
                "batchKey": f"{RUN_KEY}:feed:002",
                "partIndex": 2,
                "partCount": 2,
            }
        )
        payload.pop("fingerprintWindow")
        page, _expected = feed_page()
        page.update(
            {
                "Name": payload["batchKey"],
                "Batch Key": payload["batchKey"],
                "Payload Digest": storage.canonical_digest(payload),
                "Fingerprint Window Digest": "",
                "Part Index": 2,
                "Part Count": 2,
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }
        )
        errors = storage.validate_child_page(
            "feed", page, deepcopy(page), parent_run(), installation()
        )
        self.assertTrue(any("publishedAt" in error for error in errors), errors)

    def test_feed_expected_snapshot_requires_every_notion_property(self):
        page, expected = feed_page()
        for missing in ("Name", "Created At"):
            with self.subTest(missing=missing):
                incomplete = deepcopy(expected)
                incomplete.pop(missing)
                errors = storage.validate_child_page(
                    "feed",
                    page,
                    incomplete,
                    parent_run(),
                    installation(),
                )
                self.assertTrue(any("snapshot" in error for error in errors))

    def test_fetched_child_snapshot_rejects_missing_or_unexpected_properties(self):
        page, expected = feed_page()
        missing = deepcopy(page)
        missing.pop("Created At")
        self.assertTrue(
            storage.validate_child_page(
                "feed", missing, expected, parent_run(), installation()
            )
        )
        extra = {**page, "Unexpected Property": "schema drift"}
        self.assertTrue(
            storage.validate_child_page(
                "feed", extra, expected, parent_run(), installation()
            )
        )

    def test_strict_child_validation_does_not_mutate_snapshots(self):
        page, expected = feed_page()
        values = (page, expected, parent_run(), installation())
        before = deepcopy(values)
        self.assertEqual(storage.validate_child_page("feed", *values), [])
        self.assertEqual(values, before)

    def test_all_sources_failed_payload_cannot_be_a_committed_child(self):
        payload = feed_payload(items=[], outcomes=source_outcomes(failed=FEED_IDS))
        page, expected = feed_page(payload)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("all sources failed" in error for error in errors))

    def test_child_scalar_and_payload_run_keys_must_match_parent_run_key(self):
        page, expected = feed_page()
        wrong = RUN_KEY.replace("_a001", "_a002")
        payload = deepcopy(page["payload"])
        payload["runKey"] = wrong
        payload["batchKey"] = f"{wrong}:feed:001"
        page.update(
            {
                "Name": payload["batchKey"],
                "Batch Key": payload["batchKey"],
                "Run Key": wrong,
                "Payload Digest": storage.canonical_digest(payload),
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }
        )
        expected = deepcopy(page)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("parent Run Key" in error for error in errors))

    def test_feed_items_require_successful_observed_source_and_count_budget(self):
        failed_source = source_outcomes(failed=("financial_juice",))
        payload = feed_payload(outcomes=failed_source)
        page, expected = feed_page(payload)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("successful source" in error for error in errors))

        insufficient = source_outcomes()
        insufficient[0]["itemCount"] = 0
        payload = feed_payload(outcomes=insufficient)
        page, expected = feed_page(payload)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("itemCount" in error for error in errors))

    def test_multipart_source_count_budget_is_cumulative(self):
        first = feed_item("8" * 64, published_at="2026-08-10T01:55:00Z")
        second = feed_item("9" * 64, published_at="2026-08-10T01:56:00Z")
        outcomes = source_outcomes()
        outcomes[0]["itemCount"] = 1
        complete_window = [
            {
                "sourceFingerprint": item["sourceFingerprint"],
                "publishedAt": item["publishedAt"],
            }
            for item in (first, second)
        ]
        part_one = feed_payload(
            items=[first], outcomes=outcomes, fingerprint_window=complete_window
        )
        part_one.update({"partCount": 2, "newItemCount": 2})
        part_two = {
            **part_one,
            "batchKey": f"{RUN_KEY}:feed:002",
            "partIndex": 2,
            "items": [second],
        }
        part_two.pop("fingerprintWindow")

        def page_for(payload: dict, page_id: str) -> dict:
            successes = sum(
                outcome["status"] == "ok" for outcome in payload["sourceOutcomes"]
            )
            return {
                "page_id": page_id,
                "Name": payload["batchKey"],
                "Batch Key": payload["batchKey"],
                "Run Key": payload["runKey"],
                "Payload Digest": storage.canonical_digest(payload),
                "Fingerprint Window Digest": (
                    storage.canonical_digest(payload["fingerprintWindow"])
                    if payload["partIndex"] == 1
                    else ""
                ),
                "Body Format": storage.BODY_FORMAT,
                "Part Index": payload["partIndex"],
                "Part Count": payload["partCount"],
                "Feed Success Count": successes,
                "Feed Failure Count": len(payload["sourceOutcomes"]) - successes,
                "New Item Count": payload["newItemCount"],
                "Item Count": len(payload["items"]),
                "Fetched At": payload["fetchedAt"],
                "All Sources Failed": False,
                "Created At": "2026-08-10T02:00:01Z",
                "Run": [RUN_PAGE_ID],
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }

        result = storage.load_or_rebuild_fingerprint_window(
            [],
            [
                page_for(part_one, FEED_PAGE_ID),
                page_for(part_two, "ffffffff-ffff-4fff-8fff-ffffffffffff"),
            ],
            {RUN_PAGE_ID},
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertTrue(any("itemCount" in error for error in result["errors"]), result)

    def test_item_fetch_time_and_window_are_bound_to_the_batch(self):
        mismatched_item = feed_item(fetched_at="2026-08-10T01:59:59Z")
        payload = feed_payload(items=[mismatched_item])
        page, expected = feed_page(payload)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("fetchedAt" in error for error in errors))

        item = feed_item()
        payload = feed_payload(items=[item], fingerprint_window=[])
        page, expected = feed_page(payload)
        errors = storage.validate_child_page(
            "feed", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("fingerprintWindow" in error for error in errors))

    def test_part_one_window_covers_items_from_every_part(self):
        first = feed_item("6" * 64, published_at="2026-08-10T01:55:00Z")
        second = feed_item("7" * 64, published_at="2026-08-10T01:56:00Z")
        outcomes = source_outcomes()
        outcomes[0]["itemCount"] = 2
        part_one = feed_payload(
            items=[first],
            outcomes=outcomes,
            fingerprint_window=[{
                "sourceFingerprint": first["sourceFingerprint"],
                "publishedAt": first["publishedAt"],
            }],
        )
        part_one["partCount"] = 2
        part_one["newItemCount"] = 2
        part_two = {
            **part_one,
            "batchKey": f"{RUN_KEY}:feed:002",
            "partIndex": 2,
            "items": [second],
        }
        part_two.pop("fingerprintWindow")

        def page_for(payload: dict, page_id: str) -> dict:
            successes = sum(
                outcome["status"] == "ok" for outcome in payload["sourceOutcomes"]
            )
            return {
                "page_id": page_id,
                "Name": payload["batchKey"],
                "Batch Key": payload["batchKey"],
                "Run Key": payload["runKey"],
                "Payload Digest": storage.canonical_digest(payload),
                "Fingerprint Window Digest": (
                    storage.canonical_digest(payload["fingerprintWindow"])
                    if payload["partIndex"] == 1
                    else ""
                ),
                "Body Format": storage.BODY_FORMAT,
                "Part Index": payload["partIndex"],
                "Part Count": payload["partCount"],
                "Feed Success Count": successes,
                "Feed Failure Count": len(payload["sourceOutcomes"]) - successes,
                "New Item Count": payload["newItemCount"],
                "Item Count": len(payload["items"]),
                "Fetched At": payload["fetchedAt"],
                "All Sources Failed": False,
                "Created At": "2026-08-10T02:00:01Z",
                "Run": [RUN_PAGE_ID],
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }

        result = storage.load_or_rebuild_fingerprint_window(
            [],
            [
                page_for(part_one, FEED_PAGE_ID),
                page_for(part_two, "dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            ],
            {RUN_PAGE_ID},
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertTrue(
            any("every part" in error for error in result["errors"]),
            result,
        )

    def test_window_rejects_conflicting_fingerprint_observations(self):
        fingerprint = "2" * 64
        conflicting = [
            {
                "sourceFingerprint": fingerprint,
                "publishedAt": "2026-08-10T01:00:00Z",
            },
            {
                "sourceFingerprint": fingerprint,
                "publishedAt": "2026-08-10T01:01:00Z",
            },
        ]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            storage.advance_fingerprint_window([], conflicting)

    def test_window_rejects_future_publication_observations(self):
        future = [{
            "sourceFingerprint": "2" * 64,
            "publishedAt": "2026-08-10T03:00:00Z",
        }]
        with self.assertRaisesRegex(ValueError, "future"):
            storage.advance_fingerprint_window(
                [], future, observed_at=utc("2026-08-10T02:00:00Z")
            )

    def test_checkpoint_loader_uses_recent_horizon_and_only_latest_old_seed(self):
        def checkpoint(
            fetched_at: str,
            fingerprint: str,
            page_id: str,
            parent_id: str,
        ) -> dict:
            payload = feed_payload(
                items=[],
                fetched_at=fetched_at,
                fingerprint_window=[{
                    "sourceFingerprint": fingerprint,
                    "publishedAt": fetched_at,
                }],
            )
            payload["runKey"] = f"{RUN_KEY}-checkpoint-{fingerprint[0]}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = page_id
            page["Run"] = [parent_id]
            return page

        parent_ids = (
            "31313131-3131-4313-8313-313131313131",
            "32323232-3232-4323-8323-323232323232",
            "33333333-3333-4333-8333-333333333333",
        )
        old = checkpoint(
            "2026-08-09T10:00:00Z",
            "3" * 64,
            "34343434-3434-4343-8343-343434343434",
            parent_ids[0],
        )
        latest_old = checkpoint(
            "2026-08-09T13:00:00Z",
            "4" * 64,
            "35353535-3535-4353-8353-353535353535",
            parent_ids[1],
        )
        recent = checkpoint(
            "2026-08-10T01:00:00Z",
            "5" * 64,
            "36363636-3636-4363-8363-363636363636",
            parent_ids[2],
        )
        result = storage.load_or_rebuild_fingerprint_window(
            [old, latest_old, recent],
            [],
            set(parent_ids),
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertEqual(
            result["window"],
            [{"sourceFingerprint": "5" * 64, "publishedAt": "2026-08-10T01:00:00Z"}],
        )

        seeded = storage.load_or_rebuild_fingerprint_window(
            [old, latest_old],
            [],
            set(parent_ids),
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertEqual(
            seeded["window"],
            [{"sourceFingerprint": "4" * 64, "publishedAt": "2026-08-09T13:00:00Z"}],
        )

    def test_standalone_multipart_checkpoint_is_not_authoritative(self):
        incomplete = feed_payload(items=[], fingerprint_window=[])
        incomplete.update({"partCount": 2, "newItemCount": 0})
        incomplete_page, _expected = feed_page(incomplete)
        result = storage.load_or_rebuild_fingerprint_window(
            [incomplete_page],
            [],
            {RUN_PAGE_ID},
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertTrue(result["rebuilt"], result)
        self.assertTrue(any("incomplete" in error for error in result["errors"]), result)

    def test_checkpoint_authority_requires_complete_committed_feed_rows(self):
        now = utc("2026-08-10T02:00:00Z")

        def checkpoint_payload(
            fingerprint: str,
            *,
            fetched_at: str = "2026-08-10T01:00:00Z",
        ) -> dict:
            return feed_payload(
                items=[],
                fetched_at=fetched_at,
                fingerprint_window=[{
                    "sourceFingerprint": fingerprint,
                    "publishedAt": fetched_at,
                }],
            )

        def checkpoint_row(
            payload: dict,
            *,
            page_id: str = FEED_PAGE_ID,
            run_relation: list[str] | None = None,
        ) -> dict:
            page, _expected = feed_page(payload)
            page["page_id"] = page_id
            page["Run"] = [RUN_PAGE_ID] if run_relation is None else run_relation
            return page

        raw = checkpoint_payload("d" * 64)
        with self.subTest(case="detached raw payload"):
            result = storage.load_or_rebuild_fingerprint_window(
                [raw], [], set(), now
            )
            self.assertNotIn(
                "d" * 64,
                {entry["sourceFingerprint"] for entry in result["window"]},
                result,
            )
            self.assertTrue(result["rebuilt"], result)

        single = checkpoint_row(checkpoint_payload("e" * 64))
        with self.subTest(case="uncommitted row"):
            result = storage.load_or_rebuild_fingerprint_window(
                [single], [], set(), now
            )
            self.assertEqual(result["window"], [], result)
            self.assertEqual(
                result["errors"], ["fingerprint-window-rebuilt"], result
            )

        with self.subTest(case="mixed committed and unreadable uncommitted row"):
            uncommitted = deepcopy(single)
            uncommitted.update(
                {
                    "page_id": "31313131-3131-4313-8313-313131313131",
                    "Run": ["32323232-3232-4323-8323-323232323232"],
                    "body": "unreadable-uncommitted-body",
                }
            )
            result = storage.load_or_rebuild_fingerprint_window(
                [single, uncommitted], [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["errors"], [], result)
            self.assertFalse(result["rebuilt"], result)
            self.assertEqual(
                {entry["sourceFingerprint"] for entry in result["window"]},
                {"e" * 64},
                result,
            )

        with self.subTest(case="committed single-part row"):
            result = storage.load_or_rebuild_fingerprint_window(
                [single], [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["errors"], [], result)
            self.assertFalse(result["rebuilt"], result)
            self.assertEqual(
                {entry["sourceFingerprint"] for entry in result["window"]},
                {"e" * 64},
            )

        first_item = feed_item(
            "f" * 64,
            published_at="2026-08-10T01:10:00Z",
            fetched_at="2026-08-10T01:30:00Z",
        )
        second_item = feed_item(
            "0" * 64,
            published_at="2026-08-10T01:20:00Z",
            fetched_at="2026-08-10T01:30:00Z",
        )
        outcomes = source_outcomes()
        outcomes[0]["itemCount"] = 2
        complete_window = [
            {
                "sourceFingerprint": item["sourceFingerprint"],
                "publishedAt": item["publishedAt"],
            }
            for item in (first_item, second_item)
        ]
        part_one = feed_payload(
            items=[first_item],
            outcomes=outcomes,
            fetched_at="2026-08-10T01:30:00Z",
            fingerprint_window=complete_window,
        )
        part_one.update({"partCount": 2, "newItemCount": 2})
        part_two = {
            **part_one,
            "batchKey": f"{RUN_KEY}:feed:002",
            "partIndex": 2,
            "items": [second_item],
        }
        part_two.pop("fingerprintWindow")
        multipart = [
            checkpoint_row(part_one),
            checkpoint_row(
                part_two,
                page_id="abababab-abab-4aba-8aba-abababababab",
            ),
        ]

        with self.subTest(case="complete committed multipart rows"):
            result = storage.load_or_rebuild_fingerprint_window(
                multipart, [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["errors"], [], result)
            self.assertFalse(result["rebuilt"], result)
            self.assertEqual(
                {entry["sourceFingerprint"] for entry in result["window"]},
                {"f" * 64, "0" * 64},
            )

        with self.subTest(case="incomplete multipart rows"):
            result = storage.load_or_rebuild_fingerprint_window(
                multipart[:1], [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["window"], [], result)
            self.assertTrue(any("incomplete" in error for error in result["errors"]), result)

        malformed_relation = checkpoint_row(
            checkpoint_payload("1" * 64),
            run_relation=["opaque-parent"],
        )
        with self.subTest(case="malformed relation"):
            result = storage.load_or_rebuild_fingerprint_window(
                [malformed_relation], [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["window"], [], result)
            self.assertTrue(any("UUID" in error for error in result["errors"]), result)

        old_fetched_at = "2026-08-09T13:00:00Z"
        old_part_one = checkpoint_payload(
            "2" * 64, fetched_at=old_fetched_at
        )
        old_part_one.update({"partCount": 2, "newItemCount": 0})
        old_part_two = {
            **old_part_one,
            "batchKey": f"{RUN_KEY}:feed:002",
            "partIndex": 2,
        }
        old_part_two.pop("fingerprintWindow")
        old_multipart = [
            checkpoint_row(
                old_part_one,
                page_id="23232323-2323-4232-8232-232323232323",
            ),
            checkpoint_row(
                old_part_two,
                page_id="24242424-2424-4242-8242-242424242424",
            ),
        ]
        with self.subTest(case="complete old multipart seed"):
            result = storage.load_or_rebuild_fingerprint_window(
                old_multipart, [], {RUN_PAGE_ID}, now
            )
            self.assertFalse(result["rebuilt"], result)
            self.assertEqual(
                {entry["sourceFingerprint"] for entry in result["window"]},
                {"2" * 64},
            )
        with self.subTest(case="incomplete old multipart seed"):
            result = storage.load_or_rebuild_fingerprint_window(
                old_multipart[:1], [], {RUN_PAGE_ID}, now
            )
            self.assertEqual(result["window"], [], result)
            self.assertTrue(result["rebuilt"], result)

        tie_rows = []
        tie_parent_ids = (
            "25252525-2525-4252-8252-252525252525",
            "26262626-2626-4262-8262-262626262626",
        )
        for index, (fingerprint, parent_id) in enumerate(
            zip(("3" * 64, "4" * 64), tie_parent_ids), 1
        ):
            payload = checkpoint_payload(
                fingerprint, fetched_at=old_fetched_at
            )
            payload["runKey"] = f"{RUN_KEY}-tie-{index}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            tie_rows.append(
                checkpoint_row(
                    payload,
                    page_id=f"{index + 26:08d}-2727-4272-8272-272727272727",
                    run_relation=[parent_id],
                )
            )
        for order in (tie_rows, list(reversed(tie_rows))):
            with self.subTest(case="latest old tie union", order=order[0]["Run Key"]):
                result = storage.load_or_rebuild_fingerprint_window(
                    order, [], set(tie_parent_ids), now
                )
                self.assertEqual(
                    {entry["sourceFingerprint"] for entry in result["window"]},
                    {"3" * 64, "4" * 64},
                    result,
                )

        older_payload = checkpoint_payload(
            "5" * 64, fetched_at="2026-08-09T12:00:00Z"
        )
        older_payload["runKey"] = f"{RUN_KEY}-older"
        older_payload["batchKey"] = f"{older_payload['runKey']}:feed:001"
        older_row = checkpoint_row(
            older_payload,
            page_id="29292929-2929-4292-8292-292929292929",
            run_relation=[tie_parent_ids[0]],
        )
        with self.subTest(case="unique latest old seed"):
            result = storage.load_or_rebuild_fingerprint_window(
                [older_row, tie_rows[0]], [], {tie_parent_ids[0]}, now
            )
            self.assertEqual(
                {entry["sourceFingerprint"] for entry in result["window"]},
                {"3" * 64},
                result,
            )

    def test_fingerprint_loader_rejects_opaque_feed_page_id(self):
        page, _expected = feed_page()
        page["page_id"] = "opaque-feed-page"
        result = storage.load_or_rebuild_fingerprint_window(
            [], [page], {RUN_PAGE_ID}, utc("2026-08-10T02:00:00Z")
        )
        self.assertTrue(any("UUID" in error for error in result["errors"]), result)

    def test_authoritative_feed_page_ids_are_globally_unique(self):
        checkpoint_parent = "33333333-3333-4333-8333-333333333333"
        batch_parent = "34343434-3434-4343-8343-343434343434"

        def authoritative_row(
            *,
            suffix: str,
            fetched_at: str,
            fingerprint: str,
            parent_id: str,
            page_id: str,
        ) -> dict:
            payload = feed_payload(
                items=[],
                fetched_at=fetched_at,
                fingerprint_window=[{
                    "sourceFingerprint": fingerprint,
                    "publishedAt": fetched_at,
                }],
            )
            payload["runKey"] = f"{RUN_KEY}-{suffix}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = page_id
            page["Run"] = [parent_id]
            return page

        shared_page_id = "35353535-3535-4353-8353-353535353535"
        checkpoint = authoritative_row(
            suffix="unique-checkpoint",
            fetched_at="2026-08-10T01:00:00Z",
            fingerprint="a" * 64,
            parent_id=checkpoint_parent,
            page_id=shared_page_id,
        )
        batch = authoritative_row(
            suffix="unique-batch",
            fetched_at="2026-08-10T01:30:00Z",
            fingerprint="b" * 64,
            parent_id=batch_parent,
            page_id=shared_page_id,
        )
        committed = {checkpoint_parent, batch_parent}

        duplicate = storage.load_or_rebuild_fingerprint_window(
            [checkpoint], [batch], committed, utc("2026-08-10T02:00:00Z")
        )
        self.assertTrue(
            any("duplicate" in error and "page" in error for error in duplicate["errors"]),
            duplicate,
        )
        with self.assertRaisesRegex(ValueError, "duplicate.*page"):
            storage.merge_committed_feed_items(
                [checkpoint, batch],
                committed,
                utc("2026-08-10T00:00:00Z"),
                utc("2026-08-10T02:00:00Z"),
            )

        distinct_batch = deepcopy(batch)
        distinct_batch["page_id"] = "36363636-3636-4363-8363-363636363636"
        distinct = storage.load_or_rebuild_fingerprint_window(
            [checkpoint],
            [distinct_batch],
            committed,
            utc("2026-08-10T02:00:00Z"),
        )
        self.assertEqual(distinct["errors"], [], distinct)
        self.assertFalse(distinct["rebuilt"], distinct)
        self.assertEqual(
            storage.merge_committed_feed_items(
                [checkpoint, distinct_batch],
                committed,
                utc("2026-08-10T00:00:00Z"),
                utc("2026-08-10T02:00:00Z"),
            ),
            [],
        )

    def test_fingerprint_horizon_includes_both_boundaries_for_checkpoints_and_items(self):
        now = utc("2026-08-10T02:00:00Z")
        lower = "2026-08-09T14:00:00Z"
        upper = "2026-08-10T02:00:00Z"

        checkpoint_parent_ids = (
            "37373737-3737-4373-8373-373737373737",
            "38383838-3838-4383-8383-383838383838",
        )
        checkpoints = []
        for index, (instant, fingerprint) in enumerate(
            ((lower, "6" * 64), (upper, "7" * 64)), 1
        ):
            retained_group_entries = (
                [{"sourceFingerprint": "8" * 64, "publishedAt": lower}]
                if index == 1
                else [
                    {"sourceFingerprint": "8" * 64, "publishedAt": lower},
                    {"sourceFingerprint": "9" * 64, "publishedAt": upper},
                ]
            )
            payload = feed_payload(
                items=[], fetched_at=instant,
                fingerprint_window=sorted(
                    [{
                        "sourceFingerprint": fingerprint,
                        "publishedAt": instant,
                    }, *retained_group_entries],
                    key=lambda entry: (
                        entry["publishedAt"], entry["sourceFingerprint"]
                    ),
                ),
            )
            payload["runKey"] = f"{RUN_KEY}-checkpoint-boundary-{index}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = (
                f"{index + 38:08d}-3939-4393-8393-393939393939"
            )
            page["Run"] = [checkpoint_parent_ids[index - 1]]
            checkpoints.append(page)

        item_rows = []
        for index, (instant, fingerprint, parent_id) in enumerate((
            (lower, "8" * 64, "12121212-1212-4121-8121-121212121212"),
            (upper, "9" * 64, "13131313-1313-4131-8131-131313131313"),
        ), 1):
            item = feed_item(fingerprint=fingerprint, published_at=instant, fetched_at=instant)
            payload = feed_payload(items=[item], fetched_at=instant)
            payload["runKey"] = f"{RUN_KEY}-boundary-{index}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = parent_id
            page["Run"] = [RUN_PAGE_ID]
            item_rows.append(page)

        result = storage.load_or_rebuild_fingerprint_window(
            checkpoints,
            item_rows,
            {RUN_PAGE_ID, *checkpoint_parent_ids},
            now,
        )
        self.assertEqual(
            {entry["sourceFingerprint"] for entry in result["window"]},
            {"6" * 64, "7" * 64, "8" * 64, "9" * 64},
        )

    def test_checkpoint_stability_covers_only_prior_retained_group_items(self):
        now = utc("2026-08-10T02:00:00Z")

        def checkpoint_row(
            fetched_at: str,
            fingerprint_window: list[dict],
            *,
            suffix: str,
            page_id: str,
        ) -> dict:
            payload = feed_payload(
                items=[],
                fetched_at=fetched_at,
                fingerprint_window=fingerprint_window,
            )
            payload["runKey"] = f"{RUN_KEY}-{suffix}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = page_id
            return page

        def group_row(
            fingerprint: str,
            fetched_at: str,
            published_at: str,
            *,
            suffix: str,
            page_id: str,
        ) -> dict:
            item = feed_item(
                fingerprint,
                fetched_at=fetched_at,
                published_at=published_at,
            )
            payload = feed_payload(items=[item], fetched_at=fetched_at)
            payload["runKey"] = f"{RUN_KEY}-{suffix}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = page_id
            return page

        earlier_group = group_row(
            "6" * 64,
            "2026-08-10T00:30:00Z",
            "2026-08-10T00:25:00Z",
            suffix="earlier-group",
            page_id="46464646-4646-4464-8464-464646464646",
        )
        later_empty_checkpoint = checkpoint_row(
            "2026-08-10T01:00:00Z",
            [],
            suffix="later-empty-checkpoint",
            page_id="47474747-4747-4474-8474-474747474747",
        )
        rebuilt = storage.load_or_rebuild_fingerprint_window(
            [later_empty_checkpoint],
            [earlier_group],
            {RUN_PAGE_ID},
            now,
        )
        self.assertTrue(rebuilt["rebuilt"], rebuilt)
        self.assertTrue(any("unstable" in error for error in rebuilt["errors"]), rebuilt)
        self.assertIn(
            "6" * 64,
            {entry["sourceFingerprint"] for entry in rebuilt["window"]},
        )

        earlier_empty_checkpoint = checkpoint_row(
            "2026-08-10T00:30:00Z",
            [],
            suffix="earlier-empty-checkpoint",
            page_id="48484848-4848-4484-8484-484848484848",
        )
        later_group = group_row(
            "7" * 64,
            "2026-08-10T01:00:00Z",
            "2026-08-10T00:55:00Z",
            suffix="later-group",
            page_id="49494949-4949-4494-8494-494949494949",
        )
        stable = storage.load_or_rebuild_fingerprint_window(
            [earlier_empty_checkpoint],
            [later_group],
            {RUN_PAGE_ID},
            now,
        )
        self.assertFalse(stable["rebuilt"], stable)

        capped_window = [
            {
                "sourceFingerprint": f"{index:064x}",
                "publishedAt": "2026-08-10T00:59:00Z",
            }
            for index in range(2000)
        ]
        capped_checkpoint = checkpoint_row(
            "2026-08-10T01:00:00Z",
            capped_window,
            suffix="capped-checkpoint",
            page_id="50505050-5050-4505-8505-505050505050",
        )
        evicted_group = group_row(
            "f" * 64,
            "2026-08-09T15:00:00Z",
            "2026-08-09T14:59:00Z",
            suffix="evicted-group",
            page_id="51515151-5151-4515-8515-515151515151",
        )
        capped = storage.load_or_rebuild_fingerprint_window(
            [capped_checkpoint],
            [evicted_group],
            {RUN_PAGE_ID},
            now,
        )
        self.assertFalse(capped["rebuilt"], capped)
        self.assertEqual(capped["window"], capped_window)

    def test_fingerprint_loader_rejects_future_and_conflicting_observations(self):
        future_payload = feed_payload(
            items=[], fetched_at="2026-08-10T02:00:01Z",
            fingerprint_window=[{
                "sourceFingerprint": "a" * 64,
                "publishedAt": "2026-08-10T02:00:01Z",
            }],
        )
        future, _expected = feed_page(future_payload)
        result = storage.load_or_rebuild_fingerprint_window(
            [future], [], {RUN_PAGE_ID}, utc("2026-08-10T02:00:00Z")
        )
        self.assertTrue(any("future" in error for error in result["errors"]))

        conflict = []
        for index, instant in enumerate(
            ("2026-08-10T01:00:00Z", "2026-08-10T01:01:00Z"), 1
        ):
            payload = feed_payload(
                items=[], fetched_at=instant,
                fingerprint_window=[{
                    "sourceFingerprint": "b" * 64,
                    "publishedAt": instant,
                }],
            )
            payload["runKey"] = f"{RUN_KEY}-conflict-{index}"
            payload["batchKey"] = f"{payload['runKey']}:feed:001"
            page, _expected = feed_page(payload)
            page["page_id"] = (
                f"{index + 40:08d}-4141-4414-8414-414141414141"
            )
            conflict.append(page)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            storage.load_or_rebuild_fingerprint_window(
                conflict, [], {RUN_PAGE_ID}, utc("2026-08-10T02:00:00Z")
            )

    def test_fingerprint_rebuild_does_not_mutate_inputs(self):
        checkpoint_payload = feed_payload(
            items=[], fetched_at="2026-08-10T01:00:00Z",
            fingerprint_window=[{
                "sourceFingerprint": "c" * 64,
                "publishedAt": "2026-08-10T01:00:00Z",
            }],
        )
        checkpoint, _expected = feed_page(checkpoint_payload)
        checkpoints = [checkpoint]
        rows: list[dict] = []
        committed: set[str] = {RUN_PAGE_ID}
        before = deepcopy((checkpoints, rows, committed))
        storage.load_or_rebuild_fingerprint_window(
            checkpoints, rows, committed, utc("2026-08-10T02:00:00Z")
        )
        self.assertEqual((checkpoints, rows, committed), before)


class AuditMemoryAndReportTests(unittest.TestCase):
    def test_memory_and_report_fetched_snapshots_are_exact(self):
        for kind, factory in (("memory", memory_page), ("report", report_page)):
            page, expected = factory()
            for mutation in ("missing", "extra"):
                with self.subTest(kind=kind, mutation=mutation):
                    changed = deepcopy(page)
                    if mutation == "missing":
                        changed.pop("Created At")
                    else:
                        changed["Unexpected Property"] = "schema drift"
                    self.assertTrue(
                        storage.validate_child_page(
                            kind,
                            changed,
                            expected,
                            parent_run(),
                            installation(),
                        )
                    )

        system_times = (
            ("memory", memory_page, "Created At"),
            ("memory", memory_page, "Updated At"),
            ("report", report_page, "Created At"),
        )
        for kind, factory, field in system_times:
            with self.subTest(kind=kind, empty_system_time=field):
                page, _expected = factory()
                page[field] = ""
                self.assertTrue(
                    storage.validate_child_page(
                        kind,
                        page,
                        deepcopy(page),
                        parent_run(),
                        installation(),
                    )
                )
    def test_child_names_are_nonempty_frozen_labels_not_derived_keys(self):
        cases = (
            ("feed", feed_page),
            ("memory", memory_page),
            ("report", report_page),
        )
        for kind, factory in cases:
            with self.subTest(kind=kind):
                page, _expected = factory()
                page["Name"] = f"Human label for {kind}"
                self.assertEqual(
                    storage.validate_child_page(
                        kind,
                        page,
                        deepcopy(page),
                        parent_run(),
                        installation(),
                    ),
                    [],
                )

    def test_audit_requires_exact_child_inventory_with_unique_ids_and_digests(self):
        feed, _ = feed_page()
        memory, _ = memory_page()
        report, _ = report_page()
        audit = {
            "timestamp": "2026-08-10T02:00:02Z",
            "trigger": "scheduled",
            "feed": deepcopy(run_audit(feed)["feed"]),
            "materialChange": {},
            "worldMemory": {},
            "notification": {},
            "audit": {
                "expectedChildren": {
                    "feed": [{
                        "key": feed["Batch Key"],
                        "pageId": feed["page_id"],
                        "payloadDigest": feed["Payload Digest"],
                        "fingerprintWindowDigest": feed["Fingerprint Window Digest"],
                    }],
                    "memory": [{
                        "key": memory["Revision Key"],
                        "pageId": memory["page_id"],
                        "payloadDigest": memory["Payload Digest"],
                    }],
                    "report": [{
                        "key": report["Report Key"],
                        "pageId": report["page_id"],
                        "payloadDigest": report["Payload Digest"],
                        "renderingDigest": report["Rendering Digest"],
                    }],
                }
            },
            "commit": {},
        }
        self.assertEqual(contracts.validate_audit(audit), [])

        missing = deepcopy(audit)
        missing["audit"].pop("expectedChildren")
        self.assertTrue(contracts.validate_audit(missing))

        duplicate = deepcopy(audit)
        duplicate["audit"]["expectedChildren"]["memory"][0]["pageId"] = feed[
            "page_id"
        ]
        self.assertTrue(contracts.validate_audit(duplicate))

        bad_digest = deepcopy(audit)
        bad_digest["audit"]["expectedChildren"]["report"][0][
            "renderingDigest"
        ] = "not-a-digest"
        self.assertTrue(contracts.validate_audit(bad_digest))

        extra_top_level = deepcopy(audit)
        extra_top_level["rogueBusiness"] = {}
        self.assertTrue(contracts.validate_audit(extra_top_level))

    def test_audit_feed_facts_are_required_and_precommit_cross_bound(self):
        feed, _expected = feed_page()
        audit = run_audit(feed)
        self.assertEqual(contracts.validate_audit(audit), [])

        for field in (
            "sourceOutcomes",
            "successCount",
            "failureCount",
            "newItemCount",
        ):
            with self.subTest(missing=field):
                missing = deepcopy(audit)
                missing["feed"].pop(field)
                self.assertTrue(contracts.validate_audit(missing))

        extended = deepcopy(audit)
        extended["feed"]["latencyMs"] = 125
        self.assertEqual(contracts.validate_audit(extended), [])

        cross_bound_audits = []
        different_outcomes = run_audit(feed)
        different_outcomes["feed"].update(
            {
                "sourceOutcomes": source_outcomes(failed=(FEED_IDS[0],)),
                "successCount": 4,
                "failureCount": 1,
            }
        )
        cross_bound_audits.append(("source outcomes and counts", different_outcomes))
        different_new_count = run_audit(feed)
        different_new_count["feed"]["newItemCount"] = 2
        cross_bound_audits.append(("new item count", different_new_count))
        for field, changed_audit in cross_bound_audits:
            with self.subTest(cross_binding=field):
                bundle = precommit_bundle(feed)
                self.assertEqual(contracts.validate_audit(changed_audit), [])
                body = storage.encode_notion_body(changed_audit)
                for run in (
                    bundle["expected_run_snapshot"],
                    bundle["slot_rows"][0],
                    bundle["exact_run_rows"][0],
                ):
                    run["body"] = body
                errors = storage.verify_precommit_snapshot(**bundle)
                self.assertTrue(
                    any("audit feed" in error.lower() for error in errors),
                    errors,
                )

    def test_audit_source_outcomes_enforce_the_durable_status_matrix(self):
        feed, _expected = feed_page()
        all_ok = run_audit(feed)
        partial = deepcopy(all_ok)
        partial["feed"].update(
            {
                "sourceOutcomes": source_outcomes(failed=(FEED_IDS[0],)),
                "successCount": 4,
                "failureCount": 1,
            }
        )
        self.assertEqual(contracts.validate_audit(partial), [])

        all_failed = run_audit()
        self.assertEqual(all_failed["feed"]["successCount"], 0)
        self.assertEqual(all_failed["feed"]["failureCount"], 5)
        self.assertEqual(all_failed["feed"]["newItemCount"], 0)
        self.assertEqual(contracts.validate_audit(all_failed), [])

        impossible_failed_items = deepcopy(all_failed)
        impossible_failed_items["feed"]["newItemCount"] = 999
        self.assertTrue(contracts.validate_audit(impossible_failed_items))

        malformed_cases = (
            ("ok-bool-count", all_ok, {"itemCount": True}),
            ("ok-uppercase-cursor", all_ok, {"cursor": "A" * 64}),
            ("ok-error-text", all_ok, {"error": "unexpected"}),
            ("error-positive-count", all_failed, {"itemCount": 1}),
            ("error-cursor", all_failed, {"cursor": "a" * 64}),
            ("error-empty-message", all_failed, {"error": ""}),
        )
        for name, base, mutation in malformed_cases:
            with self.subTest(name=name):
                changed = deepcopy(base)
                changed["feed"]["sourceOutcomes"][0].update(mutation)
                self.assertTrue(contracts.validate_audit(changed))

    def test_memory_evidence_rules_do_not_overconstrain_valid_sources(self):
        state, _expected = memory_page()
        state_payload = {
            **state["payload"],
            "sources": [{
                "name": "Bureau of Labor Statistics",
                "url": "https://www.bls.gov/example",
            }],
        }
        state.update(
            {
                "Payload Digest": storage.canonical_digest(state_payload),
                "body": storage.encode_notion_body(state_payload),
                "payload": state_payload,
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "memory", state, deepcopy(state), parent_run(), installation()
            ),
            [],
        )

    def test_memory_evidence_urls_are_total_strict_http_urls(self):
        valid_url = "https://example.com/path?q=world-memory"
        valid, _expected = memory_page()
        valid_evidence = [{"name": "Evidence", "url": valid_url}]
        valid_payload = {
            **valid["payload"],
            "evidence": valid_evidence,
            "sources": valid_evidence,
        }
        valid.update(
            {
                "Payload Digest": storage.canonical_digest(valid_payload),
                "body": storage.encode_notion_body(valid_payload),
                "payload": valid_payload,
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "memory", valid, deepcopy(valid), parent_run(), installation()
            ),
            [],
        )

        for url in (
            "https:// ",
            "https://",
            "https://[",
            "https://exa mple.com/path",
            "https://example.com/path\nnext",
        ):
            with self.subTest(url=url):
                page, _expected = memory_page()
                evidence = [{"name": "Evidence", "url": url}]
                payload = {
                    **page["payload"],
                    "evidence": evidence,
                    "sources": evidence,
                }
                page.update(
                    {
                        "Payload Digest": storage.canonical_digest(payload),
                        "body": storage.encode_notion_body(payload),
                        "payload": payload,
                    }
                )
                errors = storage.validate_child_page(
                    "memory",
                    page,
                    deepcopy(page),
                    parent_run(),
                    installation(),
                )
                self.assertTrue(
                    any("evidence" in error or "sources" in error for error in errors),
                    errors,
                )

        brief, _expected = memory_page()
        brief_payload = {
            **brief["payload"],
            "recordType": "brief",
            "action": "brief-add",
            "target": "portfolio-brief",
            "dedupe_key": "portfolio-brief-20260810",
        }
        brief_payload.pop("state_key")
        brief_payload.pop("sources")
        brief_record = storage.memory_record_key("brief", brief_payload)
        brief_revision = storage.revision_key(brief_record, 1, RUN_KEY)
        brief.update(
            {
                "Name": "Readable brief title",
                "Record Key": brief_record,
                "Revision Key": brief_revision,
                "Dedupe Key": brief_payload["dedupe_key"],
                "Target": brief_payload["target"],
                "Record Type": "brief",
                "Action": "brief-add",
                "Payload Digest": storage.canonical_digest(brief_payload),
                "body": storage.encode_notion_body(brief_payload),
                "payload": brief_payload,
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "memory", brief, deepcopy(brief), parent_run(), installation()
            ),
            [],
        )

    def test_current_memory_projection_rejects_opaque_page_id(self):
        page, _expected = memory_page()
        page["page_id"] = "memory-page-alias"
        current, errors = storage.select_current_memory([page], {RUN_PAGE_ID})
        self.assertEqual(current, [])
        self.assertTrue(any("UUID" in error for error in errors), errors)

    def test_every_memory_payload_requires_evidence_to_be_a_list(self):
        page, _expected = memory_page()
        payload = {
            **page["payload"],
            "recordType": "taxonomy",
            "action": "taxonomy-refresh",
            "target": "world-memory-taxonomy",
            "evidence": "not-a-list",
        }
        payload.pop("state_key")
        payload.pop("sources")
        record = storage.memory_record_key("taxonomy", payload)
        revision = storage.revision_key(record, 1, RUN_KEY)
        page.update(
            {
                "Name": "Taxonomy refresh",
                "Record Key": record,
                "Revision Key": revision,
                "Target": payload["target"],
                "Record Type": "taxonomy",
                "Action": "taxonomy-refresh",
                "Verified Evidence": False,
                "Payload Digest": storage.canonical_digest(payload),
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }
        )
        errors = storage.validate_child_page(
            "memory", page, deepcopy(page), parent_run(), installation()
        )
        self.assertTrue(any("evidence" in error for error in errors), errors)

    def test_memory_stable_identity_components_reject_whitespace_only(self):
        invalid_payloads = (
            ("brief", {"dedupe_key": "   "}),
            ("state", {"state_key": "\t"}),
            (
                "suggestion",
                {"continuityId": "  ", "action": "state-add", "target": "rates"},
            ),
            ("suggestion", {"action": "  ", "target": "rates"}),
            ("suggestion", {"action": "state-add", "target": "\n"}),
            (
                "story-link",
                {"story_key": "  ", "endpoints": ["left", "right"]},
            ),
            ("story-link", {"endpoints": ["left", " "]}),
        )
        for record_type, payload in invalid_payloads:
            with self.subTest(record_type=record_type, payload=payload):
                with self.assertRaises(ValueError):
                    storage.memory_record_key(record_type, payload)

        padded = storage.memory_record_key(
            "brief", {"dedupe_key": "  brief-key  "}
        )
        canonical = storage.memory_record_key("brief", {"dedupe_key": "brief-key"})
        self.assertNotEqual(padded, canonical)
        self.assertTrue(
            storage.memory_record_key(
                "suggestion", {"action": "state-add", "target": "rates"}
            ).startswith("wmrec_suggestion_")
        )
        self.assertTrue(
            storage.memory_record_key(
                "story-link", {"endpoints": ["left", "right"]}
            ).startswith("wmrec_story-link_")
        )
        self.assertTrue(
            storage.memory_record_key("taxonomy", {}).startswith(
                "wmrec_taxonomy_"
            )
        )

    def test_memory_optional_physical_fields_always_validate_their_domains(self):
        optional_fields = (
            ("Importance", "importance"),
            ("Category", "category"),
            ("Region", "region"),
            ("Effective At", "effectiveAt"),
        )
        empty, _expected = memory_page()
        empty_payload = deepcopy(empty["payload"])
        for property_name, payload_name in optional_fields:
            empty[property_name] = ""
            empty_payload.pop(payload_name)
        empty.update(
            {
                "Payload Digest": storage.canonical_digest(empty_payload),
                "body": storage.encode_notion_body(empty_payload),
                "payload": empty_payload,
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "memory", empty, deepcopy(empty), parent_run(), installation()
            ),
            [],
        )

        invalid_cases = (
            ("Importance", "importance", "ultra"),
            ("Importance", "importance", []),
            ("Category", "category", "other"),
            ("Category", "category", None),
            ("Region", "region", "EU"),
            ("Region", "region", False),
            ("Effective At", "effectiveAt", "2026-08-10T02:00Z"),
            ("Effective At", "effectiveAt", []),
        )
        for property_name, payload_name, value in invalid_cases:
            with self.subTest(property_name=property_name, value=value):
                page, _expected = memory_page()
                payload = {**page["payload"], payload_name: value}
                page.update(
                    {
                        property_name: value,
                        "Payload Digest": storage.canonical_digest(payload),
                        "body": storage.encode_notion_body(payload),
                        "payload": payload,
                    }
                )
                errors = storage.validate_child_page(
                    "memory",
                    page,
                    deepcopy(page),
                    parent_run(),
                    installation(),
                )
                self.assertTrue(
                    any(property_name in error for error in errors),
                    errors,
                )

        for property_name, payload_name, value in invalid_cases:
            with self.subTest(
                property_name=property_name,
                value=value,
                payload_field="absent",
            ):
                page, _expected = memory_page()
                payload = deepcopy(page["payload"])
                payload.pop(payload_name)
                page.update(
                    {
                        property_name: value,
                        "Payload Digest": storage.canonical_digest(payload),
                        "body": storage.encode_notion_body(payload),
                        "payload": payload,
                    }
                )
                errors = storage.validate_child_page(
                    "memory",
                    page,
                    deepcopy(page),
                    parent_run(),
                    installation(),
                )
                self.assertTrue(
                    any(property_name in error for error in errors),
                    errors,
                )

    def test_memory_payload_rejects_storage_owned_self_claims(self):
        forbidden_values = {
            "runKey": "foreign-run",
            "recordKey": "foreign-record",
            "revisionKey": "foreign-revision",
            "revision": 999,
            "supersedes": [],
            "verifiedEvidence": False,
            "payloadDigest": "0" * 64,
            "bodyFormat": "foreign-body",
            "pageId": "99999999-9999-4999-8999-999999999999",
            "createdAt": "1900-01-01T00:00:00Z",
            "updatedAt": "2100-01-01T00:00:00Z",
        }
        for forbidden, value in forbidden_values.items():
            with self.subTest(forbidden=forbidden):
                page, _expected = memory_page()
                payload = {**page["payload"], forbidden: value}
                page.update(
                    {
                        "Payload Digest": storage.canonical_digest(payload),
                        "body": storage.encode_notion_body(payload),
                        "payload": payload,
                    }
                )
                errors = storage.validate_child_page(
                    "memory", page, deepcopy(page), parent_run(), installation()
                )
                self.assertTrue(
                    any(forbidden in error for error in errors), errors
                )

    def test_report_payload_rejects_parent_owned_window_and_run_fields(self):
        for forbidden, value in (
            ("runKey", "foreign-run"),
            ("reportKey", "foreign-report"),
            ("integrationKey", "wmi_000000000000_genesis"),
            ("materialChange", False),
            ("userVisible", False),
            ("evidenceRecords", []),
            ("coverageStart", "1900-01-01T00:00:00Z"),
            ("coverageEnd", "2100-01-01T00:00:00Z"),
            ("collectionCutoff", "2100-01-01T00:00:00Z"),
            ("notificationPlan", "silent"),
        ):
            with self.subTest(forbidden=forbidden):
                page, _expected = report_page()
                payload = {**page["payload"], forbidden: value}
                page.update(
                    {
                        "Payload Digest": storage.canonical_digest(payload),
                        "body": storage.encode_notion_body(payload, page["rendering"]),
                        "payload": payload,
                    }
                )
                errors = storage.validate_child_page(
                    "report", page, deepcopy(page), parent_run(), installation()
                )
                self.assertTrue(
                    any(forbidden in error for error in errors), errors
                )

    def test_public_report_validator_rejects_parent_owned_self_claims(self):
        forbidden_values = {
            "runKey": "foreign-run",
            "reportKey": "foreign-report",
            "integrationKey": "wmi_000000000000_genesis",
            "materialChange": False,
            "userVisible": False,
            "evidenceRecords": [],
            "coverageStart": "1900-01-01T00:00:00Z",
            "coverageEnd": "2100-01-01T00:00:00Z",
            "collectionCutoff": "2100-01-01T00:00:00Z",
            "notificationPlan": "silent",
        }
        self.assertEqual(contracts.validate_report(valid_report_payload()), [])
        for forbidden, value in forbidden_values.items():
            with self.subTest(forbidden=forbidden):
                payload = {**valid_report_payload(), forbidden: value}
                self.assertTrue(contracts.validate_report(payload))

    def test_strict_validators_reject_unhashable_types_deterministically(self):
        memory, _expected = memory_page()
        memory_payload_changed = {**memory["payload"], "recordType": []}
        memory.update(
            {
                "Payload Digest": storage.canonical_digest(memory_payload_changed),
                "body": storage.encode_notion_body(memory_payload_changed),
                "payload": memory_payload_changed,
            }
        )
        self.assertTrue(
            storage.validate_child_page(
                "memory", memory, deepcopy(memory), parent_run(), installation()
            )
        )

        feed, expected = feed_page()
        self.assertTrue(
            storage.validate_child_page(
                "feed", feed, expected, parent_run(Trigger=[]), installation()
            )
        )

        for field, value in (("status", []), ("feedId", [])):
            with self.subTest(feed_field=field):
                payload = feed_payload()
                if field == "status":
                    payload["sourceOutcomes"][0][field] = value
                else:
                    payload["items"][0][field] = value
                    payload["fingerprintWindow"] = [{
                        "sourceFingerprint": payload["items"][0]["sourceFingerprint"],
                        "publishedAt": payload["items"][0]["publishedAt"],
                    }]
                page, _expected = feed_page(payload)
                self.assertTrue(
                    storage.validate_child_page(
                        "feed", page, deepcopy(page), parent_run(), installation()
                    )
                )

        report, _expected = report_page()
        report["Evidence Records"] = [[]]
        self.assertTrue(
            storage.validate_child_page(
                "report", report, deepcopy(report), parent_run(), installation()
            )
        )

    def test_memory_properties_identity_action_and_evidence_derive_from_payload(self):
        page, expected = memory_page()
        self.assertEqual(
            storage.validate_child_page(
                "memory", page, expected, parent_run(), installation()
            ),
            [],
        )
        cases = (
            ("record", {"Record Key": "wmrec_state_000000000000000000"}),
            ("action", {"Action": "brief-add"}),
            ("verified", {"Verified Evidence": False}),
        )
        for name, changes in cases:
            with self.subTest(name=name):
                changed = {**page, **changes}
                changed_expected = deepcopy(changed)
                errors = storage.validate_child_page(
                    "memory",
                    changed,
                    changed_expected,
                    parent_run(),
                    installation(),
                )
                self.assertTrue(errors)

        payload = {**page["payload"], "evidence": [], "sources": []}
        changed = {
            **page,
            "Payload Digest": storage.canonical_digest(payload),
            "body": storage.encode_notion_body(payload),
            "payload": payload,
        }
        errors = storage.validate_child_page(
            "memory", changed, deepcopy(changed), parent_run(), installation()
        )
        self.assertTrue(any("evidence" in error for error in errors))

        contradictory = deepcopy(page)
        contradictory_payload = {**contradictory["payload"], "sources": []}
        contradictory.update(
            {
                "Payload Digest": storage.canonical_digest(contradictory_payload),
                "body": storage.encode_notion_body(contradictory_payload),
                "payload": contradictory_payload,
            }
        )
        errors = storage.validate_child_page(
            "memory",
            contradictory,
            deepcopy(contradictory),
            parent_run(),
            installation(),
        )
        self.assertTrue(any("sources" in error for error in errors))

    def test_suggestion_completion_requires_authoritative_caller_observation(self):
        page, _expected = memory_page()
        payload = {
            "schemaVersion": 2,
            "kind": "memory",
            "recordType": "suggestion",
            "action": "suggestion-status-update",
            "target": "suggestion-42",
            "evidence": [],
            "confidence": 0.8,
            "result": {"success": True},
            "continuityId": "suggestion-42",
            "recordStatus": "completed",
            "importance": "medium",
            "category": "emerging",
            "region": "GLOBAL",
            "effectiveAt": "2026-08-10T02:00:00Z",
        }
        record = storage.memory_record_key("suggestion", payload)
        key = storage.revision_key(record, 1, RUN_KEY)
        page.update(
            {
                "Name": "Completed suggestion",
                "Record Key": record,
                "Revision Key": key,
                "Dedupe Key": "",
                "Continuity ID": "suggestion-42",
                "Target": "suggestion-42",
                "Payload Digest": storage.canonical_digest(payload),
                "Record Type": "suggestion",
                "Record Status": "completed",
                "Importance": "medium",
                "Category": "emerging",
                "Region": "GLOBAL",
                "Action": "suggestion-status-update",
                "Confidence": 0.8,
                "Verified Evidence": False,
                "body": storage.encode_notion_body(payload),
                "payload": payload,
            }
        )
        expected = deepcopy(page)
        errors = storage.validate_child_page(
            "memory", page, expected, parent_run(), installation()
        )
        self.assertTrue(any("authoritative" in error for error in errors))
        self.assertEqual(
            storage.validate_child_page(
                "memory",
                page,
                expected,
                parent_run(),
                installation(),
                authoritative_completion=True,
            ),
            [],
        )

    def test_report_properties_derive_from_parent_and_payload_without_payload_run_key(self):
        page, expected = report_page()
        self.assertNotIn("runKey", page["payload"])
        self.assertEqual(
            storage.validate_child_page(
                "report", page, expected, parent_run(), installation()
            ),
            [],
        )
        cases = (
            ("As Of", "2026-08-10T01:00:00Z"),
            ("Coverage End", "2026-08-10T01:00:00Z"),
            ("Stance", "defensive"),
            ("Confidence", 0.2),
            ("Data Gap Count", 999),
            ("Material Change", False),
            ("User Visible", False),
        )
        for field, value in cases:
            with self.subTest(field=field):
                changed = {**page, field: value}
                errors = storage.validate_child_page(
                    "report",
                    changed,
                    deepcopy(changed),
                    parent_run(),
                    installation(),
                )
                self.assertTrue(errors)

        empty_rendering = deepcopy(page)
        empty_rendering.update(
            {
                "Rendering Digest": __import__("hashlib").sha256(b"").hexdigest(),
                "body": storage.encode_notion_body(page["payload"]),
                "rendering": "",
            }
        )
        errors = storage.validate_child_page(
            "report",
            empty_rendering,
            deepcopy(empty_rendering),
            parent_run(),
            installation(),
        )
        self.assertTrue(any("rendering" in error.lower() for error in errors))

        english = "## One-line view\nNeutral with elevated uncertainty."
        english_rendering = deepcopy(page)
        english_rendering.update(
            {
                "Rendering Digest": __import__("hashlib").sha256(
                    english.encode("utf-8")
                ).hexdigest(),
                "body": storage.encode_notion_body(page["payload"], english),
                "rendering": english,
            }
        )
        errors = storage.validate_child_page(
            "report",
            english_rendering,
            deepcopy(english_rendering),
            parent_run(),
            installation(),
        )
        self.assertTrue(any("Korean" in error for error in errors))

    def test_report_operational_identity_fields_cannot_bypass_type_validation(self):
        six_hour, expected_six_hour = report_page()
        self.assertEqual(
            storage.validate_child_page(
                "report",
                six_hour,
                expected_six_hour,
                parent_run(),
                installation(),
            ),
            [],
        )

        hourly = deepcopy(six_hour)
        hourly.update(
            {
                "Report Key": storage.report_key(RUN_KEY, "hourly-briefing"),
                "Integration Key": "",
                "Report Type": "hourly-briefing",
                "Coverage Start": "",
            }
        )
        hourly_parent = parent_run(
            **{
                "Integration Key": "",
                "Integration Due": False,
                "Integration Performed": False,
                "Material Change": True,
                "Notification Plan": "hourly-briefing",
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "report",
                hourly,
                deepcopy(hourly),
                hourly_parent,
                installation(),
            ),
            [],
        )

        for field, value in (
            ("Report Type", "rogue"),
            ("Report Type", []),
            ("Report Key", None),
            ("Report Key", ""),
            ("Integration Key", []),
            ("Integration Key", ""),
            ("Coverage Start", None),
            ("Coverage Start", "not-a-timestamp"),
            ("User Visible", False),
            ("User Visible", 1),
        ):
            with self.subTest(field=field, value=value):
                changed = {**six_hour, field: value}
                errors = storage.validate_child_page(
                    "report",
                    changed,
                    deepcopy(changed),
                    parent_run(),
                    installation(),
                )
                self.assertTrue(
                    any(field in error for error in errors),
                    errors,
                )

        combined = deepcopy(six_hour)
        combined.update(
            {
                "Report Type": "rogue",
                "Report Key": None,
                "Integration Key": [],
                "Coverage Start": None,
                "User Visible": False,
            }
        )
        combined_errors = storage.validate_child_page(
            "report",
            combined,
            deepcopy(combined),
            parent_run(),
            installation(),
        )
        for field in (
            "Report Type",
            "Report Key",
            "Integration Key",
            "Coverage Start",
            "User Visible",
        ):
            self.assertTrue(
                any(field in error for error in combined_errors),
                combined_errors,
            )

        valid_type_combined = deepcopy(six_hour)
        valid_type_combined.update(
            {
                "Report Key": None,
                "Integration Key": [],
                "Coverage Start": None,
                "User Visible": False,
            }
        )
        valid_type_errors = storage.validate_child_page(
            "report",
            valid_type_combined,
            deepcopy(valid_type_combined),
            parent_run(),
            installation(),
        )
        for field in (
            "Report Key",
            "Integration Key",
            "Coverage Start",
            "User Visible",
        ):
            self.assertTrue(
                any(field in error for error in valid_type_errors),
                valid_type_errors,
            )

    def test_report_cutoff_timestamps_must_be_nonempty_canonical_utc(self):
        page, _expected = report_page()
        page["payload"] = {**page["payload"], "asOf": ""}
        page.update(
            {
                "As Of": "",
                "Coverage End": "",
                "Payload Digest": storage.canonical_digest(page["payload"]),
                "body": storage.encode_notion_body(
                    page["payload"], page["rendering"]
                ),
            }
        )
        errors = storage.validate_child_page(
            "report",
            page,
            deepcopy(page),
            parent_run(**{"Collection Cutoff": ""}),
            installation(),
        )
        for field in ("Collection Cutoff", "As Of", "Coverage End"):
            self.assertTrue(any(field in error for error in errors), errors)

    def test_report_parent_projection_fields_are_type_strict(self):
        page, expected = report_page()
        self.assertEqual(
            storage.validate_child_page(
                "report", page, expected, parent_run(), installation()
            ),
            [],
        )

        for value in ([], 0, 1, None):
            with self.subTest(field="Material Change", value=value):
                changed = {**page, "Material Change": value}
                errors = storage.validate_child_page(
                    "report",
                    changed,
                    deepcopy(changed),
                    parent_run(**{"Material Change": value}),
                    installation(),
                )
                self.assertTrue(
                    any("Material Change" in error for error in errors),
                    errors,
                )

        for field, values in (
            ("Integration Performed", ([], 0, 1, None)),
            ("Collection Cutoff", ([], None, "")),
            ("Notification Plan", ([], None, "rogue")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    errors = storage.validate_child_page(
                        "report",
                        page,
                        expected,
                        parent_run(**{field: value}),
                        installation(),
                    )
                    self.assertTrue(
                        any(field in error for error in errors),
                        errors,
                    )

    def test_report_type_binds_the_parent_run_phase(self):
        six_hour, expected_six_hour = report_page()
        self.assertEqual(
            storage.validate_child_page(
                "report",
                six_hour,
                expected_six_hour,
                parent_run(),
                installation(),
            ),
            [],
        )
        for field, value in (
            ("Integration Due", False),
            ("Integration Performed", False),
            ("Notification Plan", "hourly-briefing"),
        ):
            with self.subTest(report_type="six-hour", field=field):
                errors = storage.validate_child_page(
                    "report",
                    six_hour,
                    expected_six_hour,
                    parent_run(**{field: value}),
                    installation(),
                )
                self.assertTrue(any(field in error for error in errors), errors)

    def test_scheduled_nonmaterial_run_still_accepts_one_visible_hourly_report(self):
        hourly, expected_hourly = hourly_report_page()
        hourly["Material Change"] = False
        expected_hourly["Material Change"] = False
        scheduled_parent = parent_run(
            **{
                "Integration Key": "",
                "Integration Due": False,
                "Integration Performed": False,
                "Material Change": False,
                "Notification Plan": "hourly-briefing",
            }
        )

        self.assertEqual(
            storage.validate_child_page(
                "report",
                hourly,
                expected_hourly,
                scheduled_parent,
                installation(),
            ),
            [],
        )

        feed, _expected_feed = feed_page()
        bundle = precommit_bundle(feed, hourly)
        for run in (
            bundle["expected_run_snapshot"],
            bundle["slot_rows"][0],
            bundle["exact_run_rows"][0],
        ):
            run["Material Change"] = False
        self.assertEqual(storage.verify_precommit_snapshot(**bundle), [])

    def test_nonintegration_run_rejects_memory_and_suggestion_completion(self):
        feed, _expected_feed = feed_page()
        memory, _expected_memory = memory_page()
        hourly, _expected_hourly = hourly_report_page()
        bundle = precommit_bundle(feed, memory, hourly)

        errors = storage.verify_precommit_snapshot(
            **bundle,
            authoritative_completed_memory_ids=[memory["page_id"]],
        )

        self.assertTrue(
            any("non-integration precommit must not contain Memory" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("non-integration precommit must not complete suggestions" in error for error in errors),
            errors,
        )

        hourly, expected_hourly = hourly_report_page()
        hourly_parent = parent_run(
            **{
                "Integration Key": "",
                "Integration Due": False,
                "Integration Performed": False,
                "Material Change": True,
                "Notification Plan": "hourly-briefing",
            }
        )
        self.assertEqual(
            storage.validate_child_page(
                "report",
                hourly,
                expected_hourly,
                hourly_parent,
                installation(),
            ),
            [],
        )
        for field, value in (
            ("Integration Due", True),
            ("Integration Performed", True),
            ("Notification Plan", "silent"),
        ):
            with self.subTest(report_type="hourly-briefing", field=field):
                errors = storage.validate_child_page(
                    "report",
                    hourly,
                    expected_hourly,
                    {**hourly_parent, field: value},
                    installation(),
                )
                self.assertTrue(any(field in error for error in errors), errors)

    def test_report_window_integration_and_evidence_relations_are_strict(self):
        integration = (
            f"wmi_{INSTALLATION_HASH}_previous-cutoff-20260809T200000Z"
        )
        parent = parent_run(**{"Integration Key": integration})
        page, _expected = report_page()
        page.update(
            {
                "Report Key": storage.report_key(RUN_KEY, "six-hour", integration),
                "Integration Key": integration,
                "Coverage Start": "2026-08-09T20:00:00Z",
            }
        )
        expected = deepcopy(page)
        self.assertEqual(
            storage.validate_child_page(
                "report", page, expected, parent, installation()
            ),
            [],
        )

        wrong_start = {**page, "Coverage Start": "2026-08-09T19:59:59Z"}
        self.assertTrue(
            storage.validate_child_page(
                "report", wrong_start, deepcopy(wrong_start), parent, installation()
            )
        )
        self.assertTrue(
            storage.validate_child_page(
                "report", page, expected, parent_run(), installation()
            )
        )

        duplicate_evidence = {
            **page,
            "Evidence Records": [
                "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            ],
        }
        self.assertTrue(
            storage.validate_child_page(
                "report",
                duplicate_evidence,
                deepcopy(duplicate_evidence),
                parent,
                installation(),
            )
        )

        hourly = deepcopy(page)
        hourly.update(
            {
                "Report Key": storage.report_key(RUN_KEY, "hourly-briefing"),
                "Integration Key": "",
                "Report Type": "hourly-briefing",
                "Coverage Start": "",
                "Material Change": False,
            }
        )
        self.assertTrue(
            storage.validate_child_page(
                "report",
                hourly,
                deepcopy(hourly),
                parent_run(
                    **{"Integration Key": "", "Material Change": False}
                ),
                installation(),
            )
        )

        genesis, _ = report_page()
        genesis["Coverage Start"] = None
        self.assertTrue(
            storage.validate_child_page(
                "report",
                genesis,
                deepcopy(genesis),
                parent_run(),
                installation(),
            )
        )


class PrecommitIntegrityTests(unittest.TestCase):
    def test_valid_precommit_requires_operational_installation_snapshot(self):
        feed, _expected = feed_page()
        self.assertEqual(storage.verify_precommit_snapshot(**precommit_bundle(feed)), [])

    def test_precommit_rejects_unhashable_run_enums_deterministically(self):
        feed, _expected = feed_page()
        for field in ("Trigger", "Notification Plan"):
            with self.subTest(field=field):
                bundle = precommit_bundle(feed)
                for run in (
                    bundle["expected_run_snapshot"],
                    bundle["slot_rows"][0],
                    bundle["exact_run_rows"][0],
                ):
                    run[field] = []
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_documented_expected_run_snapshot_uses_separate_page_id_argument(self):
        feed, _expected = feed_page()
        bundle = precommit_bundle(feed)
        self.assertNotIn("page_id", bundle["expected_run_snapshot"])
        self.assertEqual(storage.verify_precommit_snapshot(**bundle), [])

    def test_precommit_requires_all_three_child_projection_kinds(self):
        feed, _expected = feed_page()
        for projection in (
            "child_rows_by_kind",
            "expected_child_ids",
            "expected_child_pages_by_kind",
        ):
            with self.subTest(projection=projection):
                bundle = precommit_bundle(feed)
                bundle[projection] = {"feed": bundle[projection]["feed"]}
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_precommit_binds_integration_performed_to_report_and_notification(self):
        feed, _expected = feed_page()
        bundle = precommit_bundle(feed)
        for run in (
            bundle["expected_run_snapshot"],
            bundle["slot_rows"][0],
            bundle["exact_run_rows"][0],
        ):
            run["Integration Performed"] = True
        self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_precommit_notification_plan_is_an_exact_report_inventory_matrix(self):
        feed, _expected = feed_page()
        hourly, _expected = hourly_report_page()
        six_hour, _expected = report_page()

        for name, bundle in (
            ("scheduled-nonmaterial-hourly", precommit_bundle(feed)),
            ("scheduled-material-hourly", precommit_bundle(feed, hourly)),
            ("six-hour", precommit_bundle(feed, six_hour)),
        ):
            with self.subTest(valid=name):
                self.assertEqual(storage.verify_precommit_snapshot(**bundle), [])

        invalid_bundles = []
        phantom_hourly = precommit_bundle(feed, include_default_report=False)
        for run in (
            phantom_hourly["expected_run_snapshot"],
            phantom_hourly["slot_rows"][0],
            phantom_hourly["exact_run_rows"][0],
        ):
            run["Notification Plan"] = "hourly-briefing"
        invalid_bundles.append(("phantom-hourly-plan", phantom_hourly))

        suppressed_hourly = precommit_bundle(feed, hourly)
        for run in (
            suppressed_hourly["expected_run_snapshot"],
            suppressed_hourly["slot_rows"][0],
            suppressed_hourly["exact_run_rows"][0],
        ):
            run["Notification Plan"] = "silent"
        invalid_bundles.append(("suppressed-hourly-report", suppressed_hourly))

        wrong_type = precommit_bundle(feed, hourly)
        for run in (
            wrong_type["expected_run_snapshot"],
            wrong_type["slot_rows"][0],
            wrong_type["exact_run_rows"][0],
        ):
            run["Notification Plan"] = "six-hour"
        invalid_bundles.append(("wrong-report-type", wrong_type))

        extra_report = precommit_bundle(feed, hourly, six_hour)
        invalid_bundles.append(("extra-report", extra_report))

        for name, bundle in invalid_bundles:
            with self.subTest(invalid=name):
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_precommit_integration_due_must_equal_performed(self):
        feed, _expected = feed_page()
        six_hour, _expected = report_page()
        self.assertEqual(
            storage.verify_precommit_snapshot(**precommit_bundle(feed)),
            [],
        )
        self.assertEqual(
            storage.verify_precommit_snapshot(
                **precommit_bundle(feed, six_hour)
            ),
            [],
        )

        due_without_performed = precommit_bundle(feed)
        for run in (
            due_without_performed["expected_run_snapshot"],
            due_without_performed["slot_rows"][0],
            due_without_performed["exact_run_rows"][0],
        ):
            run["Integration Due"] = True
        errors = storage.verify_precommit_snapshot(**due_without_performed)
        self.assertTrue(
            any("Integration Due" in error for error in errors),
            errors,
        )

        performed_without_due = precommit_bundle(feed, six_hour)
        for run in (
            performed_without_due["expected_run_snapshot"],
            performed_without_due["slot_rows"][0],
            performed_without_due["exact_run_rows"][0],
        ):
            run["Integration Due"] = False
        errors = storage.verify_precommit_snapshot(**performed_without_due)
        self.assertTrue(
            any("Integration Due" in error for error in errors),
            errors,
        )

    def test_precommit_cache_reconciliation_remains_post_commit(self):
        feed, _expected = feed_page()
        valid = precommit_bundle(feed)
        self.assertEqual(valid["expected_run_snapshot"]["Finished At"], "")
        self.assertFalse(valid["expected_run_snapshot"]["Cache Reconciled"])
        self.assertEqual(storage.verify_precommit_snapshot(**valid), [])

        for field, value in (
            ("Cache Reconciled", True),
            ("Finished At", "2026-08-10T02:00:04Z"),
        ):
            with self.subTest(field=field):
                changed = precommit_bundle(feed)
                for run in (
                    changed["expected_run_snapshot"],
                    changed["slot_rows"][0],
                    changed["exact_run_rows"][0],
                ):
                    run[field] = value
                errors = storage.verify_precommit_snapshot(**changed)
                self.assertTrue(
                    any(field in error for error in errors),
                    errors,
                )

    def test_precommit_requires_complete_normalized_installation_snapshot(self):
        feed, _expected = feed_page()
        invalid_installations = []
        incomplete = installation()
        incomplete.pop("Schema Version")
        invalid_installations.extend((
            incomplete,
            installation(**{"Schema Version": 1}),
            installation(**{"Hub Page ID": "https://www.notion.so/not-a-page-id"}),
        ))
        for observed in invalid_installations:
            with self.subTest(observed=observed):
                bundle = precommit_bundle(feed)
                bundle["installation_snapshot"] = observed
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_precommit_independently_enforces_installation_safety_state(self):
        feed, _expected = feed_page()
        memory, _expected = memory_page()

        for name, observed in (
            ("disabled", installation(**{"Enabled": False})),
            ("paused", installation(**{"Status": "paused"})),
            ("error", installation(**{"Status": "error"})),
        ):
            with self.subTest(blocked=name):
                bundle = precommit_bundle(feed)
                bundle["installation_snapshot"] = observed
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

        autopilot_feed_only = precommit_bundle(feed)
        autopilot_feed_only["installation_snapshot"] = installation(
            **{"Autopilot Enabled": False}
        )
        self.assertEqual(
            storage.verify_precommit_snapshot(**autopilot_feed_only),
            [],
        )

        autopilot_memory = precommit_bundle(feed, memory)
        autopilot_memory["installation_snapshot"] = installation(
            **{"Autopilot Enabled": False}
        )
        self.assertTrue(storage.verify_precommit_snapshot(**autopilot_memory))

        autopilot_completion = precommit_bundle(feed)
        autopilot_completion["installation_snapshot"] = installation(
            **{"Autopilot Enabled": False}
        )
        autopilot_completion["authoritative_completed_memory_ids"] = [
            memory["page_id"]
        ]
        self.assertTrue(storage.verify_precommit_snapshot(**autopilot_completion))

        active_scheduled = precommit_bundle(feed)
        self.assertTrue(
            storage.verify_precommit_snapshot(
                **active_scheduled,
                explicit_setup=True,
            )
        )

    def test_force_precommit_requires_a_performed_six_hour_integration(self):
        force_slot = storage.slot_key(
            INSTALLATION_KEY,
            "force-world-memory",
            utc("2026-08-10T02:00:00Z"),
        )
        force_run_key = storage.run_key(force_slot, 1)

        def force_bundle(*pages: dict) -> dict:
            transformed_pages = []
            for original in pages:
                page = deepcopy(original)
                if "Batch Key" in page:
                    payload = deepcopy(page["payload"])
                    payload["runKey"] = force_run_key
                    payload["batchKey"] = f"{force_run_key}:feed:001"
                    page.update(
                        {
                            "Batch Key": payload["batchKey"],
                            "Run Key": force_run_key,
                            "Payload Digest": storage.canonical_digest(payload),
                            "body": storage.encode_notion_body(payload),
                            "payload": payload,
                        }
                    )
                elif "Report Key" in page:
                    page.update(
                        {
                            "Report Key": storage.report_key(
                                force_run_key,
                                page["Report Type"],
                                page["Integration Key"],
                            ),
                            "Run Key": force_run_key,
                        }
                    )
                transformed_pages.append(page)

            bundle = precommit_bundle(*transformed_pages)
            audit = run_audit(*transformed_pages)
            audit["trigger"] = "force-world-memory"
            body = storage.encode_notion_body(audit)
            runs = [
                bundle["expected_run_snapshot"],
                bundle["slot_rows"][0],
                bundle["exact_run_rows"][0],
                *bundle["integration_rows"],
            ]
            for run in runs:
                run.update(
                    {
                        "Slot Key": force_slot,
                        "Run Key": force_run_key,
                        "Trigger": "force-world-memory",
                        "body": body,
                    }
                )
            return bundle

        feed, _expected = feed_page()
        self.assertTrue(
            storage.verify_precommit_snapshot(**force_bundle(feed))
        )
        report, _expected = report_page()
        self.assertEqual(
            storage.verify_precommit_snapshot(**force_bundle(feed, report)),
            [],
        )

        initializing = precommit_bundle(feed)
        initializing["installation_snapshot"] = installation(
            **{"Status": "initializing"}
        )
        self.assertTrue(storage.verify_precommit_snapshot(**initializing))

        for direct_trigger in ("manual",):
            with self.subTest(explicit_setup=direct_trigger):
                direct_slot = storage.slot_key(
                    INSTALLATION_KEY,
                    direct_trigger,
                    utc("2026-08-10T02:00:00Z"),
                )
                direct_run_key = storage.run_key(direct_slot, 1)
                direct_payload = feed_payload()
                direct_payload.update(
                    {
                        "runKey": direct_run_key,
                        "batchKey": storage.feed_batch_key(direct_run_key, 1),
                    }
                )
                direct_feed, _expected = feed_page(direct_payload)
                direct_bundle = precommit_bundle(
                    direct_feed, include_default_report=False
                )
                direct_audit = run_audit(direct_feed)
                direct_audit["trigger"] = direct_trigger
                direct_body = storage.encode_notion_body(direct_audit)
                for run in (
                    direct_bundle["expected_run_snapshot"],
                    direct_bundle["slot_rows"][0],
                    direct_bundle["exact_run_rows"][0],
                ):
                    run.update(
                        {
                            "Slot Key": direct_slot,
                            "Run Key": direct_run_key,
                            "Trigger": direct_trigger,
                            "body": direct_body,
                        }
                    )
                direct_bundle["installation_snapshot"] = installation(
                    **{"Status": "initializing"}
                )
                self.assertEqual(
                    storage.verify_precommit_snapshot(
                        **direct_bundle,
                        explicit_setup=True,
                    ),
                    [],
                )

        with self.subTest(explicit_setup="force-world-memory"):
            force_setup = force_bundle(feed, report)
            force_setup["installation_snapshot"] = installation(
                **{"Status": "initializing"}
            )
            self.assertEqual(
                storage.verify_precommit_snapshot(
                    **force_setup,
                    explicit_setup=True,
                ),
                [],
            )

    def test_precommit_rejects_plaintext_or_rendered_run_audit(self):
        feed, _expected = feed_page()
        for body in (
            "plaintext audit",
            storage.encode_notion_body(run_audit(feed), "unexpected rendering"),
        ):
            with self.subTest(body=body):
                bundle = precommit_bundle(feed)
                bundle["expected_run_snapshot"]["body"] = body
                bundle["slot_rows"][0]["body"] = body
                bundle["exact_run_rows"][0]["body"] = body
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

    def test_precommit_audit_inventory_must_exactly_match_children(self):
        feed, _expected = feed_page()
        bundle = precommit_bundle(feed)
        bad_audit = run_audit()
        bad_body = storage.encode_notion_body(bad_audit)
        for run in (
            bundle["expected_run_snapshot"],
            bundle["slot_rows"][0],
            bundle["exact_run_rows"][0],
        ):
            run["body"] = bad_body
        self.assertTrue(storage.verify_precommit_snapshot(**bundle))

        for field, value in (
            ("key", "wrong-feed-key"),
            ("pageId", "14141414-1414-4141-8141-141414141414"),
            ("payloadDigest", "d" * 64),
            ("fingerprintWindowDigest", "e" * 64),
        ):
            with self.subTest(field=field):
                changed = precommit_bundle(feed)
                audit = run_audit(feed)
                audit["audit"]["expectedChildren"]["feed"][0][field] = value
                body = storage.encode_notion_body(audit)
                for run in (
                    changed["expected_run_snapshot"],
                    changed["slot_rows"][0],
                    changed["exact_run_rows"][0],
                ):
                    run["body"] = body
                self.assertTrue(storage.verify_precommit_snapshot(**changed))

    def test_precommit_crosschecks_run_and_complete_feed_group_counts(self):
        feed, _expected = feed_page()
        mutations = (
            {"Feed Success Count": 4},
            {"Feed Failure Count": 1},
            {"New Item Count": 2},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = precommit_bundle(feed)
                for run in (
                    bundle["expected_run_snapshot"],
                    bundle["slot_rows"][0],
                    bundle["exact_run_rows"][0],
                ):
                    run.update(mutation)
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

        empty = precommit_bundle()
        for run in (
            empty["expected_run_snapshot"],
            empty["slot_rows"][0],
            empty["exact_run_rows"][0],
        ):
            run.update({"Feed Success Count": 5, "Feed Failure Count": 0})
        self.assertTrue(storage.verify_precommit_snapshot(**empty))

        failed_payload = feed_payload(
            items=[], outcomes=source_outcomes(failed=FEED_IDS)
        )
        failed_feed, _ = feed_page(failed_payload)
        self.assertTrue(
            storage.verify_precommit_snapshot(**precommit_bundle(failed_feed))
        )

    def test_memory_successor_requires_exact_committed_predecessor(self):
        feed, _expected = feed_page()
        predecessor, _ = memory_page()
        predecessor_parent = "99999999-9999-4999-8999-999999999998"
        predecessor["Run"] = [predecessor_parent]
        successor = deepcopy(predecessor)
        successor.update(
            {
                "page_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                "Name": "Second revision",
                "Revision": 2,
                "Revision Key": storage.revision_key(
                    predecessor["Record Key"], 2, RUN_KEY
                ),
                "Run": [RUN_PAGE_ID],
                "Supersedes": [predecessor["page_id"]],
            }
        )
        bundle = precommit_bundle(feed, successor)
        bundle["memory_logical_rows"].append(predecessor)
        bundle["parent_status_by_id"][predecessor_parent] = "committed"
        self.assertEqual(storage.verify_precommit_snapshot(**bundle), [])

        duplicate_predecessor = deepcopy(predecessor)
        duplicate_predecessor["page_id"] = (
            "98989898-9898-4989-8989-989898989898"
        )
        duplicate_bundle = precommit_bundle(feed, successor)
        duplicate_bundle["memory_logical_rows"].extend(
            (predecessor, duplicate_predecessor)
        )
        duplicate_bundle["parent_status_by_id"][predecessor_parent] = "committed"
        duplicate_errors = storage.verify_precommit_snapshot(**duplicate_bundle)
        self.assertTrue(
            any("predecessor" in error and "exactly one" in error for error in duplicate_errors),
            duplicate_errors,
        )

        cases = (
            ("absent", None, None),
            ("wrong-record", {"Record Key": "different-record"}, "committed"),
            ("wrong-revision", {"Revision": 7}, "committed"),
            ("bool-revision", {"Revision": True}, "committed"),
            ("string-revision", {"Revision": "1"}, "committed"),
            ("preparing-parent", {}, "preparing"),
            ("failed-parent", {}, "failed"),
        )
        for name, predecessor_changes, parent_status in cases:
            with self.subTest(name=name):
                changed = precommit_bundle(feed, successor)
                if predecessor_changes is not None:
                    changed_predecessor = {**predecessor, **predecessor_changes}
                    changed["memory_logical_rows"].append(changed_predecessor)
                if parent_status is not None:
                    changed["parent_status_by_id"][predecessor_parent] = parent_status
                self.assertTrue(storage.verify_precommit_snapshot(**changed))

    def test_committed_logical_rows_cannot_hide_malformed_identities(self):
        feed, _expected = feed_page()
        prior_parent = "43434343-4343-4434-8434-434343434343"
        malformed_memory, _expected = memory_page()
        malformed_memory.update(
            {
                "page_id": "44444444-4444-4444-8444-444444444444",
                "Record Key": [],
                "Revision": True,
                "Run": [prior_parent],
            }
        )
        malformed_report, _expected = report_page()
        malformed_report.update(
            {
                "page_id": "45454545-4545-4454-8454-454545454545",
                "Integration Key": [],
                "Run": [prior_parent],
            }
        )

        for label, projection, row in (
            ("Memory", "memory_logical_rows", malformed_memory),
            ("Report", "report_logical_rows", malformed_report),
        ):
            with self.subTest(label=label, status="committed"):
                bundle = precommit_bundle(feed)
                bundle[projection] = [row]
                bundle["parent_status_by_id"][prior_parent] = "committed"
                errors = storage.verify_precommit_snapshot(**bundle)
                self.assertTrue(
                    any(label in error and "malformed" in error for error in errors),
                    errors,
                )

            for terminal_status in ("failed", "superseded"):
                with self.subTest(label=label, status=terminal_status):
                    bundle = precommit_bundle(feed)
                    bundle[projection] = [row]
                    bundle["parent_status_by_id"][prior_parent] = terminal_status
                    self.assertEqual(
                        storage.verify_precommit_snapshot(**bundle),
                        [],
                    )

    def test_report_evidence_allows_same_run_expected_or_prior_committed_memory_only(self):
        feed, _ = feed_page()
        memory, _ = memory_page()
        report, _ = report_page()
        report["Evidence Records"] = [memory["page_id"]]
        self.assertEqual(
            storage.verify_precommit_snapshot(
                **precommit_bundle(feed, memory, report)
            ),
            [],
        )

        prior_parent = "99999999-9999-4999-8999-999999999997"
        prior = deepcopy(memory)
        prior.update(
            {
                "page_id": "99999999-9999-4999-8999-999999999996",
                "Record Key": "prior-record",
                "Revision Key": "prior-record:r000001:prior-run",
                "Run": [prior_parent],
            }
        )
        prior_report, _ = report_page()
        prior_report["Evidence Records"] = [prior["page_id"]]
        prior_bundle = precommit_bundle(feed, prior_report)
        prior_bundle["memory_logical_rows"].append(prior)
        prior_bundle["parent_status_by_id"][prior_parent] = "committed"
        self.assertEqual(storage.verify_precommit_snapshot(**prior_bundle), [])

        for status in (None, "preparing", "failed", "superseded"):
            with self.subTest(status=status):
                changed = precommit_bundle(feed, prior_report)
                changed["memory_logical_rows"].append(prior)
                if status is not None:
                    changed["parent_status_by_id"][prior_parent] = status
                self.assertTrue(storage.verify_precommit_snapshot(**changed))

        wrong_current_parent = "15151515-1515-4151-8151-151515151515"
        wrong_current = deepcopy(prior)
        wrong_current["Run"] = [wrong_current_parent]
        wrong_bundle = precommit_bundle(feed, prior_report)
        wrong_bundle["memory_logical_rows"].append(wrong_current)
        wrong_bundle["parent_status_by_id"][wrong_current_parent] = "preparing"
        self.assertTrue(storage.verify_precommit_snapshot(**wrong_bundle))

    def test_parent_status_projection_cannot_contradict_the_current_run(self):
        feed, _expected = feed_page()
        self.assertEqual(storage.verify_precommit_snapshot(**precommit_bundle(feed)), [])

        invalid_status_maps = (
            {},
            {RUN_PAGE_ID: "committed"},
            {RUN_PAGE_ID: []},
            {"opaque-parent": "preparing", RUN_PAGE_ID: "preparing"},
        )
        for status_map in invalid_status_maps:
            with self.subTest(status_map=status_map):
                bundle = precommit_bundle(feed)
                bundle["parent_status_by_id"] = status_map
                self.assertTrue(storage.verify_precommit_snapshot(**bundle))

        prior_parent = "30303030-3030-4303-8303-303030303030"
        with_prior = precommit_bundle(feed)
        with_prior["parent_status_by_id"][prior_parent] = "committed"
        self.assertEqual(storage.verify_precommit_snapshot(**with_prior), [])

    def test_precommit_inputs_are_not_mutated(self):
        feed, _ = feed_page()
        bundle = precommit_bundle(feed)
        before = deepcopy(bundle)
        self.assertEqual(storage.verify_precommit_snapshot(**bundle), [])
        self.assertEqual(bundle, before)

    def test_precommit_malformed_projection_iterables_return_blocking_errors(self):
        feed, _expected = feed_page()
        self.assertEqual(storage.verify_precommit_snapshot(**precommit_bundle(feed)), [])

        iterable_parameters = (
            "slot_rows",
            "exact_run_rows",
            "memory_logical_rows",
            "report_logical_rows",
            "integration_rows",
        )
        for parameter in iterable_parameters:
            for invalid in (None, "not-rows", {}, 7):
                with self.subTest(parameter=parameter, invalid=invalid):
                    bundle = precommit_bundle(feed)
                    bundle[parameter] = invalid
                    errors = storage.verify_precommit_snapshot(**bundle)
                    self.assertIsInstance(errors, list)
                    self.assertTrue(errors)

        for kind in ("feed", "memory", "report"):
            for invalid in (None, "not-rows", {}, 7):
                with self.subTest(projection=kind, invalid=invalid):
                    bundle = precommit_bundle(feed)
                    bundle["child_rows_by_kind"][kind] = invalid
                    errors = storage.verify_precommit_snapshot(**bundle)
                    self.assertIsInstance(errors, list)
                    self.assertTrue(errors)

        for projection in ("child_rows_by_kind", "expected_child_ids"):
            for invalid in (None, [], "not-a-map", {}):
                with self.subTest(projection=projection, invalid=invalid):
                    bundle = precommit_bundle(feed)
                    bundle[projection] = invalid
                    errors = storage.verify_precommit_snapshot(**bundle)
                    self.assertIsInstance(errors, list)
                    self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
