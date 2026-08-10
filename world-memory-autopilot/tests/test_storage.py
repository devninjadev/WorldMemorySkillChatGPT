from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import inspect
import math
import textwrap
import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

import world_memory.contracts as contracts
import world_memory.scheduler as scheduler
from world_memory import storage
from world_memory.storage import (
    base_database_schemas,
    canonical_digest,
    canonical_json_bytes,
    decode_notion_body,
    encode_notion_body,
    installation_key,
    relation_statements,
    run_key,
    slot_key,
)


WORKSPACE_ID = "123e4567-e89b-42d3-a456-426614174000"
INSTALLATION_KEY = "wm:123e4567-e89b-42d3-a456-426614174000:default"
DATA_SOURCE_IDS = {
    "installations": "11111111-1111-4111-8111-111111111111",
    "runs": "22222222-2222-4222-8222-222222222222",
    "feed_batches": "33333333-3333-4333-8333-333333333333",
    "memory": "44444444-4444-4444-8444-444444444444",
    "reports": "55555555-5555-4555-8555-555555555555",
}
INSTALLATION_PAGE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def fixture_id(label: str) -> str:
    try:
        UUID(label)
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"world-memory-test:{label}"))
    return label


def fixture_ids(*labels: str) -> set[str]:
    return {fixture_id(label) for label in labels}


def legacy_notion_body(payload: object, rendering: str = "") -> str:
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    encoded = base64.b64encode(raw).decode("ascii")
    wrapped = "\n".join(textwrap.wrap(encoded, width=76))
    body = (
        "## Canonical Payload\n```text\nwm-body-v1\n"
        f"sha256:{digest}\n{wrapped}\n```"
    )
    if rendering:
        body += f"\n\n## Korean Rendering\n{rendering}"
    return body


def operational_installation() -> dict:
    return {
        "page_id": INSTALLATION_PAGE_ID,
        "Name": INSTALLATION_KEY,
        "Installation Key": INSTALLATION_KEY,
        "Hub Page ID": "99999999-9999-4999-8999-999999999999",
        "Hub URL": "https://www.notion.so/world-memory-hub",
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
        "Created At": "2026-08-10T00:00:00Z",
        "Updated At": "2026-08-10T00:00:00Z",
    }


class LegacySurfaceTests(unittest.TestCase):
    def test_filesystem_bundle_and_manifest_mutation_apis_are_absent(self):
        legacy_by_module = {
            contracts: (
                "REQUIRED_FILES", "_JSON_FILES", "UTC_FIELDS", "COLLECTOR_STATUSES",
                "validate_bundle", "_validate_manifest", "_validate_json_file",
                "_validate_jsonl_line",
            ),
            storage: (
                "CommitError", "_VersionConflict", "validate_replacement_bytes",
                "commit_bundle", "bootstrap_directory",
            ),
            scheduler: (
                "apply_feed_outcome", "apply_world_memory_success",
                "initial_next_world_memory",
            ),
        }
        for module, names in legacy_by_module.items():
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertFalse(hasattr(module, name))

        for module in (contracts, storage, scheduler):
            imported_names = set(vars(module))
            for name in (
                "REQUIRED_FILES", "validate_bundle", "CommitError",
                "bootstrap_directory", "commit_bundle", "validate_replacement_bytes",
            ):
                with self.subTest(module=module.__name__, imported=name):
                    self.assertNotIn(name, imported_names)

NOW = datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc)
SLOT_KEY = "wms_b12ee94ad696_scheduled_20260810T010000Z"
STRICT_RUN_KEY = f"{SLOT_KEY}_a001"


def task2_call(name: str, *args, **kwargs):
    function = getattr(storage, name, None)
    if function is None:
        raise AssertionError(f"missing Task 2 storage API: {name}")
    if (
        name == "verify_precommit_snapshot"
        and any(
            parameter in kwargs and parameter not in inspect.signature(function).parameters
            for parameter in (
                "expected_child_pages_by_kind", "expected_run_snapshot",
            )
        )
    ):
        raise AssertionError("verify_precommit_snapshot lacks an expected snapshot API")
    return function(*args, **kwargs)


def notion_run(
    attempt: int,
    status: str,
    *,
    slot: str = SLOT_KEY,
    started_at: datetime = NOW - timedelta(minutes=10),
    page_id: str | None = None,
    output_prepared: bool = False,
    integration_key: str = "",
) -> dict:
    physical_run_key = f"{slot}_a{attempt:03d}"
    return {
        "page_id": fixture_id(page_id or f"run-{attempt}-{status}"),
        "Name": physical_run_key,
        "Slot Key": slot,
        "Run Key": physical_run_key,
        "Integration Key": integration_key,
        "Attempt": attempt,
        "Trigger": "scheduled",
        "Status": status,
        "Started At": started_at.isoformat().replace("+00:00", "Z"),
        "Scheduled Slot": "2026-08-10T01:00:00Z",
        "Collection Cutoff": "2026-08-10T02:00:00Z",
        "Finished At": "",
        "Feed Success Count": 5,
        "Feed Failure Count": 0,
        "New Item Count": 0,
        "Material Change": False,
        "Integration Due": False,
        "Integration Performed": False,
        "Installation": [INSTALLATION_PAGE_ID],
        "Output Prepared": output_prepared,
        "Cache Reconciled": False,
        "Notification Plan": "silent",
        "Input Digest": "1" * 64,
        "Output Digest": "2" * 64,
        "Error Summary": "",
        "Created At": "2026-08-10T01:50:00.123Z",
        "Updated At": "2026-08-10T02:00:01.456Z",
        "body": encode_notion_body(run_audit()),
    }


def prepared_run(
    attempt: int = 1,
    *,
    page_id: str = "run-current",
    integration_key: str = "",
) -> dict:
    return notion_run(
        attempt, "preparing", page_id=page_id,
        integration_key=integration_key, output_prepared=True,
    )


def validation_parent(
    page_id: str,
    *,
    material_change: bool = False,
    integration_key: str = "",
) -> dict:
    run = prepared_run(page_id=page_id, integration_key=integration_key)
    run["Material Change"] = material_change
    if material_change and not integration_key:
        run["Notification Plan"] = "hourly-briefing"
    return run


def feed_item(index: int, *, status: str = "pending", published_at: str | None = None) -> dict:
    fingerprint = f"{index:064x}"
    published = published_at or f"2026-08-10T01:{index % 60:02d}:00Z"
    return {
        "schemaVersion": 1,
        "id": f"nf_{fingerprint[:18]}",
        "sourceFingerprint": fingerprint,
        "feedId": "financial_juice",
        "feedTitle": "FinancialJuice",
        "feedSourceUrl": "https://rss.app/feeds/5VaycMAa8SwPhOAP.xml",
        "sourceUrl": f"https://example.com/items/{index}",
        "title": f"Headline {index}",
        "sourcePublishedAt": published,
        "publishedAt": published,
        "publishedAtOffsetMinutes": 0,
        "fetchedAt": "2026-08-10T01:59:00Z",
        "status": status,
        "importanceCandidate": "unassessed",
    }


def fingerprint_entry(index: int, published_at: str | None = None) -> dict:
    return {
        "sourceFingerprint": f"{index:064x}",
        "publishedAt": published_at or f"2026-08-10T01:{index % 60:02d}:00Z",
    }


def source_outcomes() -> list[dict]:
    return [
        {"feedId": "financial_juice", "status": "ok", "itemCount": 1, "cursor": "", "error": ""},
        {"feedId": "walter_bloomberg", "status": "ok", "itemCount": 0, "cursor": "", "error": ""},
        {"feedId": "wall_st_engine", "status": "ok", "itemCount": 0, "cursor": "", "error": ""},
        {"feedId": "first_squawk", "status": "ok", "itemCount": 0, "cursor": "", "error": ""},
        {"feedId": "unusual_whales", "status": "ok", "itemCount": 0, "cursor": "", "error": ""},
    ]


def valid_report_payload() -> dict:
    return {
        "schemaVersion": 2,
        "title": "World Memory",
        "asOf": "2026-08-10T02:00:00Z",
        "coverage": "6h",
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
            "기준": {
                "activation": "기준 활성화",
                "transmission": "기준 전달",
                "invalidation": "기준 무효화",
                "nextCheck": "기준 다음 확인",
            },
            "낙관": {
                "activation": "낙관 활성화",
                "transmission": "낙관 전달",
                "invalidation": "낙관 무효화",
                "nextCheck": "낙관 다음 확인",
            },
            "비관": {
                "activation": "비관 활성화",
                "transmission": "비관 전달",
                "invalidation": "비관 무효화",
                "nextCheck": "비관 다음 확인",
            },
        },
    }


def feed_batch_payload(
    run_key_value: str,
    part_index: int,
    part_count: int,
    items: list[dict],
    *,
    fetched_at: str = "2026-08-10T01:59:00Z",
    new_item_count: int | None = None,
    outcomes: list[dict] | None = None,
    window: list[dict] | None = None,
) -> dict:
    current_items = deepcopy(items)
    for item in current_items:
        if isinstance(item, dict) and "fetchedAt" in item:
            item["fetchedAt"] = fetched_at
    total_new = len(current_items) if new_item_count is None else new_item_count
    current_outcomes = deepcopy(source_outcomes() if outcomes is None else outcomes)
    if outcomes is None:
        current_outcomes[0]["itemCount"] = total_new
    payload = {
        "schemaVersion": 2,
        "kind": "feed-batch",
        "runKey": run_key_value,
        "batchKey": f"{run_key_value}:feed:{part_index:03d}",
        "partIndex": part_index,
        "partCount": part_count,
        "fetchedAt": fetched_at,
        "newItemCount": total_new,
        "sourceOutcomes": current_outcomes,
        "items": current_items,
    }
    if part_index == 1:
        payload["fingerprintWindow"] = (
            [
                {
                    "sourceFingerprint": item["sourceFingerprint"],
                    "publishedAt": item["publishedAt"],
                }
                for item in current_items
                if isinstance(item, dict)
                and "sourceFingerprint" in item
                and "publishedAt" in item
            ]
            if window is None
            else window
        )
    return payload


def feed_batch_child(page_id: str, parent_id: str, payload: dict) -> tuple[dict, dict]:
    outcomes = payload["sourceOutcomes"]
    successes = sum(outcome["status"] == "ok" for outcome in outcomes)
    properties = {
        "Batch Key": payload["batchKey"],
        "Run Key": payload["runKey"],
        "Part Index": payload["partIndex"],
        "Part Count": payload["partCount"],
        "Feed Success Count": successes,
        "Feed Failure Count": len(outcomes) - successes,
        "New Item Count": payload["newItemCount"],
        "Item Count": len(payload["items"]),
        "Fetched At": payload["fetchedAt"],
        "All Sources Failed": successes == 0,
    }
    page, expected = child_page("feed", page_id, parent_id, properties, payload)
    return page, expected


def child_page(kind: str, page_id: str, parent_id: str, properties: dict, payload: dict,
               rendering: str = "") -> tuple[dict, dict]:
    physical_field = {
        "feed": "Batch Key", "memory": "Revision Key", "report": "Report Key",
    }[kind]
    current_properties = deepcopy(properties)
    current_properties.setdefault("Name", current_properties.get(physical_field, kind))
    if kind == "memory":
        current_properties.setdefault("Dedupe Key", payload.get("dedupe_key", ""))
        current_properties.setdefault("Continuity ID", payload.get("continuityId", ""))
        current_properties.setdefault("Target", payload.get("target", ""))
        current_properties.setdefault("Record Type", payload.get("recordType"))
        current_properties.setdefault("Record Status", payload.get("recordStatus", "active"))
        current_properties.setdefault("Importance", payload.get("importance", "medium"))
        current_properties.setdefault("Category", payload.get("category", "emerging"))
        current_properties.setdefault("Region", payload.get("region", "GLOBAL"))
        current_properties.setdefault("Action", payload.get("action"))
        current_properties.setdefault("Confidence", payload.get("confidence"))
        current_properties.setdefault("Effective At", payload.get("effectiveAt", ""))
        current_properties.setdefault("Verified Evidence", bool(payload.get("evidence")))
        current_properties.setdefault("Updated At", "2026-08-10T02:00:01Z")
        if isinstance(current_properties.get("Supersedes"), list):
            current_properties["Supersedes"] = [
                fixture_id(value) for value in current_properties["Supersedes"]
            ]
    if kind == "report":
        current_properties.setdefault("As Of", payload.get("asOf"))
        current_properties.setdefault("Coverage Start", "")
        current_properties.setdefault("Coverage End", payload.get("asOf"))
        current_properties.setdefault("Stance", payload.get("stance"))
        current_properties.setdefault("Confidence", payload.get("confidence"))
        current_properties.setdefault(
            "Data Gap Count", len(payload.get("dataQuality", {}).get("gaps", []))
        )
        current_properties.setdefault("Material Change", True)
        current_properties.setdefault("User Visible", True)
        current_properties.setdefault("Evidence Records", [])
        current_properties["Evidence Records"] = [
            fixture_id(value) for value in current_properties["Evidence Records"]
        ]
    current_properties.setdefault("Created At", "2026-08-10T02:00:01Z")
    page = {
        "page_id": fixture_id(page_id),
        **current_properties,
        "Run": [fixture_id(parent_id)],
        "Body Format": storage.BODY_FORMAT,
        "Payload Digest": canonical_digest(payload),
        "body": encode_notion_body(payload, rendering),
        "payload": payload,
    }
    if kind == "feed":
        page["Fingerprint Window Digest"] = (
            canonical_digest(payload["fingerprintWindow"])
            if payload.get("partIndex") == 1
            else ""
        )
    if kind == "report":
        import hashlib

        page["Rendering Digest"] = hashlib.sha256(rendering.encode()).hexdigest()
        page["rendering"] = rendering
    expected = deepcopy(page)
    return page, expected


def run_audit(*pages: dict) -> dict:
    inventory = {"feed": [], "memory": [], "report": []}
    for page in pages:
        if "Batch Key" in page:
            inventory["feed"].append({
                "key": page["Batch Key"], "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
                "fingerprintWindowDigest": page["Fingerprint Window Digest"],
            })
        elif "Revision Key" in page:
            inventory["memory"].append({
                "key": page["Revision Key"], "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
            })
        else:
            inventory["report"].append({
                "key": page["Report Key"], "pageId": page["page_id"],
                "payloadDigest": page["Payload Digest"],
                "renderingDigest": page["Rendering Digest"],
            })
    for rows in inventory.values():
        rows.sort(key=lambda row: row["key"])
    feed_pages = [page for page in pages if "Batch Key" in page]
    if feed_pages:
        outcomes = deepcopy(feed_pages[0]["payload"]["sourceOutcomes"])
        new_item_count = feed_pages[0]["payload"]["newItemCount"]
    else:
        outcomes = [
            {
                "feedId": outcome["feedId"],
                "status": "error",
                "itemCount": 0,
                "cursor": "",
                "error": "not collected",
            }
            for outcome in source_outcomes()
        ]
        new_item_count = 0
    success_count = sum(outcome["status"] == "ok" for outcome in outcomes)
    return {
        "timestamp": "2026-08-10T02:00:00Z", "trigger": "scheduled",
        "feed": {
            "sourceOutcomes": outcomes,
            "successCount": success_count,
            "failureCount": len(outcomes) - success_count,
            "newItemCount": new_item_count,
        },
        "materialChange": {}, "worldMemory": {},
        "notification": {}, "audit": {"expectedChildren": inventory},
        "commit": {},
    }


def valid_memory_payload() -> dict:
    evidence = [{"name": "Primary source", "url": "https://example.com/source"}]
    return {
        "schemaVersion": 2, "kind": "memory", "recordType": "state",
        "action": "state-add", "target": "record-a", "evidence": evidence,
        "sources": evidence, "confidence": 0.8, "result": True,
        "state_key": "record-a", "recordStatus": "active",
        "importance": "medium", "category": "emerging", "region": "GLOBAL",
        "effectiveAt": "2026-08-10T02:00:00Z",
    }


def strict_precommit_context(current: dict, *supplied_pages: dict) -> dict:
    run = deepcopy(current)
    pages = [deepcopy(page) for page in supplied_pages]
    six_hour_reports = [
        page
        for page in pages
        if page.get("Report Type") == "six-hour"
    ]
    if run["Integration Key"] and not six_hour_reports:
        payload = valid_report_payload()
        report, _expected = child_page(
            "report",
            f"six-hour-report-for-{run['page_id']}",
            run["page_id"],
            {
                "Report Key": (
                    f"{run['Integration Key']}:report:six-hour:{run['Run Key']}"
                ),
                "Run Key": run["Run Key"],
                "Integration Key": run["Integration Key"],
                "Report Type": "six-hour",
            },
            payload,
            "한국어 6시간 보고서",
        )
        pages.append(report)
        six_hour_reports.append(report)
    feed_pages = [page for page in pages if "Batch Key" in page]
    if not feed_pages:
        payload = feed_batch_payload(
            run["Run Key"], 1, 1, [], new_item_count=0, window=[]
        )
        feed, _expected = feed_batch_child(
            f"feed-for-{run['page_id']}", run["page_id"], payload
        )
        pages.append(feed)
        feed_pages.append(feed)
    first_feed = min(feed_pages, key=lambda page: page["Part Index"])
    visible_reports = [page for page in pages if "Report Key" in page]
    run.update(
        {
            "Feed Success Count": first_feed["Feed Success Count"],
            "Feed Failure Count": first_feed["Feed Failure Count"],
            "New Item Count": first_feed["New Item Count"],
            "Material Change": bool(visible_reports),
            "Integration Due": bool(six_hour_reports),
            "Integration Performed": bool(six_hour_reports),
            "Notification Plan": (
                "six-hour" if six_hour_reports
                else "hourly-briefing" if visible_reports
                else "silent"
            ),
            "body": encode_notion_body(run_audit(*pages)),
        }
    )
    by_kind: dict[str, list[dict]] = {"feed": [], "memory": [], "report": []}
    ids: dict[str, dict[str, str]] = {"feed": {}, "memory": {}, "report": {}}
    snapshots: dict[str, dict[str, dict]] = {
        "feed": {}, "memory": {}, "report": {},
    }
    physical_fields = {
        "feed": "Batch Key", "memory": "Revision Key", "report": "Report Key",
    }
    for page in pages:
        kind = (
            "feed" if "Batch Key" in page
            else "memory" if "Revision Key" in page
            else "report"
        )
        physical_key = page[physical_fields[kind]]
        by_kind[kind].append(page)
        ids[kind][physical_key] = page["page_id"]
        snapshots[kind][physical_key] = deepcopy(page)
    return {
        "slot_rows": [deepcopy(run)],
        "exact_run_rows": [deepcopy(run)],
        "expected_run_page_id": run["page_id"],
        "child_rows_by_kind": by_kind,
        "expected_child_ids": ids,
        "expected_child_pages_by_kind": snapshots,
        "expected_run_snapshot": {
            key: deepcopy(value)
            for key, value in run.items()
            if key != "page_id"
        },
        "memory_logical_rows": deepcopy(by_kind["memory"]),
        "report_logical_rows": deepcopy([
            page for page in by_kind["report"]
            if page.get("Report Type") == "six-hour"
        ]),
        "parent_status_by_id": {run["page_id"]: "preparing"},
        "integration_rows": [deepcopy(run)] if run["Integration Key"] else [],
        "installation_snapshot": operational_installation(),
    }

EXPECTED_BASE_SCHEMAS = {
    "installations": '''CREATE TABLE (
"Name" TITLE, "Installation Key" RICH_TEXT, "Hub Page ID" RICH_TEXT,
"Hub URL" URL, "Status" SELECT('initializing':yellow, 'active':green, 'paused':gray, 'error':red),
"Enabled" CHECKBOX, "Autopilot Enabled" CHECKBOX, "Timezone" SELECT('Asia/Seoul':blue),
"Hourly Interval Minutes" NUMBER, "World Memory Interval Hours" NUMBER,
"Schema Version" NUMBER, "Skill Contract Version" RICH_TEXT, "Feed Cursor State" RICH_TEXT,
"Last Feed Attempt" DATE, "Last Feed Success" DATE, "Last World Memory Success" DATE,
"Last Report Success" DATE, "Next World Memory At" DATE, "Last Briefing At" DATE,
"Last Error" RICH_TEXT, "Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)''',
    "runs": '''CREATE TABLE (
"Name" TITLE, "Slot Key" RICH_TEXT, "Run Key" RICH_TEXT, "Integration Key" RICH_TEXT, "Attempt" NUMBER,
"Trigger" SELECT('scheduled':blue, 'manual':green, 'force-world-memory':orange),
"Status" SELECT('preparing':yellow, 'committed':green, 'failed':red, 'superseded':gray),
"Started At" DATE, "Scheduled Slot" DATE, "Collection Cutoff" DATE, "Finished At" DATE,
"Feed Success Count" NUMBER, "Feed Failure Count" NUMBER, "New Item Count" NUMBER,
"Material Change" CHECKBOX, "Integration Due" CHECKBOX, "Integration Performed" CHECKBOX,
"Output Prepared" CHECKBOX, "Cache Reconciled" CHECKBOX,
"Notification Plan" SELECT('silent':gray, 'hourly-briefing':blue, 'six-hour':purple, 'error':red),
"Input Digest" RICH_TEXT, "Output Digest" RICH_TEXT, "Error Summary" RICH_TEXT,
"Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)''',
    "feed_batches": '''CREATE TABLE (
"Name" TITLE, "Batch Key" RICH_TEXT, "Run Key" RICH_TEXT, "Payload Digest" RICH_TEXT,
"Fingerprint Window Digest" RICH_TEXT, "Body Format" RICH_TEXT,
"Part Index" NUMBER, "Part Count" NUMBER, "Feed Success Count" NUMBER,
"Feed Failure Count" NUMBER, "New Item Count" NUMBER, "Item Count" NUMBER,
"Fetched At" DATE, "All Sources Failed" CHECKBOX, "Created At" CREATED_TIME)''',
    "memory": '''CREATE TABLE (
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
"Verified Evidence" CHECKBOX, "Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)''',
    "reports": '''CREATE TABLE (
"Name" TITLE, "Report Key" RICH_TEXT, "Run Key" RICH_TEXT, "Integration Key" RICH_TEXT, "Payload Digest" RICH_TEXT,
"Rendering Digest" RICH_TEXT, "Body Format" RICH_TEXT,
"Report Type" SELECT('hourly-briefing':blue, 'six-hour':purple),
"As Of" DATE, "Coverage Start" DATE, "Coverage End" DATE,
"Stance" SELECT('risk-on':green, 'neutral':gray, 'defensive':red, 'mixed':yellow),
"Confidence" NUMBER, "Data Gap Count" NUMBER, "Material Change" CHECKBOX,
"User Visible" CHECKBOX, "Created At" CREATED_TIME)''',
}


class KeyTests(unittest.TestCase):
    def test_installation_slot_and_run_keys_use_literal_contract(self):
        self.assertEqual(installation_key(WORKSPACE_ID), INSTALLATION_KEY)
        slot = slot_key(
            INSTALLATION_KEY,
            "scheduled",
            datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(slot, "wms_b12ee94ad696_scheduled_20260810T010000Z")
        self.assertEqual(
            run_key(slot, 1),
            "wms_b12ee94ad696_scheduled_20260810T010000Z_a001",
        )

    def test_slot_key_rejects_unknown_trigger_and_naive_datetime(self):
        with self.assertRaises(ValueError):
            slot_key(INSTALLATION_KEY, "surprise", datetime(2026, 8, 10, 1, 0))
        with self.assertRaises(ValueError):
            slot_key(INSTALLATION_KEY, "scheduled", datetime(2026, 8, 10, 1, 0))

    def test_slot_key_floors_scheduled_hour_and_direct_run_minute_in_utc(self):
        utc_instant = datetime(2026, 8, 10, 1, 37, 42, 123456, tzinfo=timezone.utc)
        equivalent = datetime.fromisoformat("2026-08-10T10:37:59.999999+09:00")
        self.assertEqual(
            slot_key(INSTALLATION_KEY, "scheduled", utc_instant),
            "wms_b12ee94ad696_scheduled_20260810T010000Z",
        )
        self.assertEqual(
            slot_key(INSTALLATION_KEY, "scheduled", equivalent),
            "wms_b12ee94ad696_scheduled_20260810T010000Z",
        )
        self.assertEqual(
            slot_key(INSTALLATION_KEY, "manual", utc_instant),
            "wms_b12ee94ad696_manual_20260810T013700Z",
        )
        self.assertEqual(
            slot_key(INSTALLATION_KEY, "force-world-memory", equivalent),
            "wms_b12ee94ad696_force-world-memory_20260810T013700Z",
        )

    def test_run_key_rejects_attempt_outside_three_digit_contract(self):
        for attempt in (0, 1000, True):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                run_key("wms_b12ee94ad696_scheduled_20260810T010000Z", attempt)


class CanonicalBodyTests(unittest.TestCase):
    def test_canonical_json_rejects_excessive_nesting_as_value_error(self):
        value: object = 0
        for _ in range(1500):
            value = [value]
        with self.assertRaisesRegex(ValueError, "nesting"):
            canonical_json_bytes(value)

    def test_canonical_json_rejects_unpaired_surrogates_as_invalid_utf8(self):
        for value in ({"\ud800": 1}, "\ud800"):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(ValueError, "valid UTF-8"):
                    canonical_json_bytes(value)

    def test_canonical_json_and_digest_match_literal_values(self):
        value = {"b": 2, "a": "한글"}
        self.assertEqual(canonical_json_bytes(value), '{"a":"한글","b":2}'.encode())
        self.assertEqual(
            canonical_digest(value),
            "d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1",
        )

    def test_installation_cache_properties_match_notion_update_shape(self):
        encoder = getattr(storage, "installation_cache_properties", None)
        self.assertIsNotNone(encoder, "installation cache encoder is missing")
        normalized = operational_installation()
        normalized["Feed Cursor State"] = {
            "financial_juice": "1" * 64,
            "walter_bloomberg": "2" * 64,
            "wall_st_engine": "3" * 64,
            "first_squawk": "4" * 64,
            "unusual_whales": "5" * 64,
        }
        normalized["Last Feed Attempt"] = "2026-08-10T01:00:00Z"
        normalized["Last Error"] = "first_squawk: timeout"

        properties = encoder(normalized)

        cursor_text = (
            '{"financial_juice":"' + "1" * 64
            + '","first_squawk":"' + "4" * 64
            + '","unusual_whales":"' + "5" * 64
            + '","wall_st_engine":"' + "3" * 64
            + '","walter_bloomberg":"' + "2" * 64 + '"}'
        )
        self.assertEqual(properties, {
            "Feed Cursor State": cursor_text,
            "Last Error": "first_squawk: timeout",
            "date:Last Feed Attempt:start": "2026-08-10T01:00:00Z",
            "date:Last Feed Attempt:is_datetime": 1,
            "date:Last Feed Success:start": None,
            "date:Last World Memory Success:start": None,
            "date:Last Report Success:start": None,
            "date:Next World Memory At:start": None,
            "date:Last Briefing At:start": None,
        })
        raw = {**normalized, "Feed Cursor State": properties["Feed Cursor State"]}
        self.assertEqual(
            scheduler.validate_installation_row(
                raw,
                INSTALLATION_KEY,
                normalized["Hub Page ID"],
                normalized["Hub URL"],
            ),
            [],
        )

    def test_canonical_json_rejects_non_json_numbers_and_objects(self):
        for value in (
            {"number": math.nan},
            {"number": math.inf},
            {"number": -math.inf},
            {1: "value"},
            {"nested": [{False: "value"}]},
            object(),
        ):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                canonical_json_bytes(value)

    def test_body_uses_exact_markers_and_round_trips_rendering(self):
        payload = {"b": 2, "a": "한글"}
        body = encode_notion_body(payload, "한국어 렌더링")
        self.assertEqual(
            body,
            "## Canonical Payload\n```text\n"
            "wm-body-v2\n"
            "sha256:d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1\n"
            '{"a":"한글","b":2}\n```\n\n'
            "## Korean Rendering\n한국어 렌더링",
        )
        self.assertEqual(decode_notion_body(body), (payload, "한국어 렌더링"))

    def test_decode_preserves_wm_body_v1_read_compatibility(self):
        payload = {"b": 2, "a": "한글"}
        body = legacy_notion_body(payload, "기존 렌더링")
        self.assertEqual(decode_notion_body(body), (payload, "기존 렌더링"))

    def test_decode_rejects_rendering_before_canonical_or_unheaded_trailing_text(self):
        rendering_first = (
            "한국어 렌더링\n\n## Canonical Payload\n```text\nwm-body-v1\n"
            "sha256:d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1\n"
            "eyJhIjoi7ZWc6riAIiwiYiI6Mn0=\n```"
        )
        unheaded_trailing = (
            "## Canonical Payload\n```text\nwm-body-v1\n"
            "sha256:d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1\n"
            "eyJhIjoi7ZWc6riAIiwiYiI6Mn0=\n```\n\n한국어 렌더링"
        )
        for body in (rendering_first, unheaded_trailing):
            with self.subTest(body=body), self.assertRaises(ValueError):
                decode_notion_body(body)

    def test_body_stores_searchable_canonical_json_without_base64(self):
        payload = {"title": "검색 가능한 기사 제목", "url": "https://example.com/story"}
        body = encode_notion_body(payload)
        self.assertIn(canonical_json_bytes(payload).decode("utf-8"), body)
        self.assertIn("검색 가능한 기사 제목", body)
        self.assertNotIn(base64.b64encode(canonical_json_bytes(payload)).decode("ascii"), body)

    def test_decode_rejects_malformed_legacy_base64_and_digest_changing_body(self):
        malformed = (
            "## Canonical Payload\n```text\nwm-body-v1\nsha256:"
            "d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1\n%%%\n```"
        )
        changed = (
            "## Canonical Payload\n```text\nwm-body-v1\nsha256:"
            "d6ad94428fb66348c062045f84283b49c816b309fa21aa928f1b6a03168822e1\n"
            "eyJhIjoxfQ==\n```"
        )
        for body in (malformed, changed):
            with self.subTest(body=body), self.assertRaises(ValueError):
                decode_notion_body(body)

    def test_decode_rejects_digest_matching_noncanonical_json(self):
        body = (
            "## Canonical Payload\n```text\nwm-body-v1\n"
            "sha256:d0ed52f9264c29a600df1013daf0d1661f8f23390be6b58008de7e7d33c01080\n"
            "eyJiIjoyLCAiYSI6MX0=\n```"
        )
        with self.assertRaises(ValueError):
            decode_notion_body(body)

    def test_decode_rejects_digest_matching_noncanonical_v2_json(self):
        body = (
            "## Canonical Payload\n```text\nwm-body-v2\n"
            "sha256:d0ed52f9264c29a600df1013daf0d1661f8f23390be6b58008de7e7d33c01080\n"
            '{"b":2, "a":1}\n```'
        )
        with self.assertRaises(ValueError):
            decode_notion_body(body)


class SchemaDDLTests(unittest.TestCase):
    def test_base_schemas_match_exact_relation_free_ddls(self):
        self.assertEqual(base_database_schemas(), EXPECTED_BASE_SCHEMAS)
        self.assertTrue(all("RELATION" not in ddl for ddl in base_database_schemas().values()))

    def test_relation_statements_are_exact_and_independently_retryable(self):
        self.assertEqual(relation_statements(DATA_SOURCE_IDS), {
            "runs": (
                'ADD COLUMN "Installation" RELATION(\'11111111-1111-4111-8111-111111111111\', DUAL \'Runs\')',
            ),
            "feed_batches": (
                'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Feed Batches\')',
            ),
            "memory": (
                'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Memory Records\')',
                'ADD COLUMN "Supersedes" RELATION(\'44444444-4444-4444-8444-444444444444\')',
            ),
            "reports": (
                'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Reports\')',
                'ADD COLUMN "Evidence Records" RELATION(\'44444444-4444-4444-8444-444444444444\')',
            ),
        })

    def test_relation_statements_reject_missing_extra_or_non_uuid_ids(self):
        invalid_maps = [
            {key: value for key, value in DATA_SOURCE_IDS.items() if key != "reports"},
            {**DATA_SOURCE_IDS, "extra": "66666666-6666-4666-8666-666666666666"},
            {**DATA_SOURCE_IDS, "memory": "not-a-uuid"},
        ]
        for ids in invalid_maps:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                relation_statements(ids)


class RowResolutionTests(unittest.TestCase):
    def test_installation_and_exact_child_resolution_use_zero_one_many(self):
        installation = {"page_id": "installation-1", "Installation Key": INSTALLATION_KEY}
        other = {"page_id": "other", "Installation Key": "wm:other:default"}
        self.assertEqual(
            task2_call("resolve_installation_rows", [other], INSTALLATION_KEY),
            {"action": "create"},
        )
        self.assertEqual(
            task2_call("resolve_installation_rows", [other, installation], INSTALLATION_KEY),
            {"action": "reuse", "row": installation},
        )
        self.assertEqual(
            task2_call(
                "resolve_installation_rows",
                [installation, {**installation, "page_id": "installation-2"}],
                INSTALLATION_KEY,
            ),
            {"action": "conflict", "count": 2},
        )
        child = {"page_id": "batch-1", "Batch Key": "run:feed:001"}
        self.assertEqual(
            task2_call("resolve_exact_key", [child], "Batch Key", "run:feed:001"),
            {"action": "reuse", "row": child},
        )
        self.assertEqual(
            task2_call(
                "resolve_exact_key",
                [child, {**child, "page_id": "batch-2"}],
                "Batch Key",
                "run:feed:001",
            ),
            {"action": "conflict", "count": 2},
        )

    def test_partial_bootstrap_and_uncertain_create_requery_reuse_the_single_row(self):
        initializing = {
            "page_id": "installation-initializing",
            "Installation Key": INSTALLATION_KEY,
            "Status": "initializing",
        }
        created_child = {"page_id": "feed-uncertain", "Batch Key": "run:feed:001"}
        self.assertEqual(
            task2_call("resolve_installation_rows", [initializing], INSTALLATION_KEY)["row"],
            initializing,
        )
        self.assertEqual(
            task2_call("resolve_exact_key", [created_child], "Batch Key", "run:feed:001"),
            {"action": "reuse", "row": created_child},
        )

    def test_slot_resolution_reuses_one_committed_or_creates_next_attempt(self):
        committed = notion_run(1, "committed")
        failed = notion_run(2, "failed")
        self.assertEqual(
            task2_call(
                "resolve_slot_runs", [committed, failed], SLOT_KEY, NOW,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            ),
            {"action": "reuse-committed", "run": committed},
        )
        self.assertEqual(
            task2_call(
                "resolve_slot_runs", [notion_run(1, "failed")], SLOT_KEY, NOW,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            ),
            {"action": "create-attempt", "attempt": 2, "run_key": f"{SLOT_KEY}_a002"},
        )
        self.assertEqual(
            task2_call(
                "resolve_slot_runs", [], SLOT_KEY, NOW,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            ),
            {"action": "create-attempt", "attempt": 1, "run_key": f"{SLOT_KEY}_a001"},
        )

    def test_slot_resolution_rejects_committed_and_preparing_mixtures(self):
        committed = notion_run(1, "committed")
        preparing = notion_run(2, "preparing")
        result = task2_call(
            "resolve_slot_runs", [committed, preparing], SLOT_KEY, NOW,
            installation_key=INSTALLATION_KEY,
            installation_page_id=INSTALLATION_PAGE_ID,
        )
        self.assertEqual(result["action"], "conflict-committed")
        self.assertEqual(result["reason"], "committed-and-preparing")
        self.assertEqual(result["rows"], [committed, preparing])
        for rows in (
            [notion_run(1, "committed"), notion_run(2, "committed")],
            [notion_run(1, "preparing"), notion_run(2, "preparing")],
        ):
            with self.subTest(statuses=[row["Status"] for row in rows]):
                self.assertTrue(
                    task2_call(
                        "resolve_slot_runs", rows, SLOT_KEY, NOW,
                        installation_key=INSTALLATION_KEY,
                        installation_page_id=INSTALLATION_PAGE_ID,
                    )["action"].startswith(
                        "conflict-"
                    )
                )

    def test_exact_run_key_duplicate_conflicts_before_status_precedence(self):
        first = notion_run(1, "committed", page_id="run-one")
        duplicate = notion_run(1, "failed", page_id="run-two")
        result = task2_call(
            "resolve_slot_runs", [first, duplicate], SLOT_KEY, NOW,
            installation_key=INSTALLATION_KEY,
            installation_page_id=INSTALLATION_PAGE_ID,
        )
        self.assertEqual(result["action"], "conflict-committed")
        self.assertEqual(result["reason"], "duplicate-run-key")

    def test_fresh_preparing_conflicts_and_stale_singleton_is_inspected(self):
        resolution_now = NOW + timedelta(minutes=5)
        fresh = notion_run(
            1, "preparing", started_at=resolution_now - timedelta(minutes=64)
        )
        stale = notion_run(
            1, "preparing", started_at=resolution_now - timedelta(minutes=65)
        )
        self.assertEqual(
            task2_call(
                "resolve_slot_runs", [fresh], SLOT_KEY, resolution_now,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )["action"],
            "conflict-preparing",
        )
        self.assertEqual(
            task2_call(
                "resolve_slot_runs", [stale], SLOT_KEY, resolution_now,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            ),
            {"action": "inspect-stale-preparing", "run": stale},
        )

    def test_stale_preparing_resumes_only_with_complete_valid_children(self):
        stale_complete = notion_run(
            1,
            "preparing",
            started_at=NOW - timedelta(minutes=65),
            output_prepared=True,
        )
        stale_incomplete = {**stale_complete, "Output Prepared": False}
        fresh = {
            **stale_complete,
            "Started At": (NOW - timedelta(minutes=5)).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z"),
        }
        self.assertEqual(task2_call("stale_preparing_action", stale_complete, [], NOW), "resume")
        self.assertEqual(
            task2_call("stale_preparing_action", stale_incomplete, [], NOW),
            "terminalize-failed",
        )
        self.assertEqual(
            task2_call("stale_preparing_action", stale_complete, ["digest mismatch"], NOW),
            "terminalize-failed",
        )
        self.assertEqual(task2_call("stale_preparing_action", fresh, [], NOW), "conflict")

    def test_run_resolution_rejects_malformed_attempts_instead_of_choosing(self):
        malformed = notion_run(1, "failed")
        malformed["Attempt"] = True
        with self.assertRaises(ValueError):
            task2_call(
                "resolve_slot_runs", [malformed], SLOT_KEY, NOW,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )
        exhausted = notion_run(999, "failed")
        with self.assertRaises(ValueError):
            task2_call(
                "resolve_slot_runs", [exhausted], SLOT_KEY, NOW,
                installation_key=INSTALLATION_KEY,
                installation_page_id=INSTALLATION_PAGE_ID,
            )


class PhysicalIdentityAndPartitionTests(unittest.TestCase):
    def test_integration_report_memory_and_revision_keys_are_attempt_scoped(self):
        self.assertEqual(
            task2_call("integration_key", INSTALLATION_KEY, None),
            "wmi_b12ee94ad696_genesis",
        )
        cutoff = datetime.fromisoformat("2026-08-10T10:30:45+09:00")
        self.assertEqual(
            task2_call("integration_key", INSTALLATION_KEY, cutoff),
            "wmi_b12ee94ad696_previous-cutoff-20260810T013045Z",
        )
        with self.assertRaises(ValueError):
            task2_call("integration_key", INSTALLATION_KEY, datetime(2026, 8, 10, 1, 30))
        self.assertEqual(
            task2_call("report_key", f"{SLOT_KEY}_a001", "hourly-briefing"),
            f"{SLOT_KEY}_a001:report:hourly",
        )
        integration = "wmi_b12ee94ad696_genesis"
        self.assertEqual(
            task2_call("report_key", f"{SLOT_KEY}_a002", "six-hour", integration),
            f"{integration}:report:six-hour:{SLOT_KEY}_a002",
        )
        self.assertEqual(
            task2_call("revision_key", "wmrec_brief_abc", 2, f"{SLOT_KEY}_a002"),
            f"wmrec_brief_abc:r000002:{SLOT_KEY}_a002",
        )

    def test_report_key_rejects_cross_type_integration_identity(self):
        for integration in ("integration", None, False, 0):
            with self.subTest(integration=integration), self.assertRaises(ValueError):
                task2_call("report_key", "run-a001", "hourly-briefing", integration)
        with self.assertRaises(ValueError):
            task2_call("report_key", "run-a001", "six-hour", "")
        with self.assertRaises(ValueError):
            task2_call(
                "report_key",
                "run-a001",
                "six-hour",
                "wmi_b12ee94ad696_previous-cutoff-20260230T250000Z",
            )
        for revision in (0, 1_000_000, True):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                task2_call("revision_key", "record", revision, "run")

    def test_memory_record_keys_follow_type_specific_stable_identity(self):
        cases = (
            ("brief", {"dedupe_key": "event-1"}, "wmrec_brief_f21d0f12b6f51a7662"),
            ("state", {"state_key": "state-1"}, "wmrec_state_6b241220fdc91dfab7"),
            ("suggestion", {"continuityId": "cont-1"}, "wmrec_suggestion_0490d985cd286fbd23"),
            (
                "suggestion",
                {"action": "brief-add", "target": "portfolio"},
                "wmrec_suggestion_479ae4d555cdc047a0",
            ),
            ("taxonomy", {}, "wmrec_taxonomy_598c37a489b4f437c7"),
            ("story-link", {"story_key": "story-1"}, "wmrec_story-link_948562b5452a7c0072"),
            (
                "story-link",
                {"endpoints": ["omega", "alpha"]},
                "wmrec_story-link_8b681bb6b6c997fb0f",
            ),
        )
        for record_type, payload, expected in cases:
            with self.subTest(record_type=record_type, payload=payload):
                self.assertEqual(task2_call("memory_record_key", record_type, payload), expected)
        for record_type, payload in (
            ("brief", {}),
            ("state", {}),
            ("suggestion", {"action": "brief-add"}),
            ("story-link", {"endpoints": ["only-one"]}),
            ("unknown", {"id": "x"}),
        ):
            with self.subTest(record_type=record_type), self.assertRaises(ValueError):
                task2_call("memory_record_key", record_type, payload)

    def test_feed_partition_always_emits_part_one_and_caps_parts_at_one_hundred(self):
        empty = task2_call("partition_feed_items", "run-a001", [])
        self.assertEqual(empty, [{
            "runKey": "run-a001",
            "batchKey": "run-a001:feed:001",
            "partIndex": 1,
            "partCount": 1,
            "items": [],
        }])
        parts = task2_call("partition_feed_items", "run-a001", reversed([feed_item(i) for i in range(201)]))
        self.assertEqual([part["batchKey"] for part in parts], [
            "run-a001:feed:001", "run-a001:feed:002", "run-a001:feed:003",
        ])
        self.assertEqual([len(part["items"]) for part in parts], [100, 100, 1])
        self.assertEqual([part["partCount"] for part in parts], [3, 3, 3])
        self.assertEqual(
            [item["sourceFingerprint"] for part in parts for item in part["items"]],
            [f"{index:064x}" for index in range(201)],
        )


class FingerprintWindowTests(unittest.TestCase):
    def test_window_retains_latest_two_thousand_with_deterministic_order(self):
        base = datetime(2026, 8, 1, tzinfo=timezone.utc)
        entries = [
            fingerprint_entry(
                index,
                (base + timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
            )
            for index in range(2001)
        ]
        window = task2_call("advance_fingerprint_window", reversed(entries), [])
        self.assertEqual(len(window), 2000)
        self.assertEqual(window[0], entries[1])
        self.assertEqual(window[-1], entries[-1])

    def test_new_items_dedupe_and_processed_row_wins_over_pending(self):
        processed = feed_item(7, status="processed")
        pending = feed_item(7, status="pending")
        previous = [fingerprint_entry(7)]
        self.assertEqual(task2_call("new_feed_items", previous, [pending, processed]), ([], 0))
        items, count = task2_call("new_feed_items", [], [pending, processed, feed_item(8)])
        self.assertEqual(count, 2)
        self.assertEqual([item["sourceFingerprint"] for item in items], [
            f"{7:064x}", f"{8:064x}",
        ])
        self.assertEqual(items[0]["status"], "processed")

    def test_window_load_unions_divergent_committed_checkpoints(self):
        x = fingerprint_entry(10, "2026-08-10T00:10:00Z")
        y = fingerprint_entry(11, "2026-08-10T00:11:00Z")
        x_payload = feed_batch_payload(
            "checkpoint-x", 1, 1, [], new_item_count=0, window=[x]
        )
        y_payload = feed_batch_payload(
            "checkpoint-y", 1, 1, [], new_item_count=0, window=[y]
        )
        x_row, _expected = feed_batch_child(
            "checkpoint-page-x", "checkpoint-parent-x", x_payload
        )
        y_row, _expected = feed_batch_child(
            "checkpoint-page-y", "checkpoint-parent-y", y_payload
        )
        result = task2_call(
            "load_or_rebuild_fingerprint_window",
            [x_row, y_row],
            [],
            fixture_ids("checkpoint-parent-x", "checkpoint-parent-y"),
            NOW,
        )
        self.assertEqual(result, {"window": [x, y], "rebuilt": False, "errors": []})

    def test_window_reconstructed_from_batches_marks_missing_checkpoint_as_rebuilt(self):
        payload = feed_batch_payload(
            "run-rebuild", 1, 1, [feed_item(12)],
            window=[fingerprint_entry(11), fingerprint_entry(12)]
        )
        row, _ = feed_batch_child("batch-rebuild", "parent-rebuild", payload)
        result = task2_call(
            "load_or_rebuild_fingerprint_window", [], [row], fixture_ids("parent-rebuild"), NOW
        )
        self.assertEqual(
            [entry["sourceFingerprint"] for entry in result["window"]],
            [f"{11:064x}", f"{12:064x}"],
        )
        self.assertTrue(result["rebuilt"])
        self.assertIn("fingerprint-window-rebuilt", result["errors"])

    def test_standalone_checkpoint_rejects_wrapper_and_fingerprint_corruption(self):
        valid = feed_batch_payload(
            "checkpoint", 1, 1, [], new_item_count=0,
            window=[fingerprint_entry(13, "2026-08-10T01:13:00Z")],
        )
        corruptions = {
            "schema": {**valid, "schemaVersion": 1},
            "kind": {**valid, "kind": "other"},
            "unexpected-digest": {**valid, "payloadDigest": "0" * 64},
            "fingerprint": {
                **valid,
                "fingerprintWindow": [{
                    "sourceFingerprint": "A" * 64,
                    "publishedAt": "2026-08-10T01:13:00Z",
                }],
            },
            "timestamp": {
                **valid,
                "fingerprintWindow": [{
                    "sourceFingerprint": f"{13:064x}",
                    "publishedAt": "2026-08-10T01:13:00+00:00",
                }],
            },
        }
        for name, checkpoint in corruptions.items():
            with self.subTest(name=name):
                result = task2_call(
                    "load_or_rebuild_fingerprint_window", [checkpoint], [], set(), NOW
                )
                self.assertTrue(result["rebuilt"])
                self.assertIn("fingerprint-window-rebuilt", result["errors"])
                self.assertTrue(any("checkpoint[0]" in error for error in result["errors"]))

    def test_window_rebuild_excludes_uncommitted_incomplete_and_bad_digest_batches(self):
        valid_payload = feed_batch_payload(
            "run-good", 1, 1, [feed_item(20)],
            fetched_at="2026-08-10T01:30:00Z",
            window=[fingerprint_entry(19), fingerprint_entry(20)],
        )
        valid, _ = feed_batch_child("batch-good", "parent-good", valid_payload)
        uncommitted = {
            **valid,
            "page_id": fixture_id("batch-uncommitted"),
            "Run": [fixture_id("parent-pending")],
        }
        incomplete_payload = feed_batch_payload(
            "run-incomplete", 1, 2, [feed_item(21)],
            fetched_at="2026-08-10T01:31:00Z", new_item_count=2,
        )
        incomplete, _ = feed_batch_child(
            "batch-incomplete", "parent-incomplete", incomplete_payload
        )
        bad_payload = feed_batch_payload(
            "run-bad", 1, 1, [feed_item(22)], fetched_at="2026-08-10T01:32:00Z"
        )
        bad_digest, _ = feed_batch_child("batch-bad", "parent-bad", bad_payload)
        bad_digest["Payload Digest"] = "0" * 64
        result = task2_call(
            "load_or_rebuild_fingerprint_window",
            [{"fingerprintWindow": "not-a-list"}],
            [valid, uncommitted, incomplete, bad_digest],
            fixture_ids("parent-good", "parent-incomplete", "parent-bad"),
            NOW,
        )
        self.assertEqual(
            [entry["sourceFingerprint"] for entry in result["window"]],
            [f"{19:064x}", f"{20:064x}"],
        )
        self.assertTrue(result["rebuilt"])
        self.assertIn("fingerprint-window-rebuilt", result["errors"])
        self.assertTrue(any("incomplete" in error for error in result["errors"]))
        self.assertTrue(any("digest" in error for error in result["errors"]))

    def test_window_rebuild_does_not_keep_partial_items_from_a_malformed_complete_group(self):
        first_payload = feed_batch_payload(
            "run-parts", 1, 2, [feed_item(30)], new_item_count=2
        )
        second_payload = feed_batch_payload(
            "run-parts", 2, 2, [{}], new_item_count=2
        )
        rows = []
        for index, payload in enumerate((first_payload, second_payload), 1):
            row, _ = feed_batch_child(
                f"batch-part-{index}", "parent-parts", payload
            )
            rows.append(row)
        result = task2_call(
            "load_or_rebuild_fingerprint_window", [], rows, fixture_ids("parent-parts"), NOW
        )
        self.assertEqual(result["window"], [])
        self.assertTrue(result["rebuilt"])
        self.assertTrue(any("item identity" in error for error in result["errors"]))

    def test_cutoff_merge_includes_only_committed_batches_after_and_through_bounds(self):
        def batch(index: int, parent: str, fetched: str, status: str = "pending") -> dict:
            published = (
                datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                - timedelta(seconds=1)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            item = feed_item(index, status=status, published_at=published)
            payload = feed_batch_payload(
                f"run-{parent}", 1, 1, [item], fetched_at=fetched
            )
            row, _ = feed_batch_child(f"batch-{index}-{parent}", parent, payload)
            return row
        rows = [
            batch(1, "committed-before", "2026-08-10T00:59:59Z"),
            batch(2, "committed-in", "2026-08-10T01:00:01Z", "pending"),
            batch(2, "committed-in-2", "2026-08-10T01:30:00Z", "processed"),
            batch(3, "uncommitted", "2026-08-10T01:20:00Z"),
            batch(4, "committed-after", "2026-08-10T02:00:01Z"),
        ]
        items = task2_call(
            "merge_committed_feed_items",
            rows,
            fixture_ids("committed-before", "committed-in", "committed-in-2", "committed-after"),
            datetime(2026, 8, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 10, 2, tzinfo=timezone.utc),
        )
        self.assertEqual([item["sourceFingerprint"] for item in items], [f"{2:064x}"])
        self.assertEqual(items[0]["status"], "processed")

    def test_cutoff_merge_rejects_a_tampered_part_from_an_otherwise_complete_group(self):
        first_payload = feed_batch_payload(
            "run-committed", 1, 2, [feed_item(40)], new_item_count=2,
            window=[fingerprint_entry(40), fingerprint_entry(41)],
        )
        second_payload = feed_batch_payload(
            "run-committed", 2, 2, [feed_item(41)], new_item_count=2
        )
        first, _ = feed_batch_child("batch-40", "parent-committed", first_payload)
        second, _ = feed_batch_child("batch-41", "parent-committed", second_payload)
        self.assertEqual(
            len(task2_call(
                "merge_committed_feed_items", [first, second], fixture_ids("parent-committed"),
                datetime(2026, 8, 10, 1, tzinfo=timezone.utc), NOW,
            )),
            2,
        )
        tampered_parts = (
            {**second, "Body Format": "wrong"},
            {**second, "Payload Digest": "0" * 64},
            {**second, "body": encode_notion_body({**second_payload, "items": []})},
            {**second, "Batch Key": "run-committed:feed:999"},
        )
        for tampered in tampered_parts:
            with self.subTest(field=next(
                key for key in tampered if tampered.get(key) != second.get(key)
            )), self.assertRaises(ValueError):
                task2_call(
                    "merge_committed_feed_items", [first, tampered], fixture_ids("parent-committed"),
                    datetime(2026, 8, 10, 1, tzinfo=timezone.utc), NOW,
                )

    def test_cutoff_merge_does_not_silently_omit_a_group_moved_outside_by_property_tampering(self):
        payload = feed_batch_payload(
            "run-property-tamper", 1, 1, [feed_item(42)],
            fetched_at="2026-08-10T01:30:00Z",
        )
        row, _ = feed_batch_child(
            "batch-property-tamper", "parent-property-tamper", payload
        )
        row["Fetched At"] = "2026-08-10T00:30:00Z"
        with self.assertRaises(ValueError):
            task2_call(
                "merge_committed_feed_items", [row], fixture_ids("parent-property-tamper"),
                datetime(2026, 8, 10, 1, tzinfo=timezone.utc), NOW,
            )

    def test_complete_group_requires_identical_metadata_and_exact_unique_new_count(self):
        first_payload = feed_batch_payload(
            "run-consistent", 1, 2, [feed_item(50)], new_item_count=2
        )
        second_payload = feed_batch_payload(
            "run-consistent", 2, 2, [feed_item(51)], new_item_count=2
        )
        first, _ = feed_batch_child("batch-50", "parent-consistent", first_payload)
        changed_payload = {
            **second_payload,
            "fetchedAt": "2026-08-10T01:58:00Z",
        }
        changed, _ = feed_batch_child("batch-51", "parent-consistent", changed_payload)
        duplicate_payload = {
            **second_payload,
            "items": [feed_item(50)],
        }
        duplicate, _ = feed_batch_child("batch-52", "parent-consistent", duplicate_payload)
        for second in (changed, duplicate):
            with self.subTest(page_id=second["page_id"]), self.assertRaises(ValueError):
                task2_call(
                    "merge_committed_feed_items", [first, second], fixture_ids("parent-consistent"),
                    datetime(2026, 8, 10, 1, tzinfo=timezone.utc), NOW,
                )

    def test_batch_group_rejects_part_count_above_physical_key_limit_before_grouping(self):
        payload = feed_batch_payload(
            "run-too-many", 1, 1000, [feed_item(60)], new_item_count=1000
        )
        row, _ = feed_batch_child("batch-too-many", "parent-too-many", payload)
        result = task2_call(
            "load_or_rebuild_fingerprint_window", [], [row], fixture_ids("parent-too-many"), NOW
        )
        self.assertTrue(any("1 through 999" in error for error in result["errors"]))


class MemoryRevisionTests(unittest.TestCase):
    def memory_row(self, page_id: str, record: str, revision: int, parent: str,
                   supersedes: list[str]) -> dict:
        return {
            "page_id": fixture_id(page_id),
            "Record Key": record,
            "Revision": revision,
            "Revision Key": f"{record}:r{revision:06d}:{parent}",
            "Run": [fixture_id(parent)],
            "Supersedes": [fixture_id(value) for value in supersedes],
        }

    def test_failed_attempt_successor_does_not_hide_prior_committed_revision(self):
        first = self.memory_row("memory-1", "record-a", 1, "run-committed", [])
        failed_successor = self.memory_row("memory-failed", "record-a", 2, "run-failed", ["memory-1"])
        current, errors = task2_call(
            "select_current_memory", [first, failed_successor], fixture_ids("run-committed")
        )
        self.assertEqual(current, [first])
        self.assertEqual(errors, [])
        self.assertNotEqual(failed_successor["Revision Key"], self.memory_row(
            "memory-retry", "record-a", 2, "run-a002", ["memory-1"]
        )["Revision Key"])

    def test_unique_max_committed_revision_wins(self):
        first = self.memory_row("memory-1", "record-a", 1, "run-1", [])
        second = self.memory_row("memory-2", "record-a", 2, "run-2", ["memory-1"])
        current, errors = task2_call("select_current_memory", [second, first], fixture_ids("run-1", "run-2"))
        self.assertEqual(current, [second])
        self.assertEqual(errors, [])

    def test_duplicate_gap_wrong_predecessor_and_cycle_are_conflicts(self):
        first = self.memory_row("memory-1", "record-a", 1, "run-1", [])
        cases = {
            "duplicate": [first, self.memory_row("memory-dupe", "record-a", 1, "run-2", [])],
            "gap": [first, self.memory_row("memory-3", "record-a", 3, "run-2", ["memory-1"])],
            "wrong-predecessor": [
                first,
                self.memory_row("memory-b", "record-b", 1, "run-2", []),
                self.memory_row("memory-2", "record-a", 2, "run-3", ["memory-b"]),
            ],
            "cycle": [
                {**first, "Supersedes": [fixture_id("memory-2")]},
                self.memory_row("memory-2", "record-a", 2, "run-2", ["memory-1"]),
            ],
        }
        for name, rows in cases.items():
            with self.subTest(name=name):
                current, errors = task2_call(
                    "select_current_memory", rows, {row["Run"][0] for row in rows}
                )
                self.assertTrue(errors)
                self.assertNotIn("record-a", [row["Record Key"] for row in current])

    def test_revision_above_six_digit_physical_limit_is_rejected_before_graph_walk(self):
        oversized = self.memory_row(
            "memory-large", "record-a", 1_000_000, "run-1", []
        )
        current, errors = task2_call("select_current_memory", [oversized], fixture_ids("run-1"))
        self.assertEqual(current, [])
        self.assertTrue(any("1 through 999999" in error for error in errors))


class ChildReadBackAndPrecommitTests(unittest.TestCase):
    def test_feed_child_detects_body_relation_digest_and_part_tampering(self):
        payload = feed_batch_payload(
            STRICT_RUN_KEY, 1, 1, [feed_item(1)], window=[fingerprint_entry(1)]
        )
        page, expected = feed_batch_child("batch-1", "parent-1", payload)
        parent = validation_parent("parent-1")
        self.assertEqual(task2_call(
            "validate_child_page", "feed", page, expected, parent,
            operational_installation(),
        ), [])
        mutations = {
            "Body Format": {**page, "Body Format": "wrong"},
            "Run": {**page, "Run": ["other-parent"]},
            "Run Key": {**page, "Run Key": "run-other"},
            "Part Index": {**page, "Part Index": 2},
            "Part Count": {**page, "Part Count": 2},
            "Item Count": {**page, "Item Count": 0},
            "Payload Digest": {**page, "Payload Digest": "0" * 64},
            "Fingerprint Window Digest": {**page, "Fingerprint Window Digest": "0" * 64},
            "body": {**page, "body": encode_notion_body({**payload, "items": []})},
        }
        for field, tampered in mutations.items():
            with self.subTest(field=field):
                self.assertTrue(
                    task2_call(
                        "validate_child_page", "feed", tampered, expected, parent,
                        operational_installation(),
                    )
                )

    def test_feed_part_after_part_one_does_not_require_a_checkpoint_window(self):
        payload = feed_batch_payload(
            STRICT_RUN_KEY, 2, 2, [feed_item(2)], new_item_count=2
        )
        page, expected = feed_batch_child("batch-2", "parent-1", payload)
        self.assertEqual(
            task2_call(
                "validate_child_page", "feed", page, expected,
                validation_parent("parent-1"), operational_installation(),
            ), []
        )

    def test_feed_child_rejects_boolean_and_out_of_range_part_metadata(self):
        valid_payload = feed_batch_payload(STRICT_RUN_KEY, 1, 1, [feed_item(3)])
        page, expected = feed_batch_child("batch-metadata", "parent-1", valid_payload)
        parent = validation_parent("parent-1")
        for field in ("Part Index", "Part Count", "Item Count"):
            with self.subTest(field=field):
                self.assertTrue(task2_call(
                    "validate_child_page", "feed", {**page, field: True}, expected,
                    parent, operational_installation(),
                ))

        malformed_payloads = (
            feed_batch_payload("run-large-count", 1, 1000, [feed_item(4)], new_item_count=1),
            feed_batch_payload("run-index-after-count", 2, 1, [feed_item(5)], new_item_count=1),
            feed_batch_payload("run-large-part", 1, 1, [feed_item(i) for i in range(101)], new_item_count=101),
        )
        for payload in malformed_payloads:
            malformed_page, malformed_expected = feed_batch_child(
                f"batch-malformed-{payload['runKey']}", "parent-1", payload
            )
            with self.subTest(run=payload["runKey"]):
                self.assertTrue(task2_call(
                    "validate_child_page", "feed", malformed_page,
                    malformed_expected, parent, operational_installation(),
                ))

    def test_feed_child_requires_exact_v2_wrapper_outcomes_and_full_item_rows(self):
        valid = feed_batch_payload("run-wrapper", 1, 1, [feed_item(6)])
        reversed_outcomes = list(reversed(source_outcomes()))
        invalid_error_outcomes = source_outcomes()
        invalid_error_outcomes[0] = {
            "feedId": "financial_juice", "status": "error", "itemCount": 1,
            "cursor": "a" * 64, "error": "",
        }
        corruptions = (
            {**valid, "schemaVersion": 1},
            {**valid, "kind": "other"},
            {**valid, "sourceOutcomes": reversed_outcomes},
            {**valid, "sourceOutcomes": invalid_error_outcomes},
            {**valid, "items": [{"sourceFingerprint": f"{6:064x}", "publishedAt": "2026-08-10T01:06:00Z"}]},
        )
        for index, payload in enumerate(corruptions):
            page, expected = feed_batch_child(f"batch-wrapper-{index}", "parent-1", payload)
            with self.subTest(index=index):
                self.assertTrue(task2_call(
                    "validate_child_page", "feed", page, expected,
                    validation_parent("parent-1"), operational_installation(),
                ))

    def test_report_child_validates_payload_and_korean_rendering_separately(self):
        payload = valid_report_payload()
        page, expected = child_page(
            "report", "report-1", "parent-1",
            {
                "Report Key": f"{STRICT_RUN_KEY}:report:hourly", "Run Key": STRICT_RUN_KEY,
                "Integration Key": "", "Report Type": "hourly-briefing",
            }, payload, "한국어 보고서",
        )
        self.assertEqual(
            task2_call(
                "validate_child_page", "report", page, expected,
                validation_parent("parent-1", material_change=True),
                operational_installation(),
            ), []
        )
        legacy_page = {
            **page,
            "Body Format": "wm-body-v1",
            "body": legacy_notion_body(payload, "한국어 보고서"),
        }
        legacy_expected = {
            **expected,
            "Body Format": "wm-body-v1",
            "body": legacy_page["body"],
        }
        self.assertEqual(
            task2_call(
                "validate_child_page", "report", legacy_page, legacy_expected,
                validation_parent("parent-1", material_change=True),
                operational_installation(),
            ), []
        )
        mislabeled_page = {**page, "Body Format": "wm-body-v1"}
        mislabeled_expected = {**expected, "Body Format": "wm-body-v1"}
        self.assertTrue(
            task2_call(
                "validate_child_page", "report", mislabeled_page,
                mislabeled_expected,
                validation_parent("parent-1", material_change=True),
                operational_installation(),
            )
        )
        tampered_rendering = {**page, "body": encode_notion_body(payload, "변조된 보고서")}
        self.assertTrue(
            task2_call(
                "validate_child_page", "report", tampered_rendering, expected,
                validation_parent("parent-1", material_change=True),
                operational_installation(),
            )
        )
        self.assertTrue(task2_call(
            "validate_child_page", "report", {**page, "Rendering Digest": "0" * 64},
            expected, validation_parent("parent-1", material_change=True),
            operational_installation(),
        ))
        malformed_payload = {
            **payload,
            "scenarios": {
                **payload["scenarios"],
                "낙관": {**payload["scenarios"]["낙관"], "transmission": ""},
            },
        }
        malformed_page, malformed_expected = child_page(
            "report", "report-malformed", "parent-1",
            {
                "Report Key": f"{STRICT_RUN_KEY}:report:hourly", "Run Key": STRICT_RUN_KEY,
                "Integration Key": "", "Report Type": "hourly-briefing",
            }, malformed_payload, "한국어 보고서",
        )
        self.assertTrue(task2_call(
            "validate_child_page", "report", malformed_page, malformed_expected,
            validation_parent("parent-1", material_change=True),
            operational_installation(),
        ))

    def test_memory_child_validates_revision_physical_key_and_predecessor(self):
        payload = valid_memory_payload()
        record = storage.memory_record_key("state", payload)
        page, expected = child_page(
            "memory", "memory-2", "parent-2",
            {
                "Record Key": record,
                "Revision Key": storage.revision_key(record, 2, STRICT_RUN_KEY),
                "Run Key": STRICT_RUN_KEY, "Revision": 2, "Supersedes": ["memory-1"],
            }, payload,
        )
        self.assertEqual(
            task2_call(
                "validate_child_page", "memory", page, expected,
                validation_parent("parent-2"), operational_installation(),
            ), []
        )
        for field, value in (
            ("Revision Key", storage.revision_key(record, 3, STRICT_RUN_KEY)),
            ("Supersedes", []),
            ("Revision", 3),
        ):
            with self.subTest(field=field):
                self.assertTrue(task2_call(
                    "validate_child_page", "memory", {**page, field: value}, expected,
                    validation_parent("parent-2"), operational_installation(),
                ))

    def test_child_set_requires_exact_unique_keys_pages_and_parent(self):
        row = {
            "page_id": fixture_id("batch-1"), "Batch Key": "run:feed:001",
            "Run": [fixture_id("parent-1")],
        }
        self.assertEqual(
            task2_call(
                "verify_child_set", {"run:feed:001"}, [row], fixture_id("parent-1")
            ), []
        )
        self.assertTrue(task2_call(
            "verify_child_set", {"run:feed:001"},
            [row, {**row, "page_id": fixture_id("batch-2")}],
            fixture_id("parent-1")
        ))
        self.assertTrue(task2_call(
            "verify_child_set", {"run:feed:001"},
            [{**row, "Run": [fixture_id("other")]}], fixture_id("parent-1")
        ))

    def test_precommit_snapshot_blocks_slot_run_and_child_races(self):
        current = prepared_run()
        payload = feed_batch_payload(
            current["Run Key"], 1, 1, [], new_item_count=0
        )
        child, child_expected = feed_batch_child(
            "batch-1", "run-current", payload
        )
        _ = child_expected
        kwargs = strict_precommit_context(current, child)
        self.assertEqual(task2_call("verify_precommit_snapshot", **kwargs), [])
        races = (
            {"slot_rows": [kwargs["slot_rows"][0], notion_run(2, "preparing", page_id="run-race")]},
            {"slot_rows": [{**kwargs["slot_rows"][0], "Status": "failed"}]},
            {"exact_run_rows": [kwargs["exact_run_rows"][0], {**kwargs["exact_run_rows"][0], "page_id": fixture_id("run-duplicate")}]},
            {"exact_run_rows": [{**kwargs["exact_run_rows"][0], "Status": "failed"}]},
            {"exact_run_rows": [{**kwargs["exact_run_rows"][0], "Run Key": "changed-after-validation"}]},
            {"exact_run_rows": [{**kwargs["exact_run_rows"][0], "Trigger": "manual"}]},
            {"child_rows_by_kind": {**kwargs["child_rows_by_kind"], "feed": [child, {**child, "page_id": fixture_id("batch-race")}]}},
        )
        for race in races:
            with self.subTest(race=next(iter(race))):
                self.assertTrue(task2_call("verify_precommit_snapshot", **{**kwargs, **race}))

    def test_precommit_revalidates_fresh_feed_and_report_pages_against_original_snapshots(self):
        current = prepared_run()
        feed_payload = feed_batch_payload(
            current["Run Key"], 1, 1, [feed_item(70)]
        )
        feed, feed_expected = feed_batch_child(
            "batch-current", "run-current", feed_payload
        )
        report_payload = valid_report_payload()
        report, report_expected = child_page(
            "report", "report-current", "run-current",
            {
                "Report Key": f"{current['Run Key']}:report:hourly",
                "Run Key": current["Run Key"], "Integration Key": "",
                "Report Type": "hourly-briefing",
            }, report_payload, "한국어 보고서",
        )
        _ = feed_expected, report_expected
        base = strict_precommit_context(current, feed, report)
        self.assertEqual(task2_call("verify_precommit_snapshot", **base), [])
        mutations = (
            {**base["child_rows_by_kind"], "feed": [{**feed, "Payload Digest": "tampered"}], "report": [report]},
            {**base["child_rows_by_kind"], "feed": [{**feed, "body": "tampered"}], "report": [report]},
            {**base["child_rows_by_kind"], "feed": [feed], "report": [{**report, "body": "tampered"}]},
            {**base["child_rows_by_kind"], "feed": [feed], "report": [{**report, "Payload Digest": "tampered"}]},
            {**base["child_rows_by_kind"], "feed": [feed], "report": [{**report, "Rendering Digest": "tampered"}]},
            {**base["child_rows_by_kind"], "feed": [feed], "report": [{**report, "Run Key": "run-mutated"}]},
            {**base["child_rows_by_kind"], "feed": [feed], "report": [{**report, "Report Type": "six-hour"}]},
        )
        for child_rows in mutations:
            with self.subTest(child_rows=child_rows):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot", **{**base, "child_rows_by_kind": child_rows}
                ))
        self.assertTrue(task2_call(
            "verify_precommit_snapshot",
            **{**base, "expected_child_pages_by_kind": {"feed": {}, "memory": {}, "report": {}}},
        ))

    def test_precommit_rejects_cross_part_feed_metadata_disagreement(self):
        current = prepared_run()
        first_payload = feed_batch_payload(
            current["Run Key"], 1, 2, [feed_item(71)], new_item_count=2,
            fetched_at="2026-08-10T01:58:00Z",
        )
        second_payload = feed_batch_payload(
            current["Run Key"], 2, 2, [feed_item(72)], new_item_count=2,
            fetched_at="2026-08-10T01:59:00Z",
        )
        first, first_expected = feed_batch_child("batch-1", "run-current", first_payload)
        second, second_expected = feed_batch_child("batch-2", "run-current", second_payload)
        _ = first_expected, second_expected
        errors = task2_call(
            "verify_precommit_snapshot",
            **strict_precommit_context(current, first, second),
        )
        self.assertTrue(errors)

    def test_precommit_revalidates_canonical_run_and_integration_identity(self):
        canonical = prepared_run()
        base = strict_precommit_context(canonical)
        canonical = base["expected_run_snapshot"]
        wrong_run_key = {
            **canonical, "Attempt": 2,
            "Run Key": canonical["Run Key"],
        }
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "slot_rows": [wrong_run_key],
                "exact_run_rows": [wrong_run_key],
            },
        ))

        invalid_integration = {
            **canonical, "Integration Key": "not-an-integration-key",
        }
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "slot_rows": [invalid_integration],
                "exact_run_rows": [invalid_integration],
                "integration_rows": [invalid_integration],
                "expected_run_snapshot": invalid_integration,
            },
        ))
        valid_base = strict_precommit_context(
            prepared_run(integration_key="wmi_b12ee94ad696_genesis")
        )
        valid_integration = valid_base["expected_run_snapshot"]
        for changed in (
            {**valid_integration, "Status": "committed"},
            {**valid_integration, "Run Key": "changed-run-key"},
        ):
            with self.subTest(changed=changed):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot", **{
                        **valid_base, "integration_rows": [changed],
                    },
                ))

    def test_precommit_compares_every_fresh_run_observation_to_the_original_snapshot(self):
        current = prepared_run(integration_key="wmi_b12ee94ad696_genesis")
        base = strict_precommit_context(current)
        current = base["expected_run_snapshot"]
        self.assertEqual(task2_call("verify_precommit_snapshot", **base), [])
        for field, value in (
            ("Collection Cutoff", "2099-01-01T00:00:00Z"),
            ("Output Digest", "3" * 64),
            ("body", "mutated prepared Run body"),
            ("Notification Plan", "hourly-briefing"),
        ):
            changed = {**current, field: value}
            with self.subTest(field=field):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot", **{
                        **base,
                        "slot_rows": [changed],
                        "exact_run_rows": [changed],
                        "integration_rows": [changed],
                    },
                ))

    def test_precommit_requires_and_compares_full_notion_run_snapshot_fields(self):
        current = prepared_run(integration_key="wmi_b12ee94ad696_genesis")
        base = strict_precommit_context(current)
        current = base["expected_run_snapshot"]
        self.assertEqual(task2_call("verify_precommit_snapshot", **base), [])

        for field in ("Name", "Created At", "Updated At"):
            incomplete = {**current}
            incomplete.pop(field)
            with self.subTest(case="missing-expected", field=field):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot",
                    **{**base, "expected_run_snapshot": incomplete},
                ))

        invalid_expected_values = (
            ("Name", ""),
            ("Created At", ""),
            ("Created At", 0),
            ("Updated At", ""),
            ("Updated At", None),
        )
        for field, value in invalid_expected_values:
            with self.subTest(case="invalid-expected", field=field, value=value):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot",
                    **{**base, "expected_run_snapshot": {**current, field: value}},
                ))

        tampered_values = {
            "Name": "tampered-run-title",
            "Created At": "2026-08-10T01:51:00Z",
            "Updated At": "2026-08-10T02:00:02Z",
        }
        for field, value in tampered_values.items():
            changed = {**current, field: value}
            for observation in ("slot_rows", "exact_run_rows", "integration_rows"):
                with self.subTest(case="fresh-tamper", field=field, observation=observation):
                    self.assertTrue(task2_call(
                        "verify_precommit_snapshot",
                        **{**base, observation: [changed]},
                    ))

    def test_precommit_requires_nonempty_second_precision_utc_gate_timestamps(self):
        current = prepared_run()
        base = strict_precommit_context(current)
        current = base["expected_run_snapshot"]
        self.assertEqual(task2_call("verify_precommit_snapshot", **base), [])
        for field in ("Started At", "Scheduled Slot", "Collection Cutoff"):
            for invalid_value in (
                "",
                "2026-08-10T01:00:00+00:00",
                "2026-08-10T01:00:00.000Z",
            ):
                invalid = {**current, field: invalid_value}
                with self.subTest(field=field, value=invalid_value):
                    self.assertTrue(task2_call(
                        "verify_precommit_snapshot", **{
                            **base,
                            "slot_rows": [invalid],
                            "exact_run_rows": [invalid],
                            "expected_run_snapshot": invalid,
                        },
                    ))

        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{**base, "expected_run_snapshot": None}
        ))
        incomplete_expected = {**current}
        incomplete_expected.pop("Output Digest")
        self.assertTrue(task2_call(
            "verify_precommit_snapshot",
            **{**base, "expected_run_snapshot": incomplete_expected},
        ))
        incomplete_fresh = {**current}
        incomplete_fresh.pop("body")
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base,
                "slot_rows": [incomplete_fresh],
                "exact_run_rows": [incomplete_fresh],
                "integration_rows": [incomplete_fresh],
            },
        ))

        invalid_same_observations = (
            {**current, "Feed Success Count": True},
            {**current, "Output Prepared": False},
            {**current, "Material Change": 0},
            {**current, "Started At": "not-a-timestamp"},
            {**current, "body": ""},
        )
        for invalid in invalid_same_observations:
            changed_field = next(
                field for field in invalid
                if type(invalid[field]) is not type(current[field])
                or invalid[field] != current[field]
            )
            with self.subTest(invalid=changed_field):
                self.assertTrue(task2_call(
                    "verify_precommit_snapshot", **{
                        **base,
                        "slot_rows": [invalid],
                        "exact_run_rows": [invalid],
                        "integration_rows": [invalid],
                        "expected_run_snapshot": invalid,
                    },
                ))

    def test_precommit_memory_logical_revision_comparison_is_type_sensitive(self):
        current = prepared_run()
        memory_payload = valid_memory_payload()
        record = storage.memory_record_key("state", memory_payload)
        memory, memory_expected = child_page(
            "memory", "memory-current", "run-current",
            {
                "Record Key": record,
                "Revision Key": storage.revision_key(record, 1, current["Run Key"]),
                "Run Key": current["Run Key"], "Revision": 1, "Supersedes": [],
            }, memory_payload,
        )
        _ = memory_expected
        boolean_revision = {**memory, "Revision": True}
        base = strict_precommit_context(current, memory)
        errors = task2_call(
            "verify_precommit_snapshot",
            **{**base, "memory_logical_rows": [boolean_revision]},
        )
        self.assertTrue(errors)

    def test_precommit_blocks_active_logical_memory_report_and_integration_duplicates(self):
        current = prepared_run()
        base = strict_precommit_context(current)
        base["parent_status_by_id"].update({
            fixture_id("run-other"): "preparing",
            fixture_id("run-failed"): "failed",
        })
        memory_other = {
            "page_id": fixture_id("memory-other"), "Record Key": "record-a",
            "Revision": 2, "Run": [fixture_id("run-other")],
        }
        report_other = {
            "page_id": fixture_id("report-other"),
            "Integration Key": "wmi_b12ee94ad696_genesis",
            "Run": [fixture_id("run-other")],
        }
        integration_other = {
            "page_id": fixture_id("run-other"),
            "Integration Key": "wmi_b12ee94ad696_genesis", "Status": "preparing"
        }
        for extra in (
            {"memory_logical_rows": [memory_other]},
            {"report_logical_rows": [report_other]},
            {"integration_rows": [integration_other]},
        ):
            with self.subTest(extra=next(iter(extra))):
                self.assertTrue(task2_call("verify_precommit_snapshot", **{**base, **extra}))
        ignored = {
            **memory_other, "page_id": fixture_id("memory-failed"),
            "Run": [fixture_id("run-failed")]
        }
        self.assertEqual(task2_call(
            "verify_precommit_snapshot", **{**base, "memory_logical_rows": [ignored]}
        ), [])

    def test_precommit_integration_query_requires_the_current_run_and_blocks_overlap(self):
        integration = "wmi_b12ee94ad696_genesis"
        current = prepared_run(integration_key=integration)
        base = strict_precommit_context(current)
        current = base["expected_run_snapshot"]
        base["parent_status_by_id"][fixture_id("run-force")] = "preparing"
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{**base, "integration_rows": []}
        ))
        self.assertEqual(
            task2_call(
                "verify_precommit_snapshot",
                **{**base, "integration_rows": [base["exact_run_rows"][0]]},
            ), []
        )
        force = {
            "page_id": fixture_id("run-force"), "Integration Key": integration,
            "Status": "preparing"
        }
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "integration_rows": [current, force],
            }
        ))

    def test_precommit_logical_queries_must_read_back_current_memory_and_six_hour_report(self):
        integration = "wmi_b12ee94ad696_genesis"
        current = prepared_run(integration_key=integration)
        memory_payload = valid_memory_payload()
        record = storage.memory_record_key("state", memory_payload)
        memory, memory_expected = child_page(
            "memory", "memory-current", "run-current",
            {
                "Record Key": record,
                "Revision Key": storage.revision_key(record, 1, current["Run Key"]),
                "Run Key": current["Run Key"], "Revision": 1,
                "Supersedes": [],
            }, memory_payload,
        )
        report_payload = valid_report_payload()
        report, report_expected = child_page(
            "report", "report-current", "run-current",
            {
                "Report Key": f"{integration}:report:six-hour:{current['Run Key']}",
                "Run Key": current["Run Key"], "Integration Key": integration,
                "Report Type": "six-hour",
            }, report_payload, "한국어 보고서",
        )
        _ = memory_expected, report_expected
        base = strict_precommit_context(current, memory, report)
        base["parent_status_by_id"][fixture_id("run-failed")] = "failed"
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "memory_logical_rows": [], "report_logical_rows": [],
            }
        ))
        failed_report = {
            **report, "page_id": fixture_id("report-failed"),
            "Run": [fixture_id("run-failed")],
            "Report Key": f"{integration}:report:six-hour:{current['Run Key']}-failed",
        }
        self.assertEqual(task2_call(
            "verify_precommit_snapshot", **{
                **base, "memory_logical_rows": [memory],
                "report_logical_rows": [report, failed_report],
            }
        ), [])
        contradictory_memory = {**memory, "Record Key": "record-b"}
        contradictory_report = {
            **report, "Integration Key": "wmi_b12ee94ad696_previous-cutoff-20260810T010000Z"
        }
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "memory_logical_rows": [contradictory_memory],
                "report_logical_rows": [report],
            }
        ))
        self.assertTrue(task2_call(
            "verify_precommit_snapshot", **{
                **base, "memory_logical_rows": [memory],
                "report_logical_rows": [contradictory_report],
            }
        ))


if __name__ == "__main__":
    unittest.main()
