"""Deterministic pure storage contracts for the World Memory Notion ledger."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Iterable
from urllib.parse import urlsplit
from uuid import UUID

from .contracts import (
    CONFIGURED_SOURCES,
    installation_key,
    validate_audit,
    validate_feed_row,
    validate_report,
)
from .feed import merge_buffer
from .scheduler import utc_iso, validate_operational_installation


BODY_FORMAT = "wm-body-v2"
LEGACY_BODY_FORMAT = "wm-body-v1"
READABLE_BODY_FORMATS = frozenset({LEGACY_BODY_FORMAT, BODY_FORMAT})
_BODY_MARKER = "## Canonical Payload\n```text\n"
_RENDERING_MARKER = "\n\n## Korean Rendering\n"
_TRIGGERS = {"scheduled", "manual", "force-world-memory"}
_NOTION_UTC = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
)
_DATABASE_KEYS = frozenset({"installations", "runs", "feed_batches", "memory", "reports"})
_INSTALLATION_CACHE_DATE_PROPERTIES = (
    "Last Feed Attempt",
    "Last Feed Success",
    "Last World Memory Success",
    "Last Report Success",
    "Next World Memory At",
    "Last Briefing At",
)


BASE_SCHEMAS = {
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


def _parse_uuid(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{description} must be a UUID string")
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{description} must be a UUID string") from exc
    return value


def slot_key(installation_key: str, trigger: str, started_at: datetime) -> str:
    """Return a trigger- and instant-specific logical slot key."""
    if not isinstance(installation_key, str) or not installation_key:
        raise ValueError("installation_key must be a non-empty string")
    if not isinstance(trigger, str) or trigger not in _TRIGGERS:
        raise ValueError("trigger must be scheduled, manual, or force-world-memory")
    if not isinstance(started_at, datetime) or started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware")
    utc_started_at = started_at.astimezone(timezone.utc)
    if trigger == "scheduled":
        utc_started_at = utc_started_at.replace(minute=0, second=0, microsecond=0)
    else:
        utc_started_at = utc_started_at.replace(second=0, microsecond=0)
    instant = utc_started_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = hashlib.sha256(installation_key.encode("utf-8")).hexdigest()[:12]
    return f"wms_{prefix}_{trigger}_{instant}"


def run_key(slot_key: str, attempt: int) -> str:
    """Return the physical Run key for attempt 1 through 999 of a slot."""
    if not isinstance(slot_key, str) or not slot_key:
        raise ValueError("slot_key must be a non-empty string")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 999:
        raise ValueError("attempt must be an integer from 1 through 999")
    return f"{slot_key}_a{attempt:03d}"


def _validate_json_shape(value: object, active: set[int] | None = None) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("JSON strings and object keys must be valid UTF-8") from exc
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if active is None:
        active = set()
    if isinstance(value, (list, dict)):
        identity = id(value)
        if identity in active:
            raise ValueError("JSON value must not contain a circular reference")
        active.add(identity)
        try:
            if isinstance(value, list):
                for item in value:
                    _validate_json_shape(item, active)
                return
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("JSON object keys must be strings")
                try:
                    key.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError(
                        "JSON strings and object keys must be valid UTF-8"
                    ) from exc
                _validate_json_shape(item, active)
            return
        finally:
            active.remove(identity)
    raise TypeError("value must contain only JSON objects, arrays, and scalar values")


def canonical_json_bytes(value: object) -> bytes:
    """Encode one JSON value with the World Memory canonical byte contract."""
    try:
        _validate_json_shape(value)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc
    except UnicodeEncodeError as exc:
        raise ValueError("JSON strings and object keys must be valid UTF-8") from exc


def canonical_digest(value: object) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def installation_cache_properties(installation: object) -> dict[str, str | int | None]:
    """Serialize one normalized Installation cache for a Notion property update."""
    validated = validate_operational_installation(installation)
    properties: dict[str, str | int | None] = {
        "Feed Cursor State": canonical_json_bytes(
            validated["Feed Cursor State"]
        ).decode("utf-8"),
        "Last Error": validated["Last Error"],
    }
    for field in _INSTALLATION_CACHE_DATE_PROPERTIES:
        value = validated[field]
        properties[f"date:{field}:start"] = value or None
        if value:
            properties[f"date:{field}:is_datetime"] = 1
    return properties


def encode_notion_body(payload: object, rendering: str = "") -> str:
    """Encode rendering plus an exact, self-verifying canonical payload fence."""
    if not isinstance(rendering, str):
        raise TypeError("rendering must be a string")
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    canonical_json = raw.decode("utf-8")
    body = (
        f"{_BODY_MARKER}{BODY_FORMAT}\nsha256:{digest}\n"
        f"{canonical_json}\n```"
    )
    if rendering:
        body += f"{_RENDERING_MARKER}{rendering}"
    return body


def _decode_notion_body_with_format(body: str) -> tuple[object, str, str]:
    """Decode and verify one readable Notion body, returning its format."""
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    if not body.startswith(_BODY_MARKER):
        raise ValueError("body must start with the canonical payload marker")
    canonical_section = body[len(_BODY_MARKER):]
    if _RENDERING_MARKER in canonical_section:
        canonical_section, rendering = canonical_section.split(_RENDERING_MARKER, 1)
        if not rendering:
            raise ValueError("Korean rendering section must not be empty")
    else:
        rendering = ""
    body_format = canonical_section.split("\n", 1)[0]
    if body_format == BODY_FORMAT:
        match = re.fullmatch(
            rf"{re.escape(BODY_FORMAT)}\nsha256:([0-9a-f]{{64}})\n([^\n]+)\n```",
            canonical_section,
        )
    elif body_format == LEGACY_BODY_FORMAT:
        match = re.fullmatch(
            rf"{re.escape(LEGACY_BODY_FORMAT)}\nsha256:([0-9a-f]{{64}})\n"
            r"([A-Za-z0-9+/=\n]+)\n```",
            canonical_section,
        )
    else:
        match = None
    if match is None:
        raise ValueError("canonical payload fence is malformed")
    digest, stored_payload = match.groups()
    if body_format == LEGACY_BODY_FORMAT:
        lines = stored_payload.splitlines()
        if (
            not lines
            or any(not line for line in lines)
            or any(len(line) != 76 for line in lines[:-1])
            or len(lines[-1]) > 76
        ):
            raise ValueError("canonical payload base64 wrapping is malformed")
        try:
            raw = base64.b64decode("".join(lines), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("canonical payload is not valid base64") from exc
    else:
        raw = stored_payload.encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("canonical payload digest mismatch")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("canonical payload is not valid UTF-8 JSON") from exc
    try:
        canonical = canonical_json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("canonical payload contains an unsupported JSON value") from exc
    if canonical != raw:
        raise ValueError("canonical payload bytes are not canonical JSON")
    if body_format == BODY_FORMAT and encode_notion_body(payload, rendering) != body:
        raise ValueError("canonical payload body is not in exact wm-body-v2 form")
    return payload, rendering, body_format


def decode_notion_body(body: str) -> tuple[object, str]:
    """Decode and strictly verify a current or legacy Notion page body."""
    payload, rendering, _body_format = _decode_notion_body_with_format(body)
    return payload, rendering


def base_database_schemas() -> dict[str, str]:
    """Return fresh exact relation-free CREATE TABLE statements."""
    return dict(BASE_SCHEMAS)


def relation_statements(ids: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Return independently retryable relation DDL after validating all source IDs."""
    if not isinstance(ids, dict) or set(ids) != _DATABASE_KEYS:
        raise ValueError("ids must contain exactly the five World Memory database keys")
    for key in sorted(_DATABASE_KEYS):
        _parse_uuid(ids[key], f"ids[{key!r}]")
    return {
        "runs": (
            f'ADD COLUMN "Installation" RELATION(\'{ids["installations"]}\', DUAL \'Runs\')',
        ),
        "feed_batches": (
            f'ADD COLUMN "Run" RELATION(\'{ids["runs"]}\', DUAL \'Feed Batches\')',
        ),
        "memory": (
            f'ADD COLUMN "Run" RELATION(\'{ids["runs"]}\', DUAL \'Memory Records\')',
            f'ADD COLUMN "Supersedes" RELATION(\'{ids["memory"]}\')',
        ),
        "reports": (
            f'ADD COLUMN "Run" RELATION(\'{ids["runs"]}\', DUAL \'Reports\')',
            f'ADD COLUMN "Evidence Records" RELATION(\'{ids["memory"]}\')',
        ),
    }


_RUN_STATUSES = frozenset({"preparing", "committed", "failed", "superseded"})
_TERMINAL_RUN_STATUSES = frozenset({"failed", "superseded"})
_PHYSICAL_KEY_FIELDS = ("Batch Key", "Revision Key", "Report Key")
_INTEGRATION_KEY = re.compile(
    r"wmi_[0-9a-f]{12}_(genesis|previous-cutoff-(\d{8}T\d{6}Z))"
)
_SLOT_KEY = re.compile(
    r"wms_([0-9a-f]{12})_(scheduled|manual|force-world-memory)_"
    r"(\d{8}T\d{6}Z)"
)
_FEED_ITEM_KEYS = frozenset({
    "schemaVersion", "id", "sourceFingerprint", "feedId", "feedTitle",
    "feedSourceUrl", "sourceUrl", "title", "sourcePublishedAt", "publishedAt",
    "publishedAtOffsetMinutes", "fetchedAt", "status", "importanceCandidate",
})
_FEED_BATCH_BASE_KEYS = frozenset({
    "schemaVersion", "kind", "runKey", "batchKey", "partIndex", "partCount",
    "fetchedAt", "newItemCount", "sourceOutcomes", "items",
})
_SOURCE_OUTCOME_KEYS = frozenset({"feedId", "status", "itemCount", "cursor", "error"})
_MEMORY_PAYLOAD_FORBIDDEN_FIELDS = frozenset({
    "runKey", "recordKey", "revisionKey", "revision", "supersedes",
    "verifiedEvidence", "payloadDigest", "bodyFormat", "pageId", "createdAt",
    "updatedAt",
})
_REPORT_PAYLOAD_FORBIDDEN_FIELDS = frozenset({
    "runKey", "reportKey", "integrationKey", "materialChange", "userVisible",
    "evidenceRecords", "coverageStart", "coverageEnd", "collectionCutoff",
    "notificationPlan",
})
_CONFIGURED_FEED_IDS = tuple(source[0] for source in CONFIGURED_SOURCES)
_RUN_SNAPSHOT_FIELDS = (
    "Name", "Slot Key", "Run Key", "Integration Key", "Attempt", "Trigger", "Status",
    "Started At", "Scheduled Slot", "Collection Cutoff", "Installation",
    "Created At", "Updated At",
)
_EXPECTED_RUN_SNAPSHOT_FIELDS = frozenset({
    "Name", "Slot Key", "Run Key", "Integration Key", "Attempt", "Trigger", "Status",
    "Installation", "Started At", "Scheduled Slot", "Collection Cutoff",
    "Finished At", "Feed Success Count", "Feed Failure Count", "New Item Count",
    "Material Change", "Integration Due", "Integration Performed",
    "Output Prepared", "Cache Reconciled", "Notification Plan", "Input Digest",
    "Output Digest", "Error Summary", "Created At", "Updated At", "body",
})
_OBSERVED_RUN_SNAPSHOT_FIELDS = _EXPECTED_RUN_SNAPSHOT_FIELDS | {"page_id"}
_RUN_TIMESTAMP_FIELDS = (
    "Started At", "Scheduled Slot", "Collection Cutoff", "Finished At",
)
_RUN_COUNT_FIELDS = (
    "Feed Success Count", "Feed Failure Count", "New Item Count",
)
_RUN_BOOLEAN_FIELDS = (
    "Material Change", "Integration Due", "Integration Performed",
    "Output Prepared", "Cache Reconciled",
)
_NOTIFICATION_PLANS = frozenset({"silent", "hourly-briefing", "six-hour", "error"})
_OPERATIONAL_CHILD_FIELDS = {
    "feed": frozenset({
        "page_id", "Name", "Batch Key", "Run Key", "Payload Digest",
        "Fingerprint Window Digest", "Body Format", "Part Index", "Part Count",
        "Feed Success Count", "Feed Failure Count", "New Item Count", "Item Count",
        "Fetched At", "All Sources Failed", "Created At", "Run", "body", "payload",
    }),
    "memory": frozenset({
        "page_id", "Name", "Record Key", "Revision Key", "Run Key", "Dedupe Key",
        "Continuity ID", "Target", "Payload Digest", "Body Format", "Record Type",
        "Record Status", "Importance", "Category", "Region", "Action", "Revision",
        "Confidence", "Effective At", "Verified Evidence", "Created At", "Updated At",
        "Run", "Supersedes", "body", "payload",
    }),
    "report": frozenset({
        "page_id", "Name", "Report Key", "Run Key", "Integration Key", "Payload Digest",
        "Rendering Digest", "Body Format", "Report Type", "As Of", "Coverage Start",
        "Coverage End", "Stance", "Confidence", "Data Gap Count", "Material Change",
        "User Visible", "Created At", "Run", "Evidence Records", "body", "payload",
        "rendering",
    }),
}
def _require_nonempty_string(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be a non-empty string")
    return value


def _aware_datetime(value: object, description: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise ValueError(f"{description} must be a UTC timestamp or timezone-aware datetime") from exc
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{description} must be a UTC timestamp or timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _is_canonical_utc(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return utc_iso(_aware_datetime(value, "timestamp")) == value
    except ValueError:
        return False


def _is_notion_utc(value: object) -> bool:
    if not isinstance(value, str) or _NOTION_UTC.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _is_valid_integration_key(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _INTEGRATION_KEY.fullmatch(value)
    if match is None:
        return False
    cutoff = match.group(2)
    if cutoff is None:
        return True
    try:
        parsed = datetime.strptime(cutoff, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return parsed.strftime("%Y%m%dT%H%M%SZ") == cutoff


def _single_parent_id(row: dict, *, errors: list[str] | None = None) -> str | None:
    relation = row.get("Run")
    if (
        isinstance(relation, list)
        and len(relation) == 1
        and isinstance(relation[0], str)
        and relation[0]
    ):
        try:
            return _parse_uuid(relation[0], "Run relation page ID")
        except ValueError as exc:
            if errors is not None:
                errors.append(str(exc))
                return None
            raise
    if errors is not None:
        errors.append("Run relation must contain exactly one parent page ID")
        return None
    raise ValueError("Run relation must contain exactly one parent page ID")


def resolve_exact_key(rows: Iterable[dict], key_field: str, key: str) -> dict:
    """Resolve an exact physical key query without inventing a winner."""
    _require_nonempty_string(key_field, "key_field")
    _require_nonempty_string(key, "key")
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must contain objects")
        if row.get(key_field) == key:
            matches.append(row)
    if not matches:
        return {"action": "create"}
    if len(matches) == 1:
        return {"action": "reuse", "row": matches[0]}
    return {"action": "conflict", "count": len(matches)}


def resolve_installation_rows(rows: Iterable[dict], installation_key: str) -> dict:
    """Resolve one exact Installation Key, including partial-bootstrap reentry."""
    return resolve_exact_key(rows, "Installation Key", installation_key)


def resolve_slot_runs(
    rows: Iterable[dict],
    slot_key: str,
    now: datetime,
    *,
    installation_key: str,
    installation_page_id: str,
    stale_after: timedelta = timedelta(minutes=65),
) -> dict:
    """Resolve one logical slot according to exact Run Key and status invariants."""
    _require_nonempty_string(slot_key, "slot_key")
    current_time = _aware_datetime(now, "now")
    slot_match = _SLOT_KEY.fullmatch(slot_key)
    if slot_match is None:
        raise ValueError("Slot Key must be canonical")
    installation = _require_nonempty_string(installation_key, "installation_key")
    installation_page = _parse_uuid(
        installation_page_id, "installation_page_id"
    )
    installation_prefix = hashlib.sha256(installation.encode("utf-8")).hexdigest()[:12]
    if slot_match.group(1) != installation_prefix:
        raise ValueError("Slot Key must match the Installation Key")
    slot_trigger = slot_match.group(2)
    try:
        slot_instant = datetime.strptime(slot_match.group(3), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError("Slot Key contains an invalid UTC instant") from exc
    if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
        raise ValueError("stale_after must be a positive timedelta")
    matches: list[dict] = []
    by_run_key: dict[str, list[dict]] = {}
    attempts: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must contain objects")
        if row.get("Slot Key") != slot_key:
            continue
        _parse_uuid(row.get("page_id"), "Run page_id")
        attempt = row.get("Attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 999:
            raise ValueError("Run Attempt must be an integer from 1 through 999")
        expected_run_key = run_key(slot_key, attempt)
        if row.get("Run Key") != expected_run_key:
            raise ValueError("Run Key must match Slot Key and Attempt")
        if row.get("Installation") != [installation_page]:
            raise ValueError(
                "Run Installation relation must match the validated Installation"
            )
        if not isinstance(row.get("Name"), str) or not row["Name"].strip():
            raise ValueError("Run Name must be a non-empty string")
        if row.get("Trigger") != slot_trigger:
            raise ValueError("Run Trigger must match Slot Key")
        scheduled_slot = row.get("Scheduled Slot")
        if (
            not _is_canonical_utc(scheduled_slot)
            or _aware_datetime(scheduled_slot, "Scheduled Slot") != slot_instant
        ):
            raise ValueError("Run Scheduled Slot must match Slot Key")
        raw_started_at = row.get("Started At")
        if not _is_canonical_utc(raw_started_at):
            raise ValueError("Run Started At must be canonical UTC with second precision")
        started_at = _aware_datetime(raw_started_at, "Run Started At")
        if started_at > current_time:
            raise ValueError("Run Started At cannot be in the future")
        slot_started_at = started_at.replace(
            minute=0 if slot_trigger == "scheduled" else started_at.minute,
            second=0,
            microsecond=0,
        )
        derived_slot_key = (
            f"wms_{installation_prefix}_{slot_trigger}_"
            f"{slot_started_at.strftime('%Y%m%dT%H%M%SZ')}"
        )
        if derived_slot_key != slot_key:
            raise ValueError("Run Started At must derive the observed Slot Key")
        integration_value = row.get("Integration Key")
        if not isinstance(integration_value, str):
            raise ValueError("Run Integration Key must be a string")
        if integration_value:
            if (
                not _is_valid_integration_key(integration_value)
                or not integration_value.startswith(f"wmi_{installation_prefix}_")
            ):
                raise ValueError(
                    "Run Integration Key must match the Installation Key"
                )
        status = row.get("Status")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            raise ValueError("Run Status is invalid")
        matches.append(row)
        attempts.append(attempt)
        by_run_key.setdefault(expected_run_key, []).append(row)

    duplicate_rows = [row for grouped in by_run_key.values() if len(grouped) > 1 for row in grouped]
    if duplicate_rows:
        return {
            "action": "conflict-committed",
            "reason": "duplicate-run-key",
            "rows": duplicate_rows,
        }

    committed = [row for row in matches if row["Status"] == "committed"]
    preparing = [row for row in matches if row["Status"] == "preparing"]
    if len(committed) > 1:
        return {
            "action": "conflict-committed",
            "reason": "multiple-committed",
            "rows": committed,
        }
    if committed and preparing:
        return {
            "action": "conflict-committed",
            "reason": "committed-and-preparing",
            "rows": committed + preparing,
        }
    if len(preparing) > 1:
        return {
            "action": "conflict-preparing",
            "reason": "multiple-preparing",
            "rows": preparing,
        }
    if committed:
        return {"action": "reuse-committed", "run": committed[0]}
    if preparing:
        started_at = _aware_datetime(preparing[0]["Started At"], "Run Started At")
        if current_time - started_at >= stale_after:
            return {"action": "inspect-stale-preparing", "run": preparing[0]}
        return {
            "action": "conflict-preparing",
            "reason": "fresh-preparing",
            "rows": preparing,
        }
    attempt = max(attempts, default=0) + 1
    if attempt > 999:
        raise ValueError("Run attempt space is exhausted")
    return {
        "action": "create-attempt",
        "attempt": attempt,
        "run_key": run_key(slot_key, attempt),
    }


def stale_preparing_action(
    run: dict,
    child_errors: Iterable[str],
    now: datetime,
    stale_after: timedelta = timedelta(minutes=65),
) -> str:
    """Classify a singleton preparing Run after authoritative child read-back."""
    if not isinstance(run, dict) or run.get("Status") != "preparing":
        return "conflict"
    current_time = _aware_datetime(now, "now")
    if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
        raise ValueError("stale_after must be a positive timedelta")
    raw_started_at = run.get("Started At")
    if not _is_canonical_utc(raw_started_at):
        raise ValueError("Run Started At must be canonical UTC with second precision")
    started_at = _aware_datetime(raw_started_at, "Run Started At")
    if started_at > current_time:
        raise ValueError("Run Started At cannot be in the future")
    errors = list(child_errors)
    if any(not isinstance(error, str) for error in errors):
        raise ValueError("child_errors must contain strings")
    if current_time - started_at < stale_after:
        return "conflict"
    if run.get("Output Prepared") is True and not errors:
        return "resume"
    return "terminalize-failed"


def feed_batch_key(run_key: str, part_index: int) -> str:
    """Return one attempt-scoped Feed Batch physical key."""
    _require_nonempty_string(run_key, "run_key")
    if isinstance(part_index, bool) or not isinstance(part_index, int) or not 1 <= part_index <= 999:
        raise ValueError("part_index must be an integer from 1 through 999")
    return f"{run_key}:feed:{part_index:03d}"


def integration_key(
    installation_key: str, previous_committed_cutoff: datetime | None
) -> str:
    """Return the logical integration identity from the prior committed cutoff."""
    installation = _require_nonempty_string(installation_key, "installation_key")
    prefix = hashlib.sha256(installation.encode("utf-8")).hexdigest()[:12]
    if previous_committed_cutoff is None:
        suffix = "genesis"
    else:
        cutoff = _aware_datetime(previous_committed_cutoff, "previous_committed_cutoff")
        suffix = "previous-cutoff-" + cutoff.strftime("%Y%m%dT%H%M%SZ")
    return f"wmi_{prefix}_{suffix}"


def report_key(run_key: str, report_type: str, integration_key: str = "") -> str:
    """Return an hourly or attempt-scoped six-hour Report physical key."""
    run = _require_nonempty_string(run_key, "run_key")
    if report_type == "hourly-briefing":
        if integration_key != "":
            raise ValueError("hourly-briefing requires an empty Integration Key")
        return f"{run}:report:hourly"
    if report_type == "six-hour":
        if not _is_valid_integration_key(integration_key):
            raise ValueError("six-hour requires a valid Integration Key")
        return f"{integration_key}:report:six-hour:{run}"
    raise ValueError("report_type must be hourly-briefing or six-hour")


def memory_record_key(record_type: str, payload: dict) -> str:
    """Return the logical Memory record identity from its stable type-specific field."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if record_type == "brief":
        identity = payload.get("dedupe_key")
    elif record_type == "state":
        identity = payload.get("state_key")
    elif record_type == "suggestion":
        identity = payload.get("continuityId")
        if not isinstance(identity, str) or not identity:
            action = payload.get("action")
            target = payload.get("target")
            identity = (
                f"{action}\n{target}"
                if isinstance(action, str)
                and action.strip()
                and isinstance(target, str)
                and target.strip()
                else None
            )
    elif record_type == "taxonomy":
        identity = "world-memory-taxonomy"
    elif record_type == "story-link":
        identity = payload.get("story_key")
        if not isinstance(identity, str) or not identity:
            endpoints = payload.get("endpoints")
            if (
                isinstance(endpoints, list)
                and len(endpoints) == 2
                and all(
                    isinstance(endpoint, str) and endpoint.strip()
                    for endpoint in endpoints
                )
                and endpoints[0] != endpoints[1]
            ):
                identity = "\n".join(sorted(endpoints))
            else:
                identity = None
    else:
        raise ValueError("record_type is invalid")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(f"{record_type} payload lacks its stable identity")
    digest = hashlib.sha256(f"{record_type}\n{identity}".encode("utf-8")).hexdigest()[:18]
    return f"wmrec_{record_type}_{digest}"


def revision_key(record_key: str, revision: int, run_key: str) -> str:
    """Return one attempt-scoped Memory revision physical key."""
    record = _require_nonempty_string(record_key, "record_key")
    run = _require_nonempty_string(run_key, "run_key")
    if isinstance(revision, bool) or not isinstance(revision, int) or not 1 <= revision <= 999999:
        raise ValueError("revision must be an integer from 1 through 999999")
    return f"{record}:r{revision:06d}:{run}"


def partition_feed_items(
    run_key: str, items: Iterable[dict], max_items: int = 100
) -> list[dict]:
    """Deduplicate, fingerprint-sort, and partition one Run's normalized FEED rows."""
    run = _require_nonempty_string(run_key, "run_key")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 100:
        raise ValueError("max_items must be an integer from 1 through 100")
    normalized = merge_buffer([], list(items))
    normalized.sort(key=lambda item: item["sourceFingerprint"])
    part_count = max(1, (len(normalized) + max_items - 1) // max_items)
    return [
        {
            "runKey": run,
            "batchKey": feed_batch_key(run, index),
            "partIndex": index,
            "partCount": part_count,
            "items": normalized[(index - 1) * max_items:index * max_items],
        }
        for index in range(1, part_count + 1)
    ]


def _fingerprint_entry(value: object) -> tuple[str, str, datetime]:
    if not isinstance(value, dict) or set(value) != {"sourceFingerprint", "publishedAt"}:
        raise ValueError("fingerprint entries require exactly sourceFingerprint and publishedAt")
    fingerprint = _require_nonempty_string(value.get("sourceFingerprint"), "sourceFingerprint")
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise ValueError("sourceFingerprint must be 64 lowercase hexadecimal characters")
    published_at = _require_nonempty_string(value.get("publishedAt"), "publishedAt")
    instant = _aware_datetime(published_at, "publishedAt")
    if utc_iso(instant) != published_at:
        raise ValueError("publishedAt must be canonical UTC with second precision")
    return fingerprint, published_at, instant


def advance_fingerprint_window(
    previous: Iterable[dict],
    incoming: Iterable[dict],
    limit: int = 2000,
    *,
    observed_at: datetime | None = None,
) -> list[dict]:
    """Union fingerprint entries deterministically and retain the newest bounded window."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    observation = (
        _aware_datetime(observed_at, "observed_at")
        if observed_at is not None
        else None
    )
    by_fingerprint: dict[str, tuple[str, datetime]] = {}
    for value in (*list(previous), *list(incoming)):
        fingerprint, published_at, instant = _fingerprint_entry(value)
        if observation is not None and instant > observation:
            raise ValueError("fingerprint publishedAt cannot be in the future")
        prior = by_fingerprint.get(fingerprint)
        if prior is not None and prior[0] != published_at:
            raise ValueError(
                "conflicting publishedAt values for one sourceFingerprint"
            )
        if prior is None:
            by_fingerprint[fingerprint] = (published_at, instant)
    ordered = sorted(
        by_fingerprint.items(), key=lambda entry: (entry[1][1], entry[0])
    )[-limit:]
    return [
        {"sourceFingerprint": fingerprint, "publishedAt": published_at}
        for fingerprint, (published_at, _) in ordered
    ]


def new_feed_items(
    previous_window: Iterable[dict], incoming: Iterable[dict]
) -> tuple[list[dict], int]:
    """Return incoming identities absent from the prior window with processed precedence."""
    known = {entry["sourceFingerprint"] for entry in advance_fingerprint_window([], previous_window)}
    merged = merge_buffer([], list(incoming))
    fresh = [item for item in merged if item["sourceFingerprint"] not in known]
    return fresh, len(fresh)


def _strict_int(value: object, minimum: int, maximum: int | None = None) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


def _exact_json_equal(left: object, right: object) -> bool:
    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except (TypeError, ValueError):
        return False


def _validate_feed_batch_payload(payload: object) -> list[str]:
    """Validate the exact durable Feed Batch v2 payload wrapper."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["batch payload must be an object"]
    part_index = payload.get("partIndex")
    expected_keys = set(_FEED_BATCH_BASE_KEYS)
    if _strict_int(part_index, 1, 999) and part_index == 1:
        expected_keys.add("fingerprintWindow")
    if set(payload) != expected_keys:
        errors.append("batch payload keys do not match the exact Feed Batch wrapper")
    if not _strict_int(payload.get("schemaVersion"), 2, 2):
        errors.append("batch schemaVersion must be integer 2")
    if payload.get("kind") != "feed-batch":
        errors.append("batch kind must be feed-batch")
    run_key_value = payload.get("runKey")
    if not isinstance(run_key_value, str) or not run_key_value:
        errors.append("batch runKey must be a non-empty string")
    if not _strict_int(part_index, 1, 999):
        errors.append("batch partIndex must be an integer from 1 through 999")
    part_count = payload.get("partCount")
    if not _strict_int(part_count, 1, 999):
        errors.append("batch partCount must be an integer from 1 through 999")
    elif _strict_int(part_index, 1, 999) and part_index > part_count:
        errors.append("batch partIndex must not exceed partCount")
    if (
        isinstance(run_key_value, str)
        and run_key_value
        and _strict_int(part_index, 1, 999)
    ):
        try:
            canonical_key = feed_batch_key(run_key_value, part_index)
        except ValueError:
            canonical_key = None
        if payload.get("batchKey") != canonical_key:
            errors.append("batch batchKey is not canonical")
    elif not isinstance(payload.get("batchKey"), str) or not payload.get("batchKey"):
        errors.append("batch batchKey must be a non-empty string")
    if not _is_canonical_utc(payload.get("fetchedAt")):
        errors.append("batch fetchedAt must be canonical UTC with second precision")
    if not _strict_int(payload.get("newItemCount"), 0):
        errors.append("batch newItemCount must be a non-negative integer")

    outcomes = payload.get("sourceOutcomes")
    if not isinstance(outcomes, list):
        errors.append("batch sourceOutcomes must be a list")
    else:
        feed_ids = [
            outcome.get("feedId") if isinstance(outcome, dict) else None
            for outcome in outcomes
        ]
        if tuple(feed_ids) != _CONFIGURED_FEED_IDS:
            errors.append("batch sourceOutcomes must contain configured sources in order")
        for index, outcome in enumerate(outcomes):
            prefix = f"batch sourceOutcomes[{index}]"
            if not isinstance(outcome, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if set(outcome) != _SOURCE_OUTCOME_KEYS:
                errors.append(f"{prefix} keys are not exact")
            status = outcome.get("status")
            item_count = outcome.get("itemCount")
            cursor = outcome.get("cursor")
            error = outcome.get("error")
            if not isinstance(status, str) or status not in {"ok", "error"}:
                errors.append(f"{prefix} status must be ok or error")
            if not _strict_int(item_count, 0):
                errors.append(f"{prefix} itemCount must be a non-negative integer")
            if not isinstance(cursor, str):
                errors.append(f"{prefix} cursor must be a string")
            if not isinstance(error, str):
                errors.append(f"{prefix} error must be a string")
            if status == "ok":
                if error != "":
                    errors.append(f"{prefix} successful outcome error must be empty")
                if not isinstance(cursor, str) or (
                    cursor != "" and re.fullmatch(r"[0-9a-f]{64}", cursor) is None
                ):
                    errors.append(f"{prefix} successful cursor is invalid")
            elif status == "error":
                if item_count != 0 or isinstance(item_count, bool):
                    errors.append(f"{prefix} failed outcome itemCount must be zero")
                if cursor != "":
                    errors.append(f"{prefix} failed outcome cursor must be empty")
                if not isinstance(error, str) or not error:
                    errors.append(f"{prefix} failed outcome error must be non-empty")

        successes = [
            outcome for outcome in outcomes
            if isinstance(outcome, dict) and outcome.get("status") == "ok"
        ]
        if not successes:
            errors.append("batch with all sources failed cannot be committed")

    items = payload.get("items")
    if not isinstance(items, list):
        errors.append("batch items must be a list")
    elif len(items) > 100:
        errors.append("batch items must contain at most 100 rows")
    else:
        for index, item in enumerate(items):
            if not isinstance(item, dict) or set(item) != _FEED_ITEM_KEYS:
                errors.append(f"batch item identity is invalid: items[{index}] keys are not exact")
                continue
            item_errors = validate_feed_row(item)
            errors.extend(
                f"batch item identity is invalid: items[{index}] {error}"
                for error in item_errors
            )
            if item.get("fetchedAt") != payload.get("fetchedAt"):
                errors.append(f"batch items[{index}].fetchedAt must equal batch fetchedAt")
            try:
                published_at = _aware_datetime(
                    item.get("publishedAt"), f"items[{index}].publishedAt"
                )
                fetched_at = _aware_datetime(
                    payload.get("fetchedAt"), "batch fetchedAt"
                )
            except ValueError:
                pass
            else:
                if published_at > fetched_at:
                    errors.append(
                        f"batch items[{index}].publishedAt must not be after batch fetchedAt"
                    )

        if isinstance(outcomes, list):
            outcome_by_feed = {
                outcome.get("feedId"): outcome
                for outcome in outcomes
                if isinstance(outcome, dict)
                and isinstance(outcome.get("feedId"), str)
            }
            item_counts: dict[str, int] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                feed_id = item.get("feedId")
                outcome = (
                    outcome_by_feed.get(feed_id)
                    if isinstance(feed_id, str)
                    else None
                )
                if not isinstance(outcome, dict) or outcome.get("status") != "ok":
                    errors.append("batch item must belong to a successful source outcome")
                    continue
                if isinstance(feed_id, str):
                    item_counts[feed_id] = item_counts.get(feed_id, 0) + 1
            for feed_id, count in item_counts.items():
                observed_count = outcome_by_feed[feed_id].get("itemCount")
                if not _strict_int(observed_count, 0) or count > observed_count:
                    errors.append(
                        f"batch items for {feed_id} exceed observed outcome itemCount"
                    )

    if _strict_int(part_index, 1, 999) and part_index == 1:
        window = payload.get("fingerprintWindow")
        if not isinstance(window, list):
            errors.append("batch fingerprintWindow must be a list on part one")
        else:
            try:
                fetched_at = _aware_datetime(payload.get("fetchedAt"), "fetchedAt")
                normalized_window = advance_fingerprint_window(
                    [], window, observed_at=fetched_at
                )
            except ValueError as exc:
                errors.append(f"batch fingerprintWindow invalid: {exc}")
            else:
                if normalized_window != window:
                    errors.append("batch fingerprintWindow is not canonical")
                items = payload.get("items")
                if isinstance(items, list):
                    item_entries = [
                        {
                            "sourceFingerprint": item.get("sourceFingerprint"),
                            "publishedAt": item.get("publishedAt"),
                        }
                        for item in items
                        if isinstance(item, dict)
                    ]
                    try:
                        closed_window = advance_fingerprint_window(
                            window, item_entries, observed_at=fetched_at
                        )
                    except ValueError as exc:
                        errors.append(f"batch fingerprintWindow invalid: {exc}")
                    else:
                        if closed_window != window:
                            errors.append(
                                "batch fingerprintWindow does not include current batch items"
                            )
    elif "fingerprintWindow" in payload:
        errors.append("only batch part one may carry fingerprintWindow")
    try:
        canonical_digest(payload)
    except (TypeError, ValueError) as exc:
        errors.append(f"batch payload is not canonicalizable: {exc}")
    return errors

def _valid_batch_payload(
    row: dict, payload_override: object | None = None
) -> tuple[dict | None, list[str]]:
    """Validate one flattened Feed Batch page and its canonical payload."""
    errors: list[str] = []
    payload = row.get("payload") if payload_override is None else payload_override
    errors.extend(_validate_feed_batch_payload(payload))
    if not isinstance(payload, dict):
        return None, errors
    if row.get("Body Format") not in READABLE_BODY_FORMATS:
        errors.append("batch Body Format mismatch")
    try:
        expected_digest = canonical_digest(payload)
    except (TypeError, ValueError) as exc:
        return None, [f"batch payload is not canonicalizable: {exc}"]
    if row.get("Payload Digest") != expected_digest:
        errors.append("batch payload digest mismatch")
    body = row.get("body")
    try:
        decoded, rendering, decoded_body_format = _decode_notion_body_with_format(body)
    except (TypeError, ValueError) as exc:
        errors.append(f"batch body invalid: {exc}")
    else:
        if decoded_body_format != row.get("Body Format"):
            errors.append("batch Body Format does not match body")
        if canonical_json_bytes(decoded) != canonical_json_bytes(payload):
            errors.append("batch decoded payload mismatch")
        if rendering:
            errors.append("feed batch must not have rendering")
    property_payload_pairs = (
        ("Run Key", "runKey"),
        ("Batch Key", "batchKey"),
        ("Part Index", "partIndex"),
        ("Part Count", "partCount"),
        ("Fetched At", "fetchedAt"),
        ("New Item Count", "newItemCount"),
    )
    for property_name, payload_name in property_payload_pairs:
        if not _exact_json_equal(row.get(property_name), payload.get(payload_name)):
            errors.append(f"batch {property_name} mismatch")
    run_key_value = row.get("Run Key")
    part_index = row.get("Part Index")
    if (
        isinstance(run_key_value, str)
        and isinstance(part_index, int)
        and not isinstance(part_index, bool)
    ):
        try:
            canonical_batch_key = feed_batch_key(run_key_value, part_index)
        except ValueError:
            canonical_batch_key = None
        if row.get("Batch Key") != canonical_batch_key:
            errors.append("batch physical key is not canonical")
    part_count = row.get("Part Count")
    item_count = row.get("Item Count")
    new_item_count = row.get("New Item Count")
    if not _strict_int(part_index, 1, 999):
        errors.append("batch Part Index must be an integer from 1 through 999")
    if not _strict_int(part_count, 1, 999):
        errors.append("batch Part Count must be an integer from 1 through 999")
    elif _strict_int(part_index, 1, 999) and part_index > part_count:
        errors.append("batch Part Index must not exceed Part Count")
    if not _strict_int(item_count, 0, 100):
        errors.append("batch Item Count must be an integer from 0 through 100")
    if not _strict_int(new_item_count, 0):
        errors.append("batch New Item Count must be a non-negative integer")
    items = payload.get("items")
    if isinstance(items, list) and (
        not _strict_int(item_count, 0, 100) or item_count != len(items)
    ):
        errors.append("batch Item Count mismatch")
    outcomes = payload.get("sourceOutcomes")
    if isinstance(outcomes, list) and all(isinstance(outcome, dict) for outcome in outcomes):
        successes = sum(outcome.get("status") == "ok" for outcome in outcomes)
        failures = sum(outcome.get("status") == "error" for outcome in outcomes)
        for property_name, derived in (
            ("Feed Success Count", successes),
            ("Feed Failure Count", failures),
        ):
            value = row.get(property_name)
            if not _strict_int(value, 0, len(_CONFIGURED_FEED_IDS)):
                errors.append(f"batch {property_name} must be a bounded integer")
            elif value != derived:
                errors.append(f"batch {property_name} mismatch")
        all_failed = row.get("All Sources Failed")
        if not isinstance(all_failed, bool):
            errors.append("batch All Sources Failed must be a boolean")
        elif all_failed != (successes == 0):
            errors.append("batch All Sources Failed mismatch")
    if _strict_int(row.get("Part Index"), 1, 999) and row.get("Part Index") == 1:
        window = payload.get("fingerprintWindow")
        if isinstance(window, list) and row.get("Fingerprint Window Digest") != canonical_digest(window):
            errors.append("batch fingerprint window digest mismatch")
    elif row.get("Fingerprint Window Digest") != "":
        errors.append("batch non-first part fingerprint window digest must be empty")
    return (payload if not errors else None), errors


def _complete_groups(rows: list[dict]) -> tuple[list[list[dict]], list[str]]:
    grouped: dict[str, list[dict]] = {}
    errors: list[str] = []
    for row in rows:
        run_key_value = row.get("Run Key")
        if not isinstance(run_key_value, str) or not run_key_value:
            errors.append("batch Run Key must be a non-empty string")
            continue
        grouped.setdefault(run_key_value, []).append(row)
    complete: list[list[dict]] = []
    for run_key_value in sorted(grouped):
        group = grouped[run_key_value]
        raw_counts = [row.get("Part Count") for row in group]
        indexes = [row.get("Part Index") for row in group]
        if (
            any(not _strict_int(value, 1, 999) for value in raw_counts)
            or len(set(raw_counts)) != 1
        ):
            errors.append(
                f"incomplete batch {run_key_value}: Part Count must be consistent and 1 through 999"
            )
            continue
        part_count = raw_counts[0]
        if any(not _strict_int(value, 1, 999) for value in indexes):
            errors.append(f"incomplete batch {run_key_value}: Part Index must be 1 through 999")
            continue
        unique_indexes = set(indexes)
        if (
            len(indexes) != part_count
            or len(unique_indexes) != part_count
            or min(unique_indexes) != 1
            or max(unique_indexes) != part_count
        ):
            errors.append(f"incomplete batch {run_key_value}: missing or duplicate parts")
            continue
        parent_ids: list[str] = []
        invalid_parent = False
        for row in group:
            try:
                parent_id = _single_parent_id(row)
            except ValueError as exc:
                errors.append(f"incomplete batch {run_key_value}: {exc}")
                invalid_parent = True
            else:
                if parent_id is not None:
                    parent_ids.append(parent_id)
        if invalid_parent:
            continue
        if len(parent_ids) != len(group) or len(set(parent_ids)) != 1:
            errors.append(f"incomplete batch {run_key_value}: inconsistent Run parent")
            continue
        page_ids = [row.get("page_id") for row in group]
        invalid_page_id = False
        for page_id in page_ids:
            try:
                _parse_uuid(page_id, "Feed Batch page_id")
            except ValueError as exc:
                errors.append(f"incomplete batch {run_key_value}: {exc}")
                invalid_page_id = True
        if invalid_page_id or len(set(page_ids)) != len(page_ids):
            errors.append(f"incomplete batch {run_key_value}: invalid or duplicate page ID")
            continue
        complete.append(sorted(group, key=lambda row: row["Part Index"]))
    return complete, errors


def _validated_complete_feed_groups(
    rows: list[dict],
) -> tuple[list[tuple[list[dict], list[dict]]], list[str]]:
    """Return only complete groups whose every page and cross-part metadata validate."""
    groups, errors = _complete_groups(rows)
    valid: list[tuple[list[dict], list[dict]]] = []
    for group in groups:
        run_key_value = group[0].get("Run Key", "batch")
        payloads: list[dict] = []
        group_errors: list[str] = []
        for row in group:
            payload, row_errors = _valid_batch_payload(row)
            group_errors.extend(row_errors)
            if payload is not None:
                payloads.append(payload)
        if group_errors:
            errors.extend(f"{run_key_value}: {error}" for error in group_errors)
            continue
        first = payloads[0]
        for payload in payloads[1:]:
            for field in ("fetchedAt", "newItemCount", "sourceOutcomes"):
                if payload.get(field) != first.get(field):
                    group_errors.append(f"batch parts have inconsistent {field}")
        fingerprints = [
            item["sourceFingerprint"]
            for payload in payloads
            for item in payload["items"]
        ]
        if len(fingerprints) != len(set(fingerprints)):
            group_errors.append("batch parts contain duplicate item identities")
        if len(set(fingerprints)) != first.get("newItemCount"):
            group_errors.append("batch total unique item count does not match newItemCount")
        outcomes_by_feed = {
            outcome["feedId"]: outcome for outcome in first.get("sourceOutcomes", [])
        }
        cumulative_counts: dict[str, int] = {}
        for payload in payloads:
            for item in payload["items"]:
                feed_id = item["feedId"]
                cumulative_counts[feed_id] = cumulative_counts.get(feed_id, 0) + 1
        for feed_id, count in cumulative_counts.items():
            outcome = outcomes_by_feed.get(feed_id)
            if (
                not isinstance(outcome, dict)
                or outcome.get("status") != "ok"
                or not _strict_int(outcome.get("itemCount"), 0)
                or count > outcome["itemCount"]
            ):
                group_errors.append(
                    f"batch items for {feed_id} exceed observed outcome itemCount across parts"
                )
        all_item_entries = [
            {
                "sourceFingerprint": item["sourceFingerprint"],
                "publishedAt": item["publishedAt"],
            }
            for payload in payloads
            for item in payload["items"]
        ]
        try:
            closed_window = advance_fingerprint_window(
                first.get("fingerprintWindow", []),
                all_item_entries,
                observed_at=_aware_datetime(first.get("fetchedAt"), "fetchedAt"),
            )
        except ValueError as exc:
            group_errors.append(f"batch fingerprintWindow invalid: {exc}")
        else:
            if closed_window != first.get("fingerprintWindow"):
                group_errors.append(
                    "batch part-one fingerprintWindow does not include items from every part"
                )
        if group_errors:
            errors.extend(f"{run_key_value}: {error}" for error in group_errors)
            continue
        valid.append((group, payloads))
    return valid, errors


def load_or_rebuild_fingerprint_window(
    checkpoint_rows: Iterable[dict],
    recent_batch_rows: Iterable[dict],
    committed_run_ids: set[str],
    now: datetime,
) -> dict:
    """Union committed complete Feed checkpoints and recent complete batch rows."""
    current_time = _aware_datetime(now, "now")
    horizon = current_time - timedelta(hours=12)
    if not isinstance(committed_run_ids, set):
        raise ValueError("committed_run_ids must be a set of UUID strings")
    for run_id in committed_run_ids:
        _parse_uuid(run_id, "committed Run page ID")
    errors: list[str] = []
    entries: list[dict] = []

    def committed_full_rows(
        values: Iterable[dict], label: str
    ) -> list[dict]:
        valid_rows: list[dict] = []
        expected_fields = _OPERATIONAL_CHILD_FIELDS["feed"]
        for index, row in enumerate(values):
            prefix = f"{label}[{index}]"
            if not isinstance(row, dict) or set(row) != expected_fields:
                errors.append(f"{prefix} must be a full Feed row")
                continue
            try:
                _parse_uuid(row.get("page_id"), f"{prefix} page_id")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            try:
                parent_id = _single_parent_id(row)
            except ValueError as exc:
                errors.append(f"{prefix} {exc}")
                continue
            if parent_id not in committed_run_ids:
                continue
            if not isinstance(row.get("Name"), str) or not row["Name"].strip():
                errors.append(f"{prefix} Name must be a non-empty string")
                continue
            if (
                not isinstance(row.get("Created At"), str)
                or not row["Created At"]
            ):
                errors.append(f"{prefix} Created At must be observed")
                continue
            valid_rows.append(row)
        return valid_rows

    checkpoint_candidates = committed_full_rows(checkpoint_rows, "checkpoint")
    committed_rows = committed_full_rows(recent_batch_rows, "recent batch")
    page_id_counts: dict[str, int] = {}
    for row in (*checkpoint_candidates, *committed_rows):
        page_id = row["page_id"]
        page_id_counts[page_id] = page_id_counts.get(page_id, 0) + 1
    duplicate_page_ids = {
        page_id for page_id, count in page_id_counts.items() if count > 1
    }
    if duplicate_page_ids:
        errors.append("duplicate authoritative Feed page_id")
        checkpoint_candidates = [
            row
            for row in checkpoint_candidates
            if row["page_id"] not in duplicate_page_ids
        ]
        committed_rows = [
            row
            for row in committed_rows
            if row["page_id"] not in duplicate_page_ids
        ]
    checkpoint_groups, checkpoint_errors = _validated_complete_feed_groups(
        checkpoint_candidates
    )
    errors.extend(f"checkpoint: {error}" for error in checkpoint_errors)
    valid_checkpoints: list[tuple[datetime, dict]] = []
    for _group, payloads in checkpoint_groups:
        part_one = payloads[0]
        fetched_at = _aware_datetime(
            part_one.get("fetchedAt"), "checkpoint fetchedAt"
        )
        if fetched_at > current_time:
            errors.append("checkpoint fetchedAt cannot be in the future")
            continue
        valid_checkpoints.append((fetched_at, part_one))

    recent_checkpoints = [
        pair for pair in valid_checkpoints if horizon <= pair[0] <= current_time
    ]
    selected_checkpoints = recent_checkpoints
    if not selected_checkpoints and valid_checkpoints:
        latest_old = max(pair[0] for pair in valid_checkpoints)
        selected_checkpoints = [
            pair for pair in valid_checkpoints if pair[0] == latest_old
        ]

    groups, group_errors = _validated_complete_feed_groups(committed_rows)
    errors.extend(group_errors)
    usable_groups: list[tuple[datetime, list[dict]]] = []
    for _group, payloads in groups:
        fetched_at = _aware_datetime(payloads[0]["fetchedAt"], "batch fetchedAt")
        if fetched_at > current_time:
            errors.append("recent batch fetchedAt cannot be in the future")
            continue
        if fetched_at < horizon:
            continue
        usable_groups.append((fetched_at, payloads))

    stable_checkpoints: list[tuple[datetime, dict]] = []
    for fetched_at, payload in selected_checkpoints:
        if fetched_at >= horizon:
            prior_group_items = [
                {
                    "sourceFingerprint": item["sourceFingerprint"],
                    "publishedAt": item["publishedAt"],
                }
                for group_fetched_at, payloads in usable_groups
                if group_fetched_at <= fetched_at
                for group_payload in payloads
                for item in group_payload["items"]
            ]
            advanced = advance_fingerprint_window(
                payload["fingerprintWindow"],
                prior_group_items,
                observed_at=fetched_at,
            )
            if advanced != payload["fingerprintWindow"]:
                errors.append(
                    "selected checkpoint is unstable against prior committed Feed items"
                )
                continue
        stable_checkpoints.append((fetched_at, payload))
    for _fetched_at, payload in stable_checkpoints:
        entries.extend(payload["fingerprintWindow"])
    valid_checkpoint_seen = bool(stable_checkpoints)

    for _fetched_at, payloads in usable_groups:
        group_entries: list[dict] = []
        part_one = payloads[0]
        window = part_one.get("fingerprintWindow")
        if isinstance(window, list):
            group_entries.extend(window)
        group_entries.extend(
            {
                "sourceFingerprint": item["sourceFingerprint"],
                "publishedAt": item["publishedAt"],
            }
            for payload in payloads
            for item in payload["items"]
        )
        entries.extend(group_entries)
    rebuilt = bool(errors) or not valid_checkpoint_seen
    if rebuilt and "fingerprint-window-rebuilt" not in errors:
        errors.append("fingerprint-window-rebuilt")
    return {
        "window": advance_fingerprint_window([], entries, observed_at=current_time),
        "rebuilt": rebuilt,
        "errors": errors,
    }


def merge_committed_feed_items(
    batch_rows: Iterable[dict],
    committed_run_ids: set[str],
    after: datetime,
    through: datetime,
) -> list[dict]:
    """Merge complete committed FEED batches in the logical cutoff interval ``(after, through]``."""
    after_utc = _aware_datetime(after, "after")
    through_utc = _aware_datetime(through, "through")
    if after_utc > through_utc:
        raise ValueError("after must not be later than through")
    committed_rows: list[dict] = []
    for row in batch_rows:
        if not isinstance(row, dict):
            raise ValueError("batch_rows must contain objects")
        parent_id = _single_parent_id(row)
        if parent_id not in committed_run_ids:
            continue
        committed_rows.append(row)
    seen_page_ids: set[str] = set()
    for row in committed_rows:
        try:
            page_id = _parse_uuid(row.get("page_id"), "Feed Batch page_id")
        except ValueError:
            continue
        if page_id in seen_page_ids:
            raise ValueError("duplicate authoritative Feed page_id")
        seen_page_ids.add(page_id)
    groups, errors = _validated_complete_feed_groups(committed_rows)
    if errors:
        raise ValueError("; ".join(errors))
    items: list[dict] = []
    for _group, payloads in groups:
        fetched_at = _aware_datetime(payloads[0]["fetchedAt"], "Fetched At")
        if after_utc < fetched_at <= through_utc:
            items.extend(item for payload in payloads for item in payload["items"])
    return merge_buffer([], items)


def select_current_memory(
    rows: Iterable[dict], committed_run_ids: set[str]
) -> tuple[list[dict], list[str]]:
    """Select each valid logical record's unique maximum committed revision."""
    committed: list[dict] = []
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("memory row must be an object")
            continue
        parent_id = _single_parent_id(row, errors=errors)
        if parent_id in committed_run_ids:
            committed.append(row)
    page_ids: dict[str, dict] = {}
    invalid_records: set[str] = set()
    groups: dict[str, list[dict]] = {}
    for row in committed:
        record = row.get("Record Key")
        page_id = row.get("page_id")
        revision = row.get("Revision")
        if not isinstance(record, str) or not record:
            errors.append("committed Memory Record Key is invalid")
            continue
        groups.setdefault(record, []).append(row)
        try:
            _parse_uuid(page_id, "committed Memory page_id")
        except ValueError as exc:
            errors.append(f"{record}: {exc}")
            invalid_records.add(record)
        else:
            if page_id in page_ids:
                errors.append(f"{record}: duplicate or invalid Memory page_id")
                invalid_records.add(record)
                prior_record = page_ids[page_id].get("Record Key")
                if isinstance(prior_record, str):
                    invalid_records.add(prior_record)
            else:
                page_ids[page_id] = row
        if not _strict_int(revision, 1, 999999):
            errors.append(f"{record}: Revision must be an integer from 1 through 999999")
            invalid_records.add(record)

    current: list[dict] = []
    for record in sorted(groups):
        group = groups[record]
        by_revision: dict[int, list[dict]] = {}
        for row in group:
            revision = row.get("Revision")
            if _strict_int(revision, 1, 999999):
                by_revision.setdefault(revision, []).append(row)
        duplicates = [revision for revision, values in by_revision.items() if len(values) > 1]
        if duplicates:
            errors.append(f"{record}: duplicate committed revision {min(duplicates)}")
            invalid_records.add(record)
        if by_revision:
            ordered_revisions = sorted(by_revision)
            maximum = ordered_revisions[-1]
            if ordered_revisions[0] != 1 or any(
                current != previous + 1
                for previous, current in zip(ordered_revisions, ordered_revisions[1:])
            ):
                errors.append(f"{record}: committed revision gap")
                invalid_records.add(record)
            if len(by_revision.get(1, [])) == 1 and by_revision[1][0].get("Supersedes") != []:
                errors.append(f"{record}: first revision must not supersede a predecessor")
                invalid_records.add(record)
            for prior_revision, revision in zip(ordered_revisions, ordered_revisions[1:]):
                if revision != prior_revision + 1:
                    continue
                if len(by_revision[revision]) != 1 or len(by_revision[prior_revision]) != 1:
                    continue
                predecessor_id = by_revision[prior_revision][0].get("page_id")
                if by_revision[revision][0].get("Supersedes") != [predecessor_id]:
                    errors.append(f"{record}: revision {revision} has the wrong predecessor")
                    invalid_records.add(record)
            if record not in invalid_records and len(by_revision[maximum]) == 1:
                current.append(by_revision[maximum][0])
    return current, errors


def _validate_parent_run_binding(parent_run: object, installation: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(parent_run, dict) or not isinstance(installation, dict):
        return ["parent Run and Installation snapshots must be objects"]
    try:
        parent_page_id = _parse_uuid(parent_run.get("page_id"), "parent Run page_id")
    except ValueError as exc:
        errors.append(str(exc))
        parent_page_id = None
    try:
        installation_page_id = _parse_uuid(
            installation.get("page_id"), "Installation page_id"
        )
    except ValueError as exc:
        errors.append(str(exc))
        installation_page_id = None
    installation_value = parent_run.get("Installation")
    if installation_page_id is not None and installation_value != [installation_page_id]:
        errors.append("parent Run Installation relation mismatch")
    installation_key_value = installation.get("Installation Key")
    trigger = parent_run.get("Trigger")
    started_at = parent_run.get("Started At")
    if not isinstance(installation_key_value, str) or not installation_key_value:
        errors.append("Installation Key must be a non-empty string")
    if not isinstance(trigger, str) or trigger not in _TRIGGERS:
        errors.append("parent Run Trigger is invalid")
    if not _is_canonical_utc(started_at):
        errors.append("parent Run Started At must be canonical UTC")
    collection_cutoff = parent_run.get("Collection Cutoff")
    if (
        not isinstance(collection_cutoff, str)
        or not collection_cutoff
        or not _is_canonical_utc(collection_cutoff)
    ):
        errors.append("parent Run Collection Cutoff must be nonempty canonical UTC")
    if type(parent_run.get("Material Change")) is not bool:
        errors.append("parent Run Material Change must be a boolean")
    if type(parent_run.get("Integration Due")) is not bool:
        errors.append("parent Run Integration Due must be a boolean")
    if type(parent_run.get("Integration Performed")) is not bool:
        errors.append("parent Run Integration Performed must be a boolean")
    notification_plan = parent_run.get("Notification Plan")
    if (
        not isinstance(notification_plan, str)
        or notification_plan not in _NOTIFICATION_PLANS
    ):
        errors.append("parent Run Notification Plan is invalid")
    expected_slot = None
    if (
        isinstance(installation_key_value, str)
        and installation_key_value
        and isinstance(trigger, str)
        and trigger in _TRIGGERS
        and _is_canonical_utc(started_at)
    ):
        expected_slot = slot_key(
            installation_key_value,
            trigger,
            _aware_datetime(started_at, "Started At"),
        )
        if parent_run.get("Slot Key") != expected_slot:
            errors.append("parent Run Slot Key does not match Installation and start")
        slot_match = _SLOT_KEY.fullmatch(expected_slot)
        expected_scheduled = (
            datetime.strptime(slot_match.group(3), "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
            if slot_match is not None
            else None
        )
        if parent_run.get("Scheduled Slot") != expected_scheduled:
            errors.append("parent Run Scheduled Slot does not match Slot Key")
    attempt = parent_run.get("Attempt")
    if not _strict_int(attempt, 1, 999):
        errors.append("parent Run Attempt must be an integer from 1 through 999")
    elif expected_slot is not None:
        expected_run_key = run_key(expected_slot, attempt)
        if parent_run.get("Run Key") != expected_run_key:
            errors.append("parent Run Key does not match Slot Key and Attempt")
        if not isinstance(parent_run.get("Name"), str) or not parent_run["Name"].strip():
            errors.append("parent Run Name must be a non-empty string")
    integration = parent_run.get("Integration Key")
    if not isinstance(integration, str):
        errors.append("parent Run Integration Key must be a string")
    elif integration:
        prefix = (
            hashlib.sha256(installation_key_value.encode("utf-8")).hexdigest()[:12]
            if isinstance(installation_key_value, str) and installation_key_value
            else None
        )
        match = _INTEGRATION_KEY.fullmatch(integration)
        if (
            prefix is None
            or match is None
            or not integration.startswith(f"wmi_{prefix}_")
        ):
            errors.append("parent Run Integration Key does not match Installation")
    _ = parent_page_id
    return errors


def _valid_evidence_entries(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for entry in value:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            return False
        url = entry.get("url")
        if (
            not isinstance(url, str)
            or not url
            or re.search(r"[\s\x00-\x1f\x7f]", url) is not None
        ):
            return False
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            _ = parsed.port
        except (TypeError, ValueError):
            return False
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not isinstance(hostname, str)
            or not hostname.strip()
        ):
            return False
    return True


def _validate_memory_payload(
    page: dict,
    payload: dict,
    *,
    authoritative_completion: bool = False,
) -> list[str]:
    errors: list[str] = []
    required = {
        "schemaVersion", "kind", "recordType", "action", "target", "evidence",
        "confidence", "result",
    }
    missing = required - set(payload)
    if missing:
        errors.append("Memory payload is missing: " + ", ".join(sorted(missing)))
    if type(payload.get("schemaVersion")) is not int or payload.get("schemaVersion") != 2:
        errors.append("Memory payload schemaVersion must be integer 2")
    if payload.get("kind") != "memory":
        errors.append("Memory payload kind must be memory")
    for field in sorted(_MEMORY_PAYLOAD_FORBIDDEN_FIELDS & set(payload)):
        errors.append(f"Memory payload {field} is forbidden")
    record_type = payload.get("recordType")
    action = payload.get("action")
    action_map = {
        "brief": {"brief-add"},
        "state": {"state-add", "state-supersede"},
        "story-link": {"story-link"},
        "taxonomy": {"taxonomy-refresh"},
        "suggestion": {"suggestion-status-update"},
    }
    if not isinstance(record_type, str) or record_type not in action_map:
        errors.append("Memory payload recordType is invalid")
    elif not isinstance(action, str) or action not in action_map[record_type]:
        errors.append("Memory payload action does not match recordType")
    target = payload.get("target")
    if not isinstance(target, str) or not target.strip():
        errors.append("Memory payload target must be a non-empty string")
    confidence = payload.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        errors.append("Memory payload confidence must be between 0 and 1")
    if "result" in payload:
        try:
            _validate_json_shape(payload["result"])
        except (TypeError, ValueError) as exc:
            errors.append(f"Memory payload result must be valid JSON: {exc}")
    evidence_value = payload.get("evidence")
    if not isinstance(evidence_value, list):
        errors.append("Memory payload evidence must be a list")
    evidence_is_valid = _valid_evidence_entries(evidence_value)
    sources_are_valid = _valid_evidence_entries(payload.get("sources"))
    if record_type in ("brief", "state") and not evidence_is_valid:
        errors.append("Memory brief/state mutation requires verified evidence")
    if record_type == "state" and not sources_are_valid:
        errors.append("Memory state mutation requires valid domain sources")
    for property_name, allowed in (
        ("Importance", {"", "high", "medium", "low"}),
        ("Category", {"", "stock_bond", "geopolitics", "emerging"}),
        ("Region", {"", "US", "KR", "GLOBAL"}),
    ):
        value = page.get(property_name)
        if not isinstance(value, str) or value not in allowed:
            errors.append(f"Memory {property_name} is invalid")
    effective_at = page.get("Effective At")
    if not isinstance(effective_at, str) or (
        effective_at != "" and not _is_canonical_utc(effective_at)
    ):
        errors.append("Memory Effective At must be empty or canonical UTC")
    for property_name, payload_value in (
        ("Record Type", record_type),
        ("Action", action),
        ("Target", target),
        ("Confidence", confidence),
        ("Dedupe Key", payload.get("dedupe_key", "")),
        ("Continuity ID", payload.get("continuityId", "")),
    ):
        if not _exact_json_equal(page.get(property_name), payload_value):
            errors.append(f"Memory {property_name} does not match payload")
    verified_evidence = (
        evidence_is_valid and sources_are_valid
        if record_type == "state"
        else evidence_is_valid
    )
    if page.get("Verified Evidence") is not verified_evidence:
        errors.append("Memory Verified Evidence does not match verified evidence")
    if record_type != "suggestion" and page.get("Record Status") != "active":
        errors.append("non-suggestion Memory Record Status must be active")
    if record_type == "suggestion" and (
        not isinstance(page.get("Record Status"), str)
        or page.get("Record Status") not in {"open", "watching", "completed"}
    ):
        errors.append("suggestion Memory Record Status is invalid")
    if (
        record_type == "suggestion"
        and page.get("Record Status") == "completed"
        and authoritative_completion is not True
    ):
        errors.append(
            "suggestion completion requires an authoritative caller observation"
        )
    for property_name, payload_name in (
        ("Record Status", "recordStatus"),
        ("Importance", "importance"),
        ("Category", "category"),
        ("Region", "region"),
        ("Effective At", "effectiveAt"),
    ):
        if payload_name in payload and not _exact_json_equal(
            page.get(property_name), payload[payload_name]
        ):
            errors.append(f"Memory {property_name} does not match payload")
    if isinstance(record_type, str):
        try:
            expected_record_key = memory_record_key(record_type, payload)
        except ValueError as exc:
            errors.append(f"Memory stable identity invalid: {exc}")
        else:
            if page.get("Record Key") != expected_record_key:
                errors.append("Memory Record Key does not match stable payload identity")
    return errors


def validate_child_page(
    kind: str,
    page: dict,
    expected: dict,
    parent_run: dict,
    installation: dict,
    *,
    authoritative_completion: bool = False,
) -> list[str]:
    """Validate authoritative child read-back without trusting unfetched fields."""
    errors: list[str] = []
    if not isinstance(kind, str) or kind not in {"feed", "memory", "report"}:
        return ["child kind must be feed, memory, or report"]
    if not isinstance(page, dict) or not isinstance(expected, dict):
        return ["child page and expected values must be objects"]
    if type(authoritative_completion) is not bool:
        return ["authoritative_completion must be a boolean"]
    operational_installation = installation
    try:
        operational_installation = validate_operational_installation(installation)
    except ValueError as exc:
        errors.append(f"Installation snapshot is invalid: {exc}")
    errors.extend(
        _validate_parent_run_binding(parent_run, operational_installation)
    )
    expected_parent_id = parent_run.get("page_id") if isinstance(parent_run, dict) else None
    expected_parent_run_key = parent_run.get("Run Key") if isinstance(parent_run, dict) else None
    expected_fields = _OPERATIONAL_CHILD_FIELDS[kind]
    if set(expected) != expected_fields:
        errors.append(
            f"expected {kind} child snapshot must contain exactly every Notion property"
        )
    if set(page) != expected_fields:
        errors.append(
            f"fetched {kind} child snapshot must contain exactly every Notion property"
        )
    try:
        _parse_uuid(page.get("page_id"), "child page_id")
    except ValueError as exc:
        errors.append(str(exc))
    parent_id = _single_parent_id(page, errors=errors)
    if parent_id is not None and parent_id != expected_parent_id:
        errors.append("Run relation parent mismatch")
    for property_name, expected_value in expected.items():
        if not _exact_json_equal(page.get(property_name), expected_value):
            errors.append(f"{property_name} mismatch")
    if page.get("Body Format") not in READABLE_BODY_FORMATS:
        errors.append("Body Format mismatch")
    expected_payload = expected.get("payload")
    expected_rendering = expected.get("rendering", "") if kind == "report" else ""
    if not isinstance(expected_payload, dict) or not isinstance(expected_rendering, str):
        errors.append("expected payload/rendering is malformed")
        return errors
    try:
        decoded_payload, decoded_rendering, decoded_body_format = (
            _decode_notion_body_with_format(page.get("body"))
        )
    except (TypeError, ValueError) as exc:
        errors.append(f"body validation failed: {exc}")
    else:
        if decoded_body_format != page.get("Body Format"):
            errors.append("Body Format does not match body")
        if canonical_json_bytes(decoded_payload) != canonical_json_bytes(expected_payload):
            errors.append("decoded payload mismatch")
        if decoded_rendering != expected_rendering:
            errors.append("Korean rendering mismatch")
    try:
        payload_digest = canonical_digest(expected_payload)
    except (TypeError, ValueError) as exc:
        errors.append(f"expected payload invalid: {exc}")
        return errors
    if page.get("Payload Digest") != payload_digest:
        errors.append("Payload Digest mismatch")
    if not isinstance(page.get("Name"), str) or not page["Name"].strip():
        errors.append(f"{kind} Name must be a non-empty string")

    run_key_value = page.get("Run Key")
    if run_key_value != expected_parent_run_key:
        errors.append("child Run Key does not match parent Run Key")
    payload_run_key = expected_payload.get("runKey")
    if kind == "feed" and payload_run_key != expected_parent_run_key:
        errors.append("child payload runKey does not match parent Run Key")
    if kind == "feed":
        _payload, feed_errors = _valid_batch_payload(page, expected_payload)
        errors.extend(feed_errors)
        if not isinstance(page.get("Created At"), str) or not page.get("Created At"):
            errors.append("Feed Created At must be observed")
    elif kind == "memory":
        errors.extend(
            _validate_memory_payload(
                page,
                expected_payload,
                authoritative_completion=authoritative_completion,
            )
        )
        record = page.get("Record Key")
        revision = page.get("Revision")
        if isinstance(record, str) and isinstance(run_key_value, str) and isinstance(revision, int) and not isinstance(revision, bool):
            try:
                expected_key = revision_key(record, revision, run_key_value)
            except ValueError:
                expected_key = None
            if page.get("Revision Key") != expected_key:
                errors.append("Revision Key is not canonical")
        else:
            errors.append("Memory revision identity is malformed")
        supersedes = page.get("Supersedes")
        if revision == 1 and supersedes != []:
            errors.append("first revision must not Supersede")
        if isinstance(revision, int) and revision > 1 and (
            not isinstance(supersedes, list) or len(supersedes) != 1
        ):
            errors.append("successor revision requires one Supersedes relation")
        if isinstance(supersedes, list):
            for index, predecessor_id in enumerate(supersedes):
                try:
                    _parse_uuid(predecessor_id, f"Supersedes[{index}]")
                except ValueError as exc:
                    errors.append(str(exc))
        for property_name in ("Created At", "Updated At"):
            if (
                not isinstance(page.get(property_name), str)
                or not page[property_name]
            ):
                errors.append(f"Memory {property_name} must be observed")
    else:
        for field in sorted(
            _REPORT_PAYLOAD_FORBIDDEN_FIELDS & set(expected_payload)
        ):
            errors.append(f"Report payload {field} is forbidden")
        errors.extend(
            f"Report payload invalid: {error}"
            for error in validate_report(expected_payload)
        )
        if page.get("Rendering Digest") != hashlib.sha256(expected_rendering.encode("utf-8")).hexdigest():
            errors.append("Rendering Digest mismatch")
        report_type = page.get("Report Type")
        integration = page.get("Integration Key")
        report_key_value = page.get("Report Key")
        coverage_start = page.get("Coverage Start")
        user_visible = page.get("User Visible")
        valid_report_type = (
            isinstance(report_type, str)
            and report_type in {"hourly-briefing", "six-hour"}
        )
        if not valid_report_type:
            errors.append(
                "Report Type must be hourly-briefing or six-hour"
            )
        if not isinstance(integration, str):
            errors.append("Report Integration Key must be a string")
        if not isinstance(report_key_value, str) or not report_key_value:
            errors.append("Report Key must be a non-empty string")
        if not isinstance(coverage_start, str):
            errors.append("Report Coverage Start must be a string")
        if type(user_visible) is not bool:
            errors.append("Report User Visible must be a boolean")
        if user_visible is not True:
            errors.append("Report User Visible must be true")
        if type(page.get("Material Change")) is not bool:
            errors.append("Report Material Change must be a boolean")
        if (
            isinstance(run_key_value, str)
            and valid_report_type
            and isinstance(integration, str)
            and isinstance(report_key_value, str)
            and report_key_value
        ):
            try:
                expected_key = report_key(run_key_value, report_type, integration)
            except ValueError:
                expected_key = None
            if expected_key is None or report_key_value != expected_key:
                errors.append("Report Key is not canonical")
        parent_integration = parent_run.get("Integration Key")
        parent_material = parent_run.get("Material Change")
        parent_integration_due = parent_run.get("Integration Due")
        parent_integration_performed = parent_run.get("Integration Performed")
        parent_notification = parent_run.get("Notification Plan")
        cutoff = parent_run.get("Collection Cutoff")
        as_of = page.get("As Of")
        coverage_end = page.get("Coverage End")
        if (
            not isinstance(as_of, str)
            or not as_of
            or not _is_canonical_utc(as_of)
        ):
            errors.append("Report As Of must be nonempty canonical UTC")
        if (
            not isinstance(coverage_end, str)
            or not coverage_end
            or not _is_canonical_utc(coverage_end)
        ):
            errors.append("Report Coverage End must be nonempty canonical UTC")
        if page.get("As Of") != expected_payload.get("asOf") or page.get("As Of") != cutoff:
            errors.append("Report As Of must equal payload asOf and parent cutoff")
        if page.get("Coverage End") != cutoff:
            errors.append("Report Coverage End must equal parent cutoff")
        if report_type == "six-hour" and isinstance(integration, str):
            if parent_integration_due is not True:
                errors.append("six-hour Report requires parent Integration Due")
            if parent_integration_performed is not True:
                errors.append(
                    "six-hour Report requires parent Integration Performed"
                )
            if parent_notification != "six-hour":
                errors.append(
                    "six-hour Report requires parent Notification Plan six-hour"
                )
            if not _is_valid_integration_key(integration):
                errors.append("six-hour Report Integration Key must be canonical")
            if integration != parent_integration:
                errors.append("six-hour Report Integration Key must equal parent Run")
            match = _INTEGRATION_KEY.fullmatch(integration)
            encoded_cutoff = match.group(2) if match is not None else None
            if encoded_cutoff is not None:
                expected_start = datetime.strptime(
                    encoded_cutoff, "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=timezone.utc)
                expected_start_text = utc_iso(expected_start)
                if coverage_start != expected_start_text:
                    errors.append(
                        "six-hour Report Coverage Start must equal Integration cutoff"
                    )
            elif isinstance(coverage_start, str) and coverage_start != "" and not _is_canonical_utc(coverage_start):
                errors.append("genesis Report Coverage Start must be empty or canonical UTC")
        elif report_type == "hourly-briefing":
            if parent_integration_due is not False:
                errors.append("hourly Report requires parent Integration Due false")
            if parent_integration_performed is not False:
                errors.append(
                    "hourly Report requires parent Integration Performed false"
                )
            if parent_notification != "hourly-briefing":
                errors.append(
                    "hourly Report requires parent Notification Plan hourly-briefing"
                )
            if integration != "" or parent_integration != "":
                errors.append("hourly Report Integration Key must be empty")
            if parent_material is not True:
                errors.append("hourly Report requires material change and User Visible")
            if isinstance(coverage_start, str) and coverage_start != "" and not _is_canonical_utc(coverage_start):
                errors.append("hourly Report Coverage Start must be empty or canonical UTC")
        if (
            isinstance(coverage_start, str)
            and coverage_start
            and _is_canonical_utc(coverage_start)
            and _is_canonical_utc(page.get("Coverage End"))
            and _aware_datetime(coverage_start, "Coverage Start")
            > _aware_datetime(page["Coverage End"], "Coverage End")
        ):
            errors.append("Report Coverage Start must not be after Coverage End")
        for property_name, derived in (
            ("Stance", expected_payload.get("stance")),
            ("Confidence", expected_payload.get("confidence")),
            (
                "Data Gap Count",
                len(expected_payload.get("dataQuality", {}).get("gaps", []))
                if isinstance(expected_payload.get("dataQuality"), dict)
                and isinstance(expected_payload["dataQuality"].get("gaps"), list)
                else None,
            ),
            ("Material Change", parent_material),
        ):
            if not _exact_json_equal(page.get(property_name), derived):
                errors.append(f"Report {property_name} does not match derived value")
        if page.get("User Visible") is True and (
            not expected_rendering.strip()
            or re.search(r"[가-힣]", expected_rendering) is None
        ):
            errors.append("visible Report requires nonempty Korean rendering")
        if not isinstance(page.get("Created At"), str) or not page["Created At"]:
            errors.append("Report Created At must be observed")
        evidence_records = page.get("Evidence Records")
        if not isinstance(evidence_records, list):
            errors.append("Report Evidence Records must be a list")
        else:
            string_evidence_ids = [
                evidence_id
                for evidence_id in evidence_records
                if isinstance(evidence_id, str)
            ]
            if len(string_evidence_ids) != len(set(string_evidence_ids)):
                errors.append("Report Evidence Records must be unique and ordered")
            for index, evidence_id in enumerate(evidence_records):
                try:
                    _parse_uuid(evidence_id, f"Evidence Records[{index}]")
                except ValueError as exc:
                    errors.append(str(exc))
    return errors


def verify_child_set(
    expected_keys: set[str], rows: Iterable[dict], expected_parent_id: str
) -> list[str]:
    """Require exact unique physical child keys, page IDs, and parent relations."""
    errors: list[str] = []
    try:
        _parse_uuid(expected_parent_id, "expected parent page ID")
    except ValueError as exc:
        errors.append(str(exc))
    if not isinstance(expected_keys, set) or any(
        not isinstance(key, str) or not key for key in expected_keys
    ):
        return ["expected_keys must be a set of non-empty strings"]
    actual_keys: list[str] = []
    page_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("child row must be an object")
            continue
        present = [field for field in _PHYSICAL_KEY_FIELDS if field in row]
        if len(present) != 1:
            errors.append("child row must have exactly one physical key field")
            continue
        key = row.get(present[0])
        if not isinstance(key, str) or not key:
            errors.append("child physical key must be a non-empty string")
        else:
            actual_keys.append(key)
        page_id = row.get("page_id")
        try:
            _parse_uuid(page_id, "child page_id")
        except ValueError as exc:
            errors.append(str(exc))
        else:
            page_ids.append(page_id)
        parent_id = _single_parent_id(row, errors=errors)
        if parent_id is not None and parent_id != expected_parent_id:
            errors.append(f"child {key!r} has the wrong Run parent")
    if set(actual_keys) != expected_keys:
        errors.append("child physical key set mismatch")
    if len(actual_keys) != len(set(actual_keys)):
        errors.append("duplicate child physical key")
    if len(page_ids) != len(set(page_ids)):
        errors.append("duplicate child page_id")
    return errors


def verify_precommit_snapshot(
    slot_rows: Iterable[dict],
    exact_run_rows: Iterable[dict],
    expected_run_page_id: str,
    child_rows_by_kind: dict[str, Iterable[dict]],
    expected_child_ids: dict[str, dict[str, str]],
    memory_logical_rows: Iterable[dict],
    parent_status_by_id: dict[str, str],
    report_logical_rows: Iterable[dict] = (),
    integration_rows: Iterable[dict] = (),
    expected_child_pages_by_kind: dict[str, dict[str, dict]] | None = None,
    expected_run_snapshot: dict | None = None,
    installation_snapshot: dict | None = None,
    authoritative_completed_memory_ids: Iterable[str] = (),
    explicit_setup: bool = False,
) -> list[str]:
    """Recheck every observational uniqueness boundary immediately before Run commit."""
    errors: list[str] = []

    def projection_rows(value: object, label: str) -> list[dict]:
        if isinstance(value, (str, bytes, bytearray, dict)):
            errors.append(f"{label} must be an iterable of row objects")
            return []
        try:
            return list(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            errors.append(f"{label} must be an iterable of row objects")
            return []

    if type(explicit_setup) is not bool:
        errors.append("explicit_setup must be a boolean")
    try:
        _parse_uuid(expected_run_page_id, "expected_run_page_id")
    except ValueError as exc:
        errors.append(str(exc))
    slot = projection_rows(slot_rows, "Slot snapshot")
    exact = projection_rows(exact_run_rows, "exact Run Key snapshot")
    operational_installation = installation_snapshot
    try:
        operational_installation = validate_operational_installation(
            installation_snapshot
        )
    except ValueError as exc:
        errors.append(f"Installation snapshot is invalid: {exc}")
    if isinstance(operational_installation, dict):
        if operational_installation.get("Enabled") is not True:
            errors.append("precommit requires an enabled Installation")
        if operational_installation.get("Status") in {"paused", "error"}:
            errors.append("precommit Installation status blocks commit")
    try:
        completion_ids = set(authoritative_completed_memory_ids)
    except TypeError:
        completion_ids = set()
        errors.append("authoritative completed Memory IDs must be iterable")
    for page_id in completion_ids:
        try:
            _parse_uuid(page_id, "authoritative completed Memory page ID")
        except ValueError as exc:
            errors.append(str(exc))
    if not isinstance(parent_status_by_id, dict):
        errors.append("parent status projection must be an object")
        parent_status_projection: dict[str, str] = {}
    else:
        parent_status_projection = dict(parent_status_by_id)
        for parent_id, status in parent_status_projection.items():
            try:
                _parse_uuid(parent_id, "parent status page ID")
            except ValueError as exc:
                errors.append(str(exc))
            if not isinstance(status, str) or status not in _RUN_STATUSES:
                errors.append("parent status value is invalid")
    parent_status_by_id = parent_status_projection

    def validate_run_identity(row: dict, label: str) -> None:
        slot_value = row.get("Slot Key")
        attempt_value = row.get("Attempt")
        if not isinstance(slot_value, str) or not slot_value:
            errors.append(f"{label} Slot Key is invalid")
        if not _strict_int(attempt_value, 1, 999):
            errors.append(f"{label} Attempt must be an integer from 1 through 999")
        if isinstance(slot_value, str) and slot_value and _strict_int(attempt_value, 1, 999):
            if row.get("Run Key") != run_key(slot_value, attempt_value):
                errors.append(f"{label} Run Key does not match Slot Key and Attempt")
        integration_value = row.get("Integration Key")
        if not isinstance(integration_value, str):
            errors.append(f"{label} Integration Key must be a string")
        elif integration_value and not _is_valid_integration_key(integration_value):
            errors.append(f"{label} Integration Key is invalid")

    expected_run = expected_run_snapshot if isinstance(expected_run_snapshot, dict) else {}
    if not isinstance(expected_run_snapshot, dict):
        errors.append("expected Run snapshot is required")
    missing_expected_run_fields = _EXPECTED_RUN_SNAPSHOT_FIELDS - set(expected_run)
    if missing_expected_run_fields:
        errors.append(
            "expected Run snapshot is incomplete: "
            + ", ".join(sorted(missing_expected_run_fields))
        )
    unexpected_expected_run_fields = set(expected_run) - _EXPECTED_RUN_SNAPSHOT_FIELDS
    if unexpected_expected_run_fields:
        errors.append(
            "expected Run snapshot has unexpected fields: "
            + ", ".join(sorted(unexpected_expected_run_fields))
        )
    parent_run_snapshot = {
        **expected_run,
        "page_id": expected_run_page_id,
    }
    if parent_status_by_id.get(expected_run_page_id) != expected_run.get("Status"):
        errors.append("parent status projection contradicts the current Run")
    errors.extend(
        f"expected Run snapshot: {error}"
        for error in _validate_parent_run_binding(
            parent_run_snapshot, operational_installation
        )
    )
    if expected_run.get("Status") != "preparing":
        errors.append("expected Run snapshot Status must be preparing")
    if expected_run.get("Output Prepared") is not True:
        errors.append("expected Run snapshot Output Prepared must be true")
    if expected_run.get("Cache Reconciled") is not False:
        errors.append(
            "expected Run snapshot Cache Reconciled must be false before commit"
        )
    if expected_run.get("Finished At") != "":
        errors.append(
            "expected Run snapshot Finished At must be empty while preparing"
        )
    validate_run_identity(expected_run, "expected Run snapshot")
    for property_name in _RUN_COUNT_FIELDS:
        if not _strict_int(expected_run.get(property_name), 0):
            errors.append(
                f"expected Run snapshot {property_name} must be a non-negative integer"
            )
    for property_name in _RUN_BOOLEAN_FIELDS:
        if not isinstance(expected_run.get(property_name), bool):
            errors.append(f"expected Run snapshot {property_name} must be a boolean")
    for property_name in _RUN_TIMESTAMP_FIELDS:
        value = expected_run.get(property_name)
        if (
            not isinstance(value, str)
            or (property_name != "Finished At" and not value)
            or (value and not _is_canonical_utc(value))
        ):
            errors.append(
                f"expected Run snapshot {property_name} must be canonical UTC"
                + (" or empty" if property_name == "Finished At" else "")
            )
    installation_value = expected_run.get("Installation")
    if not (
        isinstance(installation_value, list)
        and len(installation_value) == 1
        and isinstance(installation_value[0], str)
        and installation_value[0]
    ):
        errors.append("expected Run snapshot Installation must contain one page ID")
    expected_trigger = expected_run.get("Trigger")
    if not isinstance(expected_trigger, str) or expected_trigger not in _TRIGGERS:
        errors.append("expected Run snapshot Trigger is invalid")
    if explicit_setup is True and expected_trigger == "scheduled":
        errors.append("explicit_setup is invalid for a scheduled precommit")
    if (
        isinstance(operational_installation, dict)
        and operational_installation.get("Status") == "initializing"
        and (
            explicit_setup is not True
            or expected_trigger not in {"manual", "force-world-memory"}
        )
    ):
        errors.append(
            "initializing Installation precommit requires explicit direct setup"
        )
    expected_notification = expected_run.get("Notification Plan")
    if (
        not isinstance(expected_notification, str)
        or expected_notification not in _NOTIFICATION_PLANS
    ):
        errors.append("expected Run snapshot Notification Plan is invalid")
    if not isinstance(expected_run.get("Name"), str) or not expected_run.get("Name"):
        errors.append("expected Run snapshot Name must be a non-empty string")
    for property_name in ("Created At", "Updated At"):
        if (
            not isinstance(expected_run.get(property_name), str)
            or not expected_run.get(property_name)
        ):
            errors.append(
                f"expected Run snapshot {property_name} must be a non-empty string"
            )
    for property_name in ("Input Digest", "Output Digest", "Error Summary"):
        if not isinstance(expected_run.get(property_name), str):
            errors.append(f"expected Run snapshot {property_name} must be a string")
    if not isinstance(expected_run.get("body"), str) or not expected_run.get("body"):
        errors.append("expected Run snapshot body must be a non-empty string")
    run_audit_payload: dict | None = None
    if isinstance(expected_run.get("body"), str) and expected_run.get("body"):
        try:
            decoded_audit, decoded_rendering = decode_notion_body(expected_run["body"])
        except (TypeError, ValueError) as exc:
            errors.append(f"expected Run audit body is invalid: {exc}")
        else:
            if decoded_rendering != "":
                errors.append("expected Run audit body must not contain rendering")
            audit_errors = validate_audit(decoded_audit)
            errors.extend(f"expected Run audit: {error}" for error in audit_errors)
            if not audit_errors:
                run_audit_payload = decoded_audit
                if decoded_audit.get("trigger") != expected_run.get("Trigger"):
                    errors.append("expected Run audit trigger does not match Run Trigger")

    def compare_to_expected_run(row: dict, label: str) -> None:
        if set(row) != _OBSERVED_RUN_SNAPSHOT_FIELDS:
            errors.append(f"{label} must contain exactly every Run snapshot field")
        if row.get("page_id") != expected_run_page_id:
            errors.append(f"{label} page_id changed before commit")
        for property_name in sorted(_EXPECTED_RUN_SNAPSHOT_FIELDS):
            if property_name not in row:
                errors.append(f"{label} {property_name} was not fully observed")
            elif property_name in expected_run and not _exact_json_equal(
                row.get(property_name), expected_run[property_name]
            ):
                errors.append(f"{label} {property_name} changed before commit")

    current_slot = [row for row in slot if isinstance(row, dict) and row.get("page_id") == expected_run_page_id]
    if len(current_slot) != 1:
        errors.append("Slot snapshot must contain the current Run exactly once")
    elif current_slot[0].get("Status") != "preparing":
        errors.append("current Slot Run is no longer preparing")
    if len(current_slot) == 1:
        validate_run_identity(current_slot[0], "current Slot Run")
        compare_to_expected_run(current_slot[0], "current Slot Run")
    for row in slot:
        if not isinstance(row, dict):
            errors.append("Slot snapshot row must be an object")
            continue
        if row.get("page_id") == expected_run_page_id:
            continue
        status = row.get("Status")
        if not isinstance(status, str):
            errors.append("Slot snapshot Run status is invalid")
        elif status not in _TERMINAL_RUN_STATUSES:
            errors.append("Slot snapshot contains another active Run")
    if len(exact) != 1 or not isinstance(exact[0], dict) or exact[0].get("page_id") != expected_run_page_id:
        errors.append("exact Run Key snapshot must contain only the current Run")
    else:
        validate_run_identity(exact[0], "current exact Run")
        compare_to_expected_run(exact[0], "current exact Run")
    if (
        len(exact) == 1
        and isinstance(exact[0], dict)
        and exact[0].get("page_id") == expected_run_page_id
        and len(current_slot) == 1
    ):
        if exact[0].get("Status") != "preparing":
            errors.append("current Run is no longer preparing")
        for property_name in _RUN_SNAPSHOT_FIELDS:
            if property_name not in exact[0] or property_name not in current_slot[0]:
                errors.append(f"current Run {property_name} was not fully observed before commit")
            elif not _exact_json_equal(
                exact[0].get(property_name), current_slot[0].get(property_name)
            ):
                errors.append(f"current Run {property_name} changed before commit")

    if not isinstance(child_rows_by_kind, dict) or not isinstance(expected_child_ids, dict):
        return errors + ["child snapshots and expectations must be objects"]
    required_child_kinds = set(_OPERATIONAL_CHILD_FIELDS)
    if set(child_rows_by_kind) != required_child_kinds:
        errors.append(
            "child row projections must contain exactly feed, memory, and report"
        )
    if set(expected_child_ids) != required_child_kinds:
        errors.append(
            "expected child ID projections must contain exactly feed, memory, and report"
        )
    if expected_child_pages_by_kind is None:
        expected_page_snapshots: dict[str, dict[str, dict]] = {}
        if any(
            isinstance(mapping, dict) and mapping
            for mapping in expected_child_ids.values()
        ):
            errors.append("expected child page snapshots are required for expected children")
    elif not isinstance(expected_child_pages_by_kind, dict):
        expected_page_snapshots = {}
        errors.append("expected child page snapshots must be an object")
    else:
        expected_page_snapshots = expected_child_pages_by_kind
    if set(expected_page_snapshots) != required_child_kinds:
        errors.append(
            "expected child page projections must contain exactly feed, memory, and report"
        )
    if set(expected_page_snapshots) != set(expected_child_ids):
        errors.append("expected child page snapshot kinds do not match expected child IDs")
    child_snapshots = {
        kind: projection_rows(rows, f"{kind} child rows")
        for kind, rows in child_rows_by_kind.items()
    }
    if (
        isinstance(operational_installation, dict)
        and operational_installation.get("Autopilot Enabled") is False
    ):
        expected_memory_ids = expected_child_ids.get("memory", {})
        expected_memory_pages = expected_page_snapshots.get("memory", {})
        if (
            child_snapshots.get("memory")
            or (isinstance(expected_memory_ids, dict) and expected_memory_ids)
            or (isinstance(expected_memory_pages, dict) and expected_memory_pages)
        ):
            errors.append(
                "Autopilot-disabled precommit must not contain Memory children"
            )
        if completion_ids:
            errors.append(
                "Autopilot-disabled precommit must not complete suggestions"
            )
    validated_feed_groups: list[tuple[list[dict], list[dict]]] = []
    for kind in sorted(
        set(child_snapshots) | set(expected_child_ids) | set(expected_page_snapshots)
    ):
        rows = child_snapshots.get(kind, [])
        expected_mapping = expected_child_ids.get(kind, {})
        if not isinstance(expected_mapping, dict):
            errors.append(f"{kind} expected child mapping must be an object")
            continue
        expected_pages = expected_page_snapshots.get(kind, {})
        if not isinstance(expected_pages, dict):
            errors.append(f"{kind} expected child page snapshots must be an object")
            expected_pages = {}
        if set(expected_pages) != set(expected_mapping):
            errors.append(f"{kind} expected child page snapshot keys do not match child IDs")
        if kind not in _OPERATIONAL_CHILD_FIELDS:
            errors.append(f"{kind} is not a supported child kind")
        if any(
            not isinstance(page_id, str) or not page_id
            for page_id in expected_mapping.values()
        ):
            errors.append(f"{kind} expected child page IDs must be non-empty strings")
        errors.extend(
            f"{kind}: {error}"
            for error in verify_child_set(set(expected_mapping), rows, expected_run_page_id)
        )
        actual_mapping: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            fields = [field for field in _PHYSICAL_KEY_FIELDS if field in row]
            if len(fields) == 1 and isinstance(row.get(fields[0]), str) and isinstance(row.get("page_id"), str):
                actual_mapping[row[fields[0]]] = row["page_id"]
        if actual_mapping != expected_mapping:
            errors.append(f"{kind}: child page IDs changed before commit")
        if kind not in _OPERATIONAL_CHILD_FIELDS:
            continue
        physical_field = {
            "feed": "Batch Key", "memory": "Revision Key", "report": "Report Key",
        }[kind]
        validated_feed_rows: list[dict] = []
        for physical_key, page_id in expected_mapping.items():
            expected_page = expected_pages.get(physical_key)
            if not isinstance(expected_page, dict):
                errors.append(f"{kind} {physical_key!r}: expected child page snapshot is missing")
                continue
            expected_fields = _OPERATIONAL_CHILD_FIELDS[kind]
            missing_fields = expected_fields - set(expected_page)
            unexpected_fields = set(expected_page) - expected_fields
            if missing_fields or unexpected_fields:
                errors.append(
                    f"{kind} {physical_key!r}: expected child page snapshot fields are not exact"
                )
                continue
            matches = [
                row for row in rows
                if isinstance(row, dict)
                and row.get(physical_field) == physical_key
                and row.get("page_id") == page_id
            ]
            if len(matches) != 1:
                continue
            row = matches[0]
            errors.extend(
                f"{kind} {physical_key!r}: {error}"
                for error in validate_child_page(
                    kind,
                    row,
                    expected_page,
                    parent_run_snapshot,
                    operational_installation,
                    authoritative_completion=page_id in completion_ids,
                )
            )
            if kind == "feed" and isinstance(expected_page.get("payload"), dict):
                validated_feed_rows.append({**row, "payload": expected_page["payload"]})
        if kind == "feed" and validated_feed_rows:
            groups, feed_group_errors = _validated_complete_feed_groups(
                validated_feed_rows
            )
            validated_feed_groups.extend(groups)
            errors.extend(f"feed: {error}" for error in feed_group_errors)

    expected_inventory: dict[str, list[dict]] = {
        "feed": [], "memory": [], "report": [],
    }
    for kind in ("feed", "memory", "report"):
        expected_pages = expected_page_snapshots.get(kind, {})
        if not isinstance(expected_pages, dict):
            continue
        for physical_key in sorted(expected_pages):
            page = expected_pages[physical_key]
            if not isinstance(page, dict):
                continue
            entry = {
                "key": physical_key,
                "pageId": page.get("page_id"),
                "payloadDigest": page.get("Payload Digest"),
            }
            if kind == "feed":
                entry["fingerprintWindowDigest"] = page.get(
                    "Fingerprint Window Digest"
                )
            elif kind == "report":
                entry["renderingDigest"] = page.get("Rendering Digest")
            expected_inventory[kind].append(entry)
    if run_audit_payload is not None:
        observed_inventory = run_audit_payload["audit"]["expectedChildren"]
        if not _exact_json_equal(observed_inventory, expected_inventory):
            errors.append("expected Run audit child inventory does not match snapshots")

    report_pages = expected_page_snapshots.get("report", {})
    all_reports = [
        page for page in report_pages.values() if isinstance(page, dict)
    ] if isinstance(report_pages, dict) else []
    six_hour_reports = [
        page
        for page in all_reports
        if page.get("Report Type") == "six-hour"
    ]
    hourly_reports = [
        page
        for page in all_reports
        if page.get("Report Type") == "hourly-briefing"
    ]
    integration_due = expected_run.get("Integration Due")
    integration_performed = expected_run.get("Integration Performed")
    integration_value = expected_run.get("Integration Key")
    notification_plan = expected_run.get("Notification Plan")
    material_change = expected_run.get("Material Change")
    if (
        expected_trigger == "force-world-memory"
        and integration_performed is not True
    ):
        errors.append(
            "force-world-memory precommit requires a performed integration"
        )
    if (
        type(integration_due) is bool
        and type(integration_performed) is bool
        and integration_due != integration_performed
    ):
        errors.append("Integration Due must equal Integration Performed at precommit")
    if integration_performed is True:
        if not isinstance(integration_value, str) or not integration_value:
            errors.append(
                "Integration Performed requires a non-empty Integration Key"
            )
        if len(six_hour_reports) != 1:
            errors.append(
                "Integration Performed requires exactly one six-hour Report"
            )
        elif six_hour_reports[0].get("Integration Key") != integration_value:
            errors.append(
                "six-hour Report Integration Key must match the performed integration"
            )
        if notification_plan != "six-hour":
            errors.append(
                "Integration Performed requires the six-hour notification plan"
            )
        if hourly_reports or len(all_reports) != 1:
            errors.append(
                "six-hour precommit requires exactly one Report and no hourly Report"
            )
    elif integration_performed is False:
        if integration_value != "":
            errors.append(
                "non-integration precommit Run Integration Key must be empty"
            )
        if six_hour_reports:
            errors.append(
                "six-hour Report requires Integration Performed"
            )
        if notification_plan == "six-hour":
            errors.append(
                "six-hour notification requires Integration Performed"
            )
        if material_change is True:
            if notification_plan != "hourly-briefing":
                errors.append(
                    "material non-integration precommit requires hourly-briefing notification"
                )
            if len(hourly_reports) != 1 or len(all_reports) != 1:
                errors.append(
                    "material non-integration precommit requires exactly one hourly Report"
                )
        elif material_change is False:
            if notification_plan != "silent":
                errors.append(
                    "non-material precommit requires a silent notification plan"
                )
            if all_reports:
                errors.append("non-material precommit must not contain Reports")

    if not child_snapshots.get("feed"):
        errors.append("precommit requires at least one Feed Batch child")
    success_count = expected_run.get("Feed Success Count")
    failure_count = expected_run.get("Feed Failure Count")
    if (
        _strict_int(success_count, 0)
        and _strict_int(failure_count, 0)
        and success_count + failure_count != len(_CONFIGURED_FEED_IDS)
    ):
        errors.append("Run Feed Success Count plus Failure Count must equal five")
    if _strict_int(success_count, 0) and success_count < 1:
        errors.append("precommit requires at least one successful feed source")
    if len(validated_feed_groups) != 1:
        errors.append("precommit requires exactly one complete Feed Batch group")
    else:
        _feed_rows, payloads = validated_feed_groups[0]
        first_payload = payloads[0]
        outcomes = first_payload.get("sourceOutcomes", [])
        observed_success = sum(
            outcome.get("status") == "ok"
            for outcome in outcomes
            if isinstance(outcome, dict)
        )
        observed_failure = sum(
            outcome.get("status") == "error"
            for outcome in outcomes
            if isinstance(outcome, dict)
        )
        for property_name, observed in (
            ("Feed Success Count", observed_success),
            ("Feed Failure Count", observed_failure),
            ("New Item Count", first_payload.get("newItemCount")),
        ):
            if not _exact_json_equal(expected_run.get(property_name), observed):
                errors.append(f"Run {property_name} does not match Feed Batch group")
        if run_audit_payload is not None:
            audit_feed = run_audit_payload.get("feed")
            expected_audit_feed = {
                "sourceOutcomes": outcomes,
                "successCount": observed_success,
                "failureCount": observed_failure,
                "newItemCount": first_payload.get("newItemCount"),
            }
            for field, observed in expected_audit_feed.items():
                if not isinstance(audit_feed, dict) or not _exact_json_equal(
                    audit_feed.get(field), observed
                ):
                    errors.append(
                        f"expected Run audit feed {field} does not match Feed Batch group"
                    )

    memory_expected: dict[str, tuple[str, int]] = {}
    memory_mapping = expected_child_ids.get("memory", {})
    if isinstance(memory_mapping, dict):
        memory_children = child_snapshots.get("memory", [])
        for physical_key, page_id in memory_mapping.items():
            if not isinstance(physical_key, str) or not isinstance(page_id, str) or not page_id:
                continue
            matches = [
                row for row in memory_children
                if isinstance(row, dict)
                and row.get("Revision Key") == physical_key
                and row.get("page_id") == page_id
            ]
            if len(matches) != 1:
                continue
            row = matches[0]
            record = row.get("Record Key")
            revision = row.get("Revision")
            canonical_prefix = (
                f"{record}:r{revision:06d}:"
                if isinstance(record, str)
                and record
                and _strict_int(revision, 1, 999999)
                else None
            )
            if (
                not isinstance(physical_key, str)
                or canonical_prefix is None
                or not physical_key.startswith(canonical_prefix)
                or physical_key == canonical_prefix
            ):
                errors.append("memory: expected child logical identity is malformed")
                continue
            memory_expected[page_id] = (record, revision)

    report_mapping = expected_child_ids.get("report", {})
    six_hour_report_expected: dict[str, str] = {}
    if isinstance(report_mapping, dict):
        report_children = child_snapshots.get("report", [])
        for physical_key, page_id in report_mapping.items():
            if (
                not isinstance(physical_key, str)
                or not isinstance(page_id, str)
                or not page_id
                or ":report:six-hour:" not in physical_key
            ):
                continue
            matches = [
                row for row in report_children
                if isinstance(row, dict)
                and row.get("Report Key") == physical_key
                and row.get("page_id") == page_id
            ]
            if len(matches) != 1:
                continue
            integration_value = matches[0].get("Integration Key")
            physical_prefix = f"{integration_value}:report:six-hour:"
            if (
                not _is_valid_integration_key(integration_value)
                or not physical_key.startswith(physical_prefix)
                or physical_key == physical_prefix
            ):
                errors.append("report: expected child logical identity is malformed")
                continue
            six_hour_report_expected[page_id] = integration_value

    def require_current_logical_rows(
        rows: list[dict], expected_identities: dict[str, object], label: str
    ) -> None:
        for page_id in sorted(expected_identities):
            matches = [row for row in rows if isinstance(row, dict) and row.get("page_id") == page_id]
            if len(matches) != 1:
                errors.append(f"logical {label} snapshot must contain current page {page_id} exactly once")
                continue
            if matches[0].get("Run") != [expected_run_page_id]:
                errors.append(f"logical {label} current page has the wrong Run parent")
            expected_identity = expected_identities[page_id]
            actual_identity = logical_identity(matches[0], label)
            if actual_identity is None:
                errors.append(f"logical {label} current page identity is malformed")
            if actual_identity != expected_identity:
                errors.append(f"logical {label} current page identity changed before commit")

    memory_rows = projection_rows(memory_logical_rows, "Memory logical snapshot")
    report_rows = projection_rows(report_logical_rows, "Report logical snapshot")

    def logical_identity(row: dict, label: str) -> object | None:
        if label == "Memory":
            record_value = row.get("Record Key")
            revision_value = row.get("Revision")
            if (
                not isinstance(record_value, str)
                or not record_value
                or not _strict_int(revision_value, 1, 999999)
            ):
                return None
            return record_value, revision_value
        integration_value = row.get("Integration Key")
        return integration_value if _is_valid_integration_key(integration_value) else None

    require_current_logical_rows(memory_rows, memory_expected, "Memory")
    require_current_logical_rows(report_rows, six_hour_report_expected, "Report")

    for page_id, (record, revision) in memory_expected.items():
        current_matches = [
            row for row in memory_rows
            if isinstance(row, dict) and row.get("page_id") == page_id
        ]
        if len(current_matches) != 1:
            continue
        current = current_matches[0]
        if revision == 1:
            if current.get("Supersedes") != []:
                errors.append("Memory revision 1 must not have a predecessor")
            continue
        relation = current.get("Supersedes")
        logical_predecessors = [
            row
            for row in memory_rows
            if isinstance(row, dict)
            and row.get("Record Key") == record
            and _strict_int(row.get("Revision"), 1, 999999)
            and row.get("Revision") == revision - 1
        ]
        committed_predecessors: list[dict] = []
        for predecessor in logical_predecessors:
            try:
                _parse_uuid(
                    predecessor.get("page_id"), "Memory predecessor page_id"
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
            predecessor_parent = _single_parent_id(predecessor, errors=errors)
            if (
                predecessor_parent is not None
                and parent_status_by_id.get(predecessor_parent) == "committed"
            ):
                committed_predecessors.append(predecessor)
        if len(committed_predecessors) != 1:
            errors.append(
                "Memory successor requires exactly one committed logical predecessor"
            )
            continue
        predecessor_id = committed_predecessors[0].get("page_id")
        if relation != [predecessor_id]:
            errors.append(
                "Memory successor Supersedes must name the exact logical predecessor"
            )

    current_memory_ids = set(memory_expected)
    report_expected_pages = expected_page_snapshots.get("report", {})
    if isinstance(report_expected_pages, dict):
        for report_page_snapshot in report_expected_pages.values():
            if not isinstance(report_page_snapshot, dict):
                continue
            evidence_ids = report_page_snapshot.get("Evidence Records")
            if not isinstance(evidence_ids, list):
                continue
            for evidence_id in evidence_ids:
                if evidence_id in current_memory_ids:
                    continue
                evidence_matches = [
                    row for row in memory_rows
                    if isinstance(row, dict) and row.get("page_id") == evidence_id
                ]
                if len(evidence_matches) != 1:
                    errors.append(
                        "Report evidence must resolve to exactly one Memory row"
                    )
                    continue
                evidence_row = evidence_matches[0]
                if logical_identity(evidence_row, "Memory") is None:
                    errors.append("Report evidence Memory identity is malformed")
                evidence_parent = _single_parent_id(evidence_row, errors=errors)
                if (
                    evidence_parent is None
                    or parent_status_by_id.get(evidence_parent) != "committed"
                ):
                    errors.append(
                        "Report evidence must belong to a committed prior Run"
                    )

    def check_logical_rows(
        rows: Iterable[dict], label: str, expected_identities: dict[str, object]
    ) -> None:
        for row in rows:
            if not isinstance(row, dict):
                errors.append(f"{label} logical row must be an object")
                continue
            page_id = row.get("page_id")
            expected_identity = expected_identities.get(page_id) if isinstance(page_id, str) else None
            actual_identity = logical_identity(row, label)
            if (
                expected_identity is not None
                and actual_identity == expected_identity
                and row.get("Run") == [expected_run_page_id]
            ):
                continue
            parent_id = _single_parent_id(row, errors=errors)
            if parent_id is None:
                continue
            status = parent_status_by_id.get(parent_id)
            if not isinstance(status, str):
                errors.append(f"logical {label} parent status is unknown")
            elif status in _TERMINAL_RUN_STATUSES:
                continue
            elif status == "committed":
                if actual_identity is None:
                    errors.append(
                        f"committed logical {label} identity is malformed"
                    )
                elif actual_identity not in set(expected_identities.values()):
                    continue
                else:
                    errors.append(
                        f"another active parent owns logical {label} identity"
                    )
            elif status in {"preparing", "committed"}:
                errors.append(f"another active parent owns logical {label} identity")
            else:
                errors.append(f"logical {label} parent status is unknown")

    check_logical_rows(memory_rows, "Memory", memory_expected)
    check_logical_rows(report_rows, "Report", six_hour_report_expected)
    integration = projection_rows(integration_rows, "Integration snapshot")
    current_integration_key = exact[0].get("Integration Key") if len(exact) == 1 and isinstance(exact[0], dict) else None
    if isinstance(current_integration_key, str) and current_integration_key:
        current_integration_rows = [
            row for row in integration
            if isinstance(row, dict) and row.get("page_id") == expected_run_page_id
        ]
        if len(current_integration_rows) != 1:
            errors.append("Integration snapshot must contain the current Run exactly once")
        else:
            current_integration = current_integration_rows[0]
            if current_integration.get("Status") != "preparing":
                errors.append("current Integration Run is no longer preparing")
            if not _is_valid_integration_key(current_integration.get("Integration Key")):
                errors.append("current Integration Run identity is invalid")
            if len(exact) == 1 and isinstance(exact[0], dict):
                for property_name in _RUN_SNAPSHOT_FIELDS:
                    if property_name not in current_integration:
                        errors.append(
                            f"current Integration Run {property_name} was not fully observed"
                        )
                    elif not _exact_json_equal(
                        current_integration.get(property_name),
                        exact[0].get(property_name),
                    ):
                        errors.append(
                            f"current Integration Run {property_name} changed before commit"
                        )
            validate_run_identity(current_integration, "current Integration Run")
            compare_to_expected_run(current_integration, "current Integration Run")
    elif integration:
        errors.append("non-integration Run received an Integration snapshot")
    for row in integration:
        if not isinstance(row, dict):
            errors.append("Integration snapshot row must be an object")
            continue
        if row.get("page_id") == expected_run_page_id:
            continue
        status = row.get("Status")
        if not isinstance(status, str):
            errors.append("Integration Run status is unknown")
        elif status in _TERMINAL_RUN_STATUSES:
            continue
        elif status in {"preparing", "committed"}:
            errors.append("another active Run owns the Integration Key")
        else:
            errors.append("Integration Run status is unknown")
    return errors


_RUN_SUPERSESSION_BUNDLE_KEYS = frozenset({
    "explicitApproval",
    "invocation",
    "installation",
    "targetRun",
    "slotRows",
    "exactRunRows",
    "authoritativeRuns",
    "feedRows",
    "memoryRows",
    "reportRows",
})


def _blocked_supersession(errors: Iterable[str]) -> dict:
    return {"action": "blocked", "errors": list(dict.fromkeys(errors))}


def plan_run_supersession(bundle: object) -> dict:
    """Plan one direct-approved, status-only corrupt Run supersession."""
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return _blocked_supersession(["repair bundle must be an object"])
    if set(bundle) != _RUN_SUPERSESSION_BUNDLE_KEYS:
        errors.append("repair bundle keys are not exact")
    if bundle.get("explicitApproval") is not True:
        errors.append("explicit direct user approval is required")
    if bundle.get("invocation") != "manual":
        errors.append("Run supersession recovery is direct manual only")

    installation = bundle.get("installation")
    try:
        validated_installation = validate_operational_installation(installation)
    except ValueError as exc:
        errors.append(f"Installation snapshot is invalid: {exc}")
        validated_installation = None

    target = bundle.get("targetRun")
    if not isinstance(target, dict):
        errors.append("target Run must be an object")
        return _blocked_supersession(errors)
    if set(target) != _OBSERVED_RUN_SNAPSHOT_FIELDS:
        errors.append("target Run must contain exactly every Run snapshot field")
    try:
        target_page_id = _parse_uuid(target.get("page_id"), "target Run page_id")
    except ValueError as exc:
        errors.append(str(exc))
        target_page_id = None
    if validated_installation is not None:
        errors.extend(_validate_parent_run_binding(target, validated_installation))

    required_target = {
        "Status": "committed",
        "Integration Key": "",
        "Material Change": False,
        "Integration Due": False,
        "Integration Performed": False,
        "Output Prepared": True,
        "Cache Reconciled": False,
        "Notification Plan": "silent",
    }
    for field, wanted in required_target.items():
        if not _exact_json_equal(target.get(field), wanted):
            errors.append(f"target Run {field} is not eligible")
    if not _is_canonical_utc(target.get("Finished At")):
        errors.append("target Run Finished At must be nonempty canonical UTC")

    projections: dict[str, list] = {}
    for field in (
        "slotRows",
        "exactRunRows",
        "authoritativeRuns",
        "feedRows",
        "memoryRows",
        "reportRows",
    ):
        value = bundle.get(field)
        if not isinstance(value, list):
            errors.append(f"{field} must be a list")
            projections[field] = []
        else:
            projections[field] = value

    for field in ("slotRows", "exactRunRows"):
        rows = projections[field]
        if len(rows) != 1 or not isinstance(rows[0], dict):
            errors.append(f"{field} must contain the target Run exactly once")
        elif not _exact_json_equal(rows[0], target):
            errors.append(f"{field} target Run snapshot changed")

    authority = projections["authoritativeRuns"]
    target_matches = [
        row for row in authority
        if isinstance(row, dict)
        and row.get("page_id") == target_page_id
        and row.get("Run Key") == target.get("Run Key")
    ]
    if len(target_matches) != 1 or not _exact_json_equal(target_matches[0], target):
        errors.append("authoritativeRuns must contain the exact target once")
    seen_run_keys: set[str] = set()
    target_order: tuple[datetime, str] | None = None
    try:
        target_order = (
            _aware_datetime(target.get("Collection Cutoff"), "target Collection Cutoff"),
            target.get("Run Key"),
        )
    except ValueError as exc:
        errors.append(str(exc))
    if target_order is not None and not isinstance(target_order[1], str):
        errors.append("target Run Key must be a string")
        target_order = None
    for index, row in enumerate(authority):
        if not isinstance(row, dict):
            errors.append(f"authoritativeRuns[{index}] must be an object")
            continue
        run_key_value = row.get("Run Key")
        if not isinstance(run_key_value, str) or not run_key_value:
            errors.append(f"authoritativeRuns[{index}].Run Key is invalid")
            continue
        if run_key_value in seen_run_keys:
            errors.append(f"duplicate Run Key in authority: {run_key_value}")
        seen_run_keys.add(run_key_value)
        status = row.get("Status")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            errors.append(f"authoritativeRuns[{index}].Status is invalid")
            continue
        try:
            row_order = (
                _aware_datetime(
                    row.get("Collection Cutoff"),
                    f"authoritativeRuns[{index}].Collection Cutoff",
                ),
                run_key_value,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if (
            target_order is not None
            and row.get("page_id") != target_page_id
            and status in {"preparing", "committed"}
            and row_order > target_order
        ):
            errors.append("a later preparing or committed Run blocks repair")

    feed_rows = projections["feedRows"]
    if len(feed_rows) != 1 or not isinstance(feed_rows[0], dict):
        errors.append("repair requires exactly one Feed Batch row")
        feed = None
    else:
        feed = feed_rows[0]
    if projections["memoryRows"]:
        errors.append("target Run must not have Memory children")
    if projections["reportRows"]:
        errors.append("target Run must not have Report children")

    audit_payload = None
    try:
        decoded_audit, audit_rendering = decode_notion_body(target.get("body"))
    except (TypeError, ValueError) as exc:
        errors.append(f"target Run body is invalid: {exc}")
    else:
        if audit_rendering:
            errors.append("target Run body must not have rendering")
        audit_errors = validate_audit(decoded_audit)
        errors.extend(f"target Run audit: {error}" for error in audit_errors)
        if not audit_errors:
            audit_payload = decoded_audit

    if feed is not None:
        if set(feed) != _OPERATIONAL_CHILD_FIELDS["feed"]:
            errors.append("Feed Batch must contain exactly every Feed snapshot field")
        if feed.get("Run") != [target_page_id]:
            errors.append("Feed Batch Run relation does not match target")
        if feed.get("Run Key") != target.get("Run Key"):
            errors.append("Feed Batch Run Key does not match target")
        if feed.get("Part Index") != 1 or feed.get("Part Count") != 1:
            errors.append("repair supports only one single-part Feed Batch")
        payload, feed_errors = _valid_batch_payload(feed)
        allowed_mismatch = "batch Fetched At mismatch"
        unexpected_feed_errors = [
            error for error in feed_errors if error != allowed_mismatch
        ]
        errors.extend(f"Feed Batch: {error}" for error in unexpected_feed_errors)
        if feed_errors.count(allowed_mismatch) != 1:
            errors.append("Feed Batch must have exactly one Fetched At mismatch")
        if feed.get("Fetched At") != target.get("Collection Cutoff"):
            errors.append("Feed Batch physical Fetched At must equal parent cutoff")
        if isinstance(payload, dict):
            if payload.get("fetchedAt") == feed.get("Fetched At"):
                errors.append("Feed Batch property and payload Fetched At must differ")
            if target.get("Feed Success Count") != feed.get("Feed Success Count"):
                errors.append("target Feed Success Count mismatch")
            if target.get("Feed Failure Count") != feed.get("Feed Failure Count"):
                errors.append("target Feed Failure Count mismatch")
            if target.get("New Item Count") != feed.get("New Item Count"):
                errors.append("target New Item Count mismatch")
        if audit_payload is not None:
            inventory = audit_payload.get("audit", {}).get("expectedChildren")
            expected_inventory = {
                "feed": [{
                    "key": feed.get("Batch Key"),
                    "pageId": feed.get("page_id"),
                    "payloadDigest": feed.get("Payload Digest"),
                    "fingerprintWindowDigest": feed.get("Fingerprint Window Digest"),
                }],
                "memory": [],
                "report": [],
            }
            if not _exact_json_equal(inventory, expected_inventory):
                errors.append("target Run audit child inventory mismatch")
            audit_feed = audit_payload.get("feed")
            if isinstance(payload, dict):
                expected_audit_feed = {
                    "sourceOutcomes": payload.get("sourceOutcomes"),
                    "successCount": feed.get("Feed Success Count"),
                    "failureCount": feed.get("Feed Failure Count"),
                    "newItemCount": feed.get("New Item Count"),
                }
                if not isinstance(audit_feed, dict) or any(
                    not _exact_json_equal(audit_feed.get(key), value)
                    for key, value in expected_audit_feed.items()
                ):
                    errors.append("target Run audit feed facts mismatch")

    if errors:
        return _blocked_supersession(errors)
    return {
        "action": "supersede-run",
        "reason": "feed-fetched-at-property-payload-mismatch",
        "runPageId": target_page_id,
        "runKey": target["Run Key"],
        "expectedStatus": "committed",
        "nextStatus": "superseded",
        "propertyUpdates": {"Status": "superseded"},
        "cacheRepairRequired": True,
    }


def verify_run_supersession_readback(
    before: object,
    after: object,
    feed_before: object,
    feed_after: object,
) -> list[str]:
    """Verify that a confirmed supersession changed only Run authority state."""
    errors: list[str] = []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ["Run read-back snapshots must be objects"]
    if (
        set(before) != _OBSERVED_RUN_SNAPSHOT_FIELDS
        or set(after) != _OBSERVED_RUN_SNAPSHOT_FIELDS
    ):
        errors.append("Run read-back snapshots must contain exact fields")
    if before.get("Status") != "committed":
        errors.append("pre-repair Run Status must be committed")
    if after.get("Status") != "superseded":
        errors.append("post-repair Run Status must be superseded")
    for field in sorted(_OBSERVED_RUN_SNAPSHOT_FIELDS - {"Status", "Updated At"}):
        if not _exact_json_equal(before.get(field), after.get(field)):
            errors.append(f"Run {field} changed during supersession")
    if before.get("page_id") != after.get("page_id"):
        errors.append("Run page_id changed during supersession")
    if not _is_notion_utc(after.get("Updated At")):
        errors.append("post-repair Run Updated At must be an observed Notion UTC timestamp")
    if not isinstance(feed_before, dict) or not isinstance(feed_after, dict):
        errors.append("Feed read-back snapshots must be objects")
    elif not _exact_json_equal(feed_before, feed_after):
        errors.append("Feed Batch changed during Run supersession")
    return errors
