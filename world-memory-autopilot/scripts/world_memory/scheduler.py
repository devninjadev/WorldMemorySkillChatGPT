"""Pure installation policy, integration clock, and cache repair contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Iterable, Literal
from urllib.parse import urlsplit
from uuid import UUID

from .contracts import CONFIGURED_SOURCES


TRIGGERS = frozenset({"scheduled", "manual", "force-world-memory"})
Trigger = Literal["scheduled", "manual", "force-world-memory"]
_STATUSES = frozenset({"initializing", "active", "paused", "error"})
_RUN_STATUSES = frozenset({"preparing", "committed", "failed", "superseded"})
_NOTIFICATION_PLANS = frozenset({"silent", "hourly-briefing", "six-hour", "error"})
_INTERNAL_INTEGRATION_GATE = timedelta(hours=5, minutes=45)
_FEED_IDS = tuple(source[0] for source in CONFIGURED_SOURCES)
_OUTCOME_KEYS = frozenset({"status", "itemCount", "cursor", "error"})
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_NOTION_UTC = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z"
)
_INTEGRATION_KEY = re.compile(
    r"wmi_([0-9a-f]{12})_(genesis|previous-cutoff-(\d{8}T\d{6}Z))"
)
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_INSTALLATION_CACHE_TIMES = (
    "Last Feed Attempt",
    "Last Feed Success",
    "Last World Memory Success",
    "Last Report Success",
    "Next World Memory At",
    "Last Briefing At",
)
_INSTALLATION_REQUIRED_FIELDS = frozenset({
    "page_id", "Name", "Installation Key", "Hub Page ID", "Hub URL", "Status",
    "Enabled", "Autopilot Enabled", "Timezone", "Hourly Interval Minutes",
    "World Memory Interval Hours", "Schema Version", "Skill Contract Version",
    "Feed Cursor State", *_INSTALLATION_CACHE_TIMES, "Last Error", "Created At",
    "Updated At",
})


def _aware_utc(value: datetime, description: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{description} must be timezone-aware")
    return value.astimezone(timezone.utc)


def parse_utc(value: str) -> datetime:
    """Parse a timezone-aware ISO instant and normalize it to UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty ISO string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"invalid ISO timestamp: {value}") from exc
    return _aware_utc(parsed, "timestamp")


def utc_iso(value: datetime) -> str:
    """Serialize a timezone-aware instant as canonical second-precision UTC."""
    return _aware_utc(value, "timestamp").isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_utc(value: object, description: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise ValueError(f"{description} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{description} must be canonical UTC") from exc
    if utc_iso(parsed) != value:
        raise ValueError(f"{description} must be canonical UTC")
    return value


def normalize_trigger(value: str) -> Trigger:
    if not isinstance(value, str):
        raise ValueError("trigger must be a string")
    normalized = value.strip().lower()
    if normalized not in TRIGGERS:
        raise ValueError(f"unsupported trigger: {value}")
    return normalized  # type: ignore[return-value]


def _uuid(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{description} must be a UUID string")
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{description} must be a UUID string") from exc
    return value


def _notion_timestamp(value: object, description: str) -> str:
    if not isinstance(value, str) or _NOTION_UTC.fullmatch(value) is None:
        raise ValueError(f"{description} must be a non-empty UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{description} must be a non-empty UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{description} must be a non-empty UTC timestamp")
    return value


def validate_operational_installation(installation: object) -> dict:
    """Validate one fully observed operational Installation row."""
    if not isinstance(installation, dict):
        raise ValueError("installation must be an object")
    missing = _INSTALLATION_REQUIRED_FIELDS - set(installation)
    if missing:
        raise ValueError(
            "Installation row is incomplete: " + ", ".join(sorted(missing))
        )
    unexpected = set(installation) - (_INSTALLATION_REQUIRED_FIELDS | {"Runs"})
    if unexpected:
        raise ValueError(
            "Installation row has unexpected fields: "
            + ", ".join(sorted(unexpected))
        )
    page_id = _uuid(installation.get("page_id"), "page_id")
    hub_page_id = _uuid(installation.get("Hub Page ID"), "Hub Page ID")
    key = installation.get("Installation Key")
    if not isinstance(key, str):
        raise ValueError("Installation Key must be a string")
    match = re.fullmatch(r"wm:([0-9a-fA-F-]{36}):default", key)
    if match is None:
        raise ValueError("Installation Key must be wm:<workspace-uuid>:default")
    workspace_id = _uuid(match.group(1), "Installation Key workspace ID")
    if workspace_id != str(UUID(workspace_id)):
        raise ValueError(
            "Installation Key workspace ID must be canonical lowercase UUID text"
        )
    if installation.get("Name") != key:
        raise ValueError("Name must equal Installation Key")
    hub_url = installation.get("Hub URL")
    if not isinstance(hub_url, str):
        raise ValueError("Hub URL must be an HTTP(S) URL")
    parsed_url = urlsplit(hub_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Hub URL must be an HTTP(S) URL")
    status = installation.get("Status")
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("Status must be initializing, active, paused, or error")
    for field in ("Enabled", "Autopilot Enabled"):
        if type(installation.get(field)) is not bool:
            raise ValueError(f"{field} must be a boolean")
    exact_values = {
        "Timezone": "Asia/Seoul",
        "Hourly Interval Minutes": 60,
        "World Memory Interval Hours": 6,
        "Schema Version": 2,
        "Skill Contract Version": "notion-v2",
    }
    for field, expected in exact_values.items():
        value = installation.get(field)
        if type(value) is not type(expected) or value != expected:
            raise ValueError(f"{field} must be exactly {expected!r}")
    _validate_cursor_state(installation.get("Feed Cursor State"))
    for field in _INSTALLATION_CACHE_TIMES:
        _canonical_utc(installation.get(field), field, allow_empty=True)
    if not isinstance(installation.get("Last Error"), str):
        raise ValueError("Last Error must be a string")
    _notion_timestamp(installation.get("Created At"), "Created At")
    _notion_timestamp(installation.get("Updated At"), "Updated At")
    runs = installation.get("Runs")
    if runs is not None:
        if not isinstance(runs, list):
            raise ValueError("Runs must be an array of page IDs")
        for index, run_id in enumerate(runs):
            _uuid(run_id, f"Runs[{index}]")
    # Keep observed opaque values byte-for-byte; validation must not normalize IDs.
    _ = page_id, hub_page_id
    return deepcopy(installation)


def validate_installation_row(
    row: object,
    expected_installation_key: str,
    expected_hub_page_id: str,
    expected_hub_url: str,
) -> list[str]:
    """Validate a raw fetched Notion Installation row before adapter decoding."""
    errors: list[str] = []
    if not isinstance(row, dict):
        return ["Installation row must be an object"]
    cursor_text = row.get("Feed Cursor State")
    if not isinstance(cursor_text, str):
        return ["Feed Cursor State must be canonical compact JSON text"]

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate Feed Cursor State key: {key}")
            result[key] = value
        return result

    try:
        decoded_cursor = json.loads(
            cursor_text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
        canonical_cursor = json.dumps(
            decoded_cursor,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Feed Cursor State is invalid: {exc}")
        return errors
    if cursor_text != canonical_cursor:
        errors.append("Feed Cursor State must be canonical compact JSON text")
    adapted = deepcopy(row)
    adapted["Feed Cursor State"] = decoded_cursor
    try:
        validate_operational_installation(adapted)
    except ValueError as exc:
        errors.append(str(exc))
    if row.get("Installation Key") != expected_installation_key:
        errors.append("Installation Key does not match registry")
    if row.get("Name") != expected_installation_key:
        errors.append("Installation Name does not match registry")
    if row.get("Hub Page ID") != expected_hub_page_id:
        errors.append("Hub Page ID does not match registry")
    if row.get("Hub URL") != expected_hub_url:
        errors.append("Hub URL does not match registry")
    return errors


def _policy(
    action: str,
    reason: str,
    *,
    run: bool,
    collect: bool,
    analyze: bool,
    child: bool,
    cache: bool,
    memory: bool,
    complete: bool,
    notification: str,
) -> dict[str, bool | str]:
    return {
        "action": action,
        "reason": reason,
        "run": run,
        "collect": collect,
        "analyze": analyze,
        "schemaMutation": False,
        "childMutation": child,
        "cacheMutation": cache,
        "memoryMutation": memory,
        "completeSuggestions": complete,
        "notification": notification,
    }


def _blocked(action: str, reason: str, notification: str) -> dict[str, bool | str]:
    return _policy(
        action,
        reason,
        run=False,
        collect=False,
        analyze=False,
        child=False,
        cache=False,
        memory=False,
        complete=False,
        notification=notification,
    )


def _read_only(reason: str, notification: str) -> dict[str, bool | str]:
    return _policy(
        "read-only",
        reason,
        run=True,
        collect=True,
        analyze=True,
        child=False,
        cache=False,
        memory=False,
        complete=False,
        notification=notification,
    )


def run_policy(
    installation: dict | None,
    trigger: str,
    *,
    registry_valid: bool,
    explicit_setup: bool = False,
) -> dict[str, bool | str]:
    """Return the exact fail-closed permission boundary for one invocation."""
    normalized = normalize_trigger(trigger)
    if normalized == "scheduled" and explicit_setup is True:
        raise ValueError("scheduled trigger cannot use explicit setup")
    if type(registry_valid) is not bool or type(explicit_setup) is not bool:
        raise ValueError("registry_valid and explicit_setup must be a boolean")
    if not registry_valid:
        return _blocked("setup-required", "registry-invalid", "error")
    if installation is None:
        return _blocked("setup-required", "installation-missing", "error")
    if not isinstance(installation, dict):
        raise ValueError("installation must be an object or null")
    installation = validate_operational_installation(installation)

    status = installation.get("Status")
    enabled = installation.get("Enabled")
    autopilot = installation.get("Autopilot Enabled")
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("Status must be initializing, active, paused, or error")
    if type(enabled) is not bool:
        raise ValueError("Enabled must be a boolean")
    if type(autopilot) is not bool:
        raise ValueError("Autopilot Enabled must be a boolean")

    if not enabled:
        if normalized == "scheduled":
            return _blocked("silent-noop", "disabled", "silent")
        return _read_only("disabled", "disabled")
    if status == "initializing":
        if explicit_setup and normalized in {"manual", "force-world-memory"}:
            return _policy(
                "run",
                "explicit-setup",
                run=True,
                collect=True,
                analyze=True,
                child=True,
                cache=True,
                memory=autopilot,
                complete=autopilot,
                notification="normal",
            )
        return _blocked("setup-required", "initializing", "error")
    if status == "paused":
        if normalized == "scheduled":
            return _blocked("silent-noop", "paused", "silent")
        return _read_only("paused", "disabled")
    if status == "error":
        if normalized == "scheduled":
            return _blocked("stored-error", "stored-error", "error")
        return _read_only("stored-error", "error")

    reason = "active" if autopilot else "autopilot-disabled"
    return _policy(
        "run",
        reason,
        run=True,
        collect=True,
        analyze=True,
        child=True,
        cache=True,
        memory=autopilot,
        complete=autopilot,
        notification="normal",
    )


def _installation_prefix(installation: dict) -> str:
    key = installation.get("Installation Key")
    if not isinstance(key, str) or not key:
        raise ValueError("Installation Key must be a non-empty string")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _validate_integration_key(value: object, prefix: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Integration Key must be a string")
    match = _INTEGRATION_KEY.fullmatch(value)
    if match is None or match.group(1) != prefix:
        raise ValueError("Integration Key must match the Installation Key")
    encoded_cutoff = match.group(3)
    if encoded_cutoff:
        try:
            datetime.strptime(encoded_cutoff, "%Y%m%dT%H%M%SZ")
        except ValueError as exc:
            raise ValueError("Integration Key contains an invalid cutoff") from exc
    return value


def effective_last_integration(
    installation: dict,
    committed_integrations: Iterable[dict],
) -> str:
    """Select only unique committed integration Runs over the eventual cache."""
    if not isinstance(installation, dict):
        raise ValueError("installation must be an object")
    prefix = _installation_prefix(installation)
    seen: set[str] = set()
    cutoffs: list[str] = []
    try:
        rows = list(committed_integrations)
    except TypeError as exc:
        raise ValueError("committed_integrations must be iterable") from exc
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"committed_integrations[{index}] must be an object")
        status = row.get("Status")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            raise ValueError(f"committed_integrations[{index}].Status is invalid")
        if status != "committed":
            continue
        performed = row.get("Integration Performed")
        if type(performed) is not bool:
            raise ValueError("Integration Performed must be a boolean")
        if not performed:
            if row.get("Integration Key") != "":
                raise ValueError(
                    "committed non-integration Run Integration Key must be empty"
                )
            continue
        key = _validate_integration_key(row.get("Integration Key"), prefix)
        if key in seen:
            raise ValueError(f"duplicate committed Integration Key: {key}")
        seen.add(key)
        cutoffs.append(
            _canonical_utc(row.get("Collection Cutoff"), "Collection Cutoff")
        )
    if cutoffs:
        return max(cutoffs)
    return ""


def world_memory_due(
    installation: dict,
    committed_integrations: Iterable[dict],
    now: datetime,
    trigger: str,
) -> bool:
    """Return the timing-only nominal six-hour gate from authoritative Runs."""
    normalized = normalize_trigger(trigger)
    current = _aware_utc(now, "now")
    interval = installation.get("World Memory Interval Hours") if isinstance(installation, dict) else None
    if type(interval) is not int or interval != 6:
        raise ValueError("World Memory Interval Hours must be exactly 6")
    cutoff = effective_last_integration(installation, committed_integrations)
    if not cutoff:
        return True
    cutoff_at = parse_utc(cutoff)
    if cutoff_at > current:
        raise ValueError("authoritative integration cutoff cannot be in the future")
    if normalized == "force-world-memory":
        return True
    return current >= cutoff_at + _INTERNAL_INTEGRATION_GATE


def _exact_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _exact_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _validate_cursor_state(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Feed Cursor State must be an object")
    result: dict[str, str] = {}
    for feed_id, cursor in value.items():
        if feed_id not in _FEED_IDS:
            raise ValueError(f"Feed Cursor State has unknown feed id: {feed_id}")
        if not isinstance(cursor, str) or (cursor and _LOWER_SHA256.fullmatch(cursor) is None):
            raise ValueError(f"Feed Cursor State[{feed_id}] must be empty or lowercase sha256")
        result[feed_id] = cursor
    return result


def _validate_source_outcomes(value: object, description: str) -> dict[str, dict]:
    if not isinstance(value, dict):
        raise ValueError(f"{description}.sourceOutcomes must be an object")
    if set(value) != set(_FEED_IDS):
        raise ValueError(
            f"{description}.sourceOutcomes must contain exactly the configured sources"
        )
    result: dict[str, dict] = {}
    for feed_id, outcome in value.items():
        if feed_id not in _FEED_IDS:
            raise ValueError(f"{description}.sourceOutcomes has unknown feed id: {feed_id}")
        if not isinstance(outcome, dict) or set(outcome) != _OUTCOME_KEYS:
            raise ValueError(
                f"{description}.sourceOutcomes[{feed_id}] must contain exact outcome fields"
            )
        status = outcome.get("status")
        item_count = outcome.get("itemCount")
        cursor = outcome.get("cursor")
        error = outcome.get("error")
        if not isinstance(status, str) or status not in {"ok", "error"}:
            raise ValueError(f"{description}.sourceOutcomes[{feed_id}].status is invalid")
        if type(item_count) is not int or item_count < 0:
            raise ValueError(f"{description}.sourceOutcomes[{feed_id}].itemCount is invalid")
        if not isinstance(cursor, str) or not isinstance(error, str):
            raise ValueError(f"{description}.sourceOutcomes[{feed_id}] strings are invalid")
        if status == "ok":
            if error or (cursor and _LOWER_SHA256.fullmatch(cursor) is None):
                raise ValueError(f"{description}.sourceOutcomes[{feed_id}] ok fields are invalid")
        elif item_count != 0 or cursor or not error.strip():
            raise ValueError(f"{description}.sourceOutcomes[{feed_id}] error fields are invalid")
        result[feed_id] = deepcopy(outcome)
    return result


_CACHE_SNAPSHOT_FIELDS = (
    "Run Key",
    "Status",
    "Collection Cutoff",
    "Finished At",
    "Integration Key",
    "Integration Performed",
    "Notification Plan",
    "sourceOutcomes",
)


def _validate_cache_run(row: object, index: int, installation_prefix: str) -> dict:
    description = f"authoritative_runs[{index}]"
    if not isinstance(row, dict):
        raise ValueError(f"{description} must be an object")
    key = row.get("Run Key")
    if not isinstance(key, str) or not key:
        raise ValueError(f"{description}.Run Key must be a non-empty string")
    status = row.get("Status")
    if not isinstance(status, str) or status not in _RUN_STATUSES:
        raise ValueError(f"{description}.Status is invalid")
    if status != "committed":
        return row
    _canonical_utc(row.get("Collection Cutoff"), f"{description}.Collection Cutoff")
    _canonical_utc(row.get("Finished At"), f"{description}.Finished At")
    performed = row.get("Integration Performed")
    if type(performed) is not bool:
        raise ValueError(f"{description}.Integration Performed must be a boolean")
    integration_key = row.get("Integration Key")
    if not isinstance(integration_key, str):
        raise ValueError(f"{description}.Integration Key must be a string")
    if performed or integration_key:
        _validate_integration_key(integration_key, installation_prefix)
    if performed is not bool(integration_key):
        raise ValueError(
            f"{description}.Integration Key must be present exactly when integration is performed"
        )
    notification = row.get("Notification Plan")
    if not isinstance(notification, str) or notification not in _NOTIFICATION_PLANS:
        raise ValueError(f"{description}.Notification Plan is invalid")
    source_outcomes = _validate_source_outcomes(row.get("sourceOutcomes"), description)
    successes = [outcome for outcome in source_outcomes.values() if outcome["status"] == "ok"]
    if not successes:
        raise ValueError(f"{description} committed Run has all sources failed")
    return row


def _row_time(row: dict, field: str) -> datetime:
    return parse_utc(row[field])


def _validated_cache_authority(
    authoritative_runs: Iterable[dict],
    installation_prefix: str,
) -> list[dict]:
    try:
        raw_rows = list(authoritative_runs)
    except TypeError as exc:
        raise ValueError("authoritative_runs must be iterable") from exc
    rows: list[dict] = []
    seen_run_keys: set[str] = set()
    seen_integration_keys: set[str] = set()
    for index, raw in enumerate(raw_rows):
        row = _validate_cache_run(raw, index, installation_prefix)
        run_key_value = row.get("Run Key")
        if run_key_value in seen_run_keys:
            raise ValueError(
                f"duplicate Run Key in authoritative projection: {run_key_value}"
            )
        seen_run_keys.add(run_key_value)
        if row.get("Status") == "committed" and row.get("Integration Key"):
            logical_key = row["Integration Key"]
            if logical_key in seen_integration_keys:
                raise ValueError(
                    f"duplicate committed Integration Key: {logical_key}"
                )
            seen_integration_keys.add(logical_key)
        rows.append(row)
    return rows


def _project_installation_cache(
    current: dict,
    rows: Iterable[dict],
    initial_cursor_state: dict[str, str],
) -> dict:
    committed = [row for row in rows if row.get("Status") == "committed"]
    committed.sort(key=lambda row: (_row_time(row, "Collection Cutoff"), row["Run Key"]))
    result = deepcopy(current)
    replayed = dict(initial_cursor_state)
    partial_rows: list[dict] = []
    for row in committed:
        source_outcomes = row["sourceOutcomes"]
        successes = 0
        failures = 0
        for feed_id in _FEED_IDS:
            outcome = source_outcomes.get(feed_id)
            if outcome is None:
                continue
            if outcome["status"] == "ok":
                successes += 1
                if outcome["cursor"]:
                    replayed[feed_id] = outcome["cursor"]
            else:
                failures += 1
        if successes and failures:
            partial_rows.append(row)
    result["Feed Cursor State"] = replayed

    if committed:
        latest_feed = committed[-1]
        result["Last Feed Attempt"] = latest_feed["Collection Cutoff"]
        result["Last Feed Success"] = latest_feed["Collection Cutoff"]
    else:
        result["Last Feed Attempt"] = ""
        result["Last Feed Success"] = ""

    integrations = [row for row in committed if row["Integration Performed"] is True]
    if integrations:
        latest_integration = integrations[-1]
        cutoff = latest_integration["Collection Cutoff"]
        result["Last World Memory Success"] = cutoff
        result["Next World Memory At"] = utc_iso(parse_utc(cutoff) + timedelta(hours=6))
    else:
        result["Last World Memory Success"] = ""
        result["Next World Memory At"] = ""

    reports = [
        row for row in committed
        if row["Notification Plan"] in {"hourly-briefing", "six-hour"}
    ]
    reports.sort(key=lambda row: (_row_time(row, "Finished At"), row["Run Key"]))
    result["Last Report Success"] = reports[-1]["Finished At"] if reports else ""
    briefings = [row for row in reports if row["Notification Plan"] == "hourly-briefing"]
    result["Last Briefing At"] = briefings[-1]["Finished At"] if briefings else ""

    if partial_rows:
        latest_partial = partial_rows[-1]
        failures = [
            f"{feed_id}: {latest_partial['sourceOutcomes'][feed_id]['error']}"
            for feed_id in _FEED_IDS
            if feed_id in latest_partial["sourceOutcomes"]
            and latest_partial["sourceOutcomes"][feed_id]["status"] == "error"
        ]
        result["Last Error"] = "; ".join(failures)
    else:
        result["Last Error"] = ""
    return result


def reconstruct_installation_cache(
    current: dict,
    authoritative_runs: Iterable[dict],
) -> dict:
    """Rebuild every Installation cache field from committed ledger authority."""
    if not isinstance(current, dict):
        raise ValueError("current must be an object")
    prefix = _installation_prefix(current)
    rows = _validated_cache_authority(authoritative_runs, prefix)
    return _project_installation_cache(current, rows, {})


def reconcile_installation_cache(
    current: dict,
    candidate: dict,
    authoritative_runs: Iterable[dict],
) -> dict:
    """Repair the Installation cache from a complete committed Run projection."""
    if not isinstance(current, dict):
        raise ValueError("current must be an object")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    try:
        cursor_state = _validate_cursor_state(current.get("Feed Cursor State", {}))
    except ValueError:
        cursor_state = {}
    prefix = _installation_prefix(current)
    rows = _validated_cache_authority(authoritative_runs, prefix)

    if candidate.get("Status") != "committed":
        return deepcopy(current)
    candidate_key = candidate.get("Run Key")
    matches = [row for row in rows if row.get("Run Key") == candidate_key]
    if len(matches) != 1 or matches[0].get("Status") != "committed":
        return deepcopy(current)
    validated_candidate = _validate_cache_run(candidate, -1, prefix)
    authoritative_candidate = matches[0]
    for field in _CACHE_SNAPSHOT_FIELDS:
        if field not in validated_candidate or field not in authoritative_candidate:
            raise ValueError(f"candidate {field} is missing from required snapshot")
        if not _exact_equal(validated_candidate[field], authoritative_candidate[field]):
            raise ValueError(f"candidate {field} does not match authoritative snapshot")
    for field, candidate_value in validated_candidate.items():
        if field not in authoritative_candidate:
            raise ValueError(f"candidate {field} is missing from authoritative snapshot")
        if not _exact_equal(candidate_value, authoritative_candidate[field]):
            raise ValueError(f"candidate {field} does not match authoritative snapshot")

    return _project_installation_cache(current, rows, cursor_state)
