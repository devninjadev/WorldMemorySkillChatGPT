"""Storage-neutral payload, registry, and Notion schema validation."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit
from uuid import UUID


CATEGORIES = {"stock_bond", "geopolitics", "emerging"}
REGIONS = {"US", "KR", "GLOBAL"}
IMPORTANCE = {"high", "medium", "low"}
FEED_STATUSES = {"pending", "processed"}
SUGGESTION_STATUSES = {"open", "watching", "completed"}
MUTATION_ACTIONS = {
    "brief-add", "state-add", "state-supersede", "story-link",
    "taxonomy-refresh", "suggestion-status-update",
}
READ_ONLY_ACTIONS = {"investigate"}
_REPORT_STORAGE_OWNED_FIELDS = frozenset({
    "runKey",
    "reportKey",
    "integrationKey",
    "materialChange",
    "userVisible",
    "evidenceRecords",
    "coverageStart",
    "coverageEnd",
    "collectionCutoff",
    "notificationPlan",
})

# Kept here instead of importing feed.py so validation remains a dependency leaf.
CONFIGURED_SOURCES = (
    ("financial_juice", "FinancialJuice", "https://rss.app/feeds/5VaycMAa8SwPhOAP.csv", 0),
    ("walter_bloomberg", "Walter Bloomberg", "https://rss.app/feeds/YcRRdWN5eSO3o2LP.csv", 0),
    ("wall_st_engine", "Wall St Engine", "https://rss.app/feeds/Hf52VRUllNu7gABF.csv", 0),
    ("first_squawk", "First Squawk", "https://rss.app/feeds/d68ow40E3dkwaEvN.csv", -540),
    ("unusual_whales", "unusual_whales", "https://rss.app/feeds/nikLNBATmLDuprRz.csv", -540),
)
SOURCE_BY_ID = {source[0]: source for source in CONFIGURED_SOURCES}
STATE_STRING_FIELDS = (
    "state_id", "state_key", "state_label", "state_status", "state_bias", "net_effect",
    "summary", "rationale", "source_event_id", "supersedes_state_id", "replaced_by_state_id",
)
STATE_TIME_FIELDS = ("effective_from", "effective_to", "updated_at")
EVENT_LIST_FIELDS = ("tickers", "tags", "subjects", "industries")
EVENT_STRING_FIELDS = (
    "why_it_matters", "portfolio_link", "horizon", "event_kind", "story", "story_key",
    "story_family",
)


def is_utc_iso(value: object) -> bool:
    """Return whether value is an empty or UTC ISO 8601 timestamp."""
    if value == "":
        return True
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
    ):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _is_nonempty_utc(value: object) -> bool:
    return value != "" and is_utc_iso(value)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _is_valid_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_one_of(value: object, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def _missing(value: dict[str, object], fields: tuple[str, ...]) -> list[str]:
    return [f"missing required key: {field}" for field in fields if field not in value]


def _object(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _validate_schema_version(value: dict[str, object], field: str = "schemaVersion") -> list[str]:
    if value.get(field) != 1 or not _is_int(value.get(field)):
        return [f"{field} must be 1"]
    return []


def _validate_string(value: dict[str, object], field: str, *, nonempty: bool = False) -> list[str]:
    current = value.get(field)
    if not isinstance(current, str) or (nonempty and not current.strip()):
        description = "a non-empty string" if nonempty else "a string"
        return [f"{field} must be {description}"]
    return []


def _validate_list(value: dict[str, object], field: str) -> list[str]:
    if not isinstance(value.get(field), list):
        return [f"{field} must be a list"]
    return []


def _validate_object(value: dict[str, object], field: str) -> list[str]:
    if not isinstance(value.get(field), dict):
        return [f"{field} must be an object"]
    return []


def validate_world_state(value: object) -> list[str]:
    state = _object(value)
    if state is None:
        return ["world-state must be an object"]
    required = ("schemaVersion", "states", "storyLinks", "taxonomy", "updatedAt")
    errors = _missing(state, required)
    errors.extend(_validate_schema_version(state))
    for field in ("states", "storyLinks"):
        errors.extend(_validate_list(state, field))
    errors.extend(_validate_object(state, "taxonomy"))
    if not is_utc_iso(state.get("updatedAt")):
        errors.append("updatedAt must be UTC ISO 8601 or empty")
    states = state.get("states")
    if isinstance(states, list):
        for index, item in enumerate(states):
            if not isinstance(item, dict):
                errors.append(f"states[{index}] must be an object")
                continue
            for field in STATE_STRING_FIELDS:
                if not isinstance(item.get(field), str):
                    errors.append(f"states[{index}].{field} must be a string")
            for field in STATE_TIME_FIELDS:
                if not is_utc_iso(item.get(field)):
                    errors.append(f"states[{index}].{field} must be UTC ISO 8601 or empty")
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                errors.append(f"states[{index}].confidence must be between 0 and 1")
    story_links = state.get("storyLinks")
    if isinstance(story_links, list):
        for index, item in enumerate(story_links):
            if not isinstance(item, dict):
                errors.append(f"storyLinks[{index}] must be an object")
    return errors

def validate_suggestions(value: object) -> list[str]:
    suggestions = _object(value)
    if suggestions is None:
        return ["suggestions must be an object"]
    required = ("schemaVersion", "items", "updatedAt")
    errors = _missing(suggestions, required)
    errors.extend(_validate_schema_version(suggestions))
    errors.extend(_validate_list(suggestions, "items"))
    if not is_utc_iso(suggestions.get("updatedAt")):
        errors.append("updatedAt must be UTC ISO 8601 or empty")
    items = suggestions.get("items")
    expected_fields = {
        "continuityId", "text", "status", "action", "target", "evidence", "confidence", "handledAt",
    }
    if isinstance(items, list):
        for index, item in enumerate(items):
            prefix = f"items[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            missing = expected_fields - set(item)
            extra = set(item) - expected_fields
            for field in sorted(missing):
                errors.append(f"{prefix} missing required key: {field}")
            for field in sorted(extra):
                errors.append(f"{prefix} has unsupported key: {field}")
            for field in ("continuityId", "text"):
                if not isinstance(item.get(field), str):
                    errors.append(f"{prefix}.{field} must be a string")
            if not _is_one_of(item.get("status"), SUGGESTION_STATUSES):
                errors.append(f"{prefix}.status must be open, watching, or completed")
            action = item.get("action")
            if not _is_one_of(action, MUTATION_ACTIONS | READ_ONLY_ACTIONS):
                errors.append(f"{prefix}.action is not allowlisted")
            if not isinstance(item.get("target"), str) or not item["target"].strip():
                errors.append(f"{prefix}.target must be a non-empty string")
            if not isinstance(item.get("evidence"), list):
                errors.append(f"{prefix}.evidence must be a list")
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                errors.append(f"{prefix}.confidence must be between 0 and 1")
            if not is_utc_iso(item.get("handledAt")):
                errors.append(f"{prefix}.handledAt must be UTC ISO 8601 or empty")
            if item.get("status") == "completed" and not _is_one_of(action, MUTATION_ACTIONS):
                errors.append(f"{prefix}.status completed requires a mutation action")
    return errors


def validate_report(value: object) -> list[str]:
    report = _object(value)
    if report is None:
        return ["report-latest must be an object"]
    required = (
        "schemaVersion", "title", "asOf", "coverage", "dataQuality", "stance",
        "confidence", "summary", "narrative", "changesSincePrevious", "signalRadar",
        "highlights", "memoryChangeSuggestions", "portfolioSuggestions", "nextChecks",
        "sources",
    )
    errors = _missing(report, required)
    for field in sorted(_REPORT_STORAGE_OWNED_FIELDS & set(report)):
        errors.append(f"{field} is owned by Report storage and must not be supplied")
    version = report.get("schemaVersion")
    if not _is_int(version) or version != 2:
        errors.append("schemaVersion must be 2")
    if "scenarios" not in report:
        errors.append("missing required key: scenarios")
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, dict):
        errors.append("scenarios must be an object")
    else:
        scenario_names = {"기준", "낙관", "비관"}
        if set(scenarios) != scenario_names:
            errors.append("scenarios must contain exactly 기준, 낙관, and 비관")
        scenario_fields = {"activation", "transmission", "invalidation", "nextCheck"}
        for scenario_name in sorted(scenario_names & set(scenarios)):
            scenario = scenarios[scenario_name]
            if not isinstance(scenario, dict):
                errors.append(f"scenarios.{scenario_name} must be an object")
                continue
            if set(scenario) != scenario_fields:
                errors.append(
                    f"scenarios.{scenario_name} must contain exactly activation, "
                    "transmission, invalidation, and nextCheck"
                )
            for field in sorted(scenario_fields):
                if not isinstance(scenario.get(field), str) or not scenario[field].strip():
                    errors.append(
                        f"scenarios.{scenario_name}.{field} must be a non-empty string"
                    )
    for field in ("title", "asOf", "coverage", "summary", "narrative"):
        errors.extend(_validate_string(report, field))
    if not is_utc_iso(report.get("asOf")):
        errors.append("asOf must be UTC ISO 8601 or empty")
    errors.extend(_validate_object(report, "dataQuality"))
    if isinstance(report.get("dataQuality"), dict):
        errors.extend(_validate_list(report["dataQuality"], "gaps"))
        gaps = report["dataQuality"].get("gaps")
        if isinstance(gaps, list):
            for index, gap in enumerate(gaps):
                if not isinstance(gap, str):
                    errors.append(f"dataQuality.gaps[{index}] must be a string")
    if not _is_one_of(report.get("stance"), {"risk-on", "neutral", "defensive", "mixed"}):
        errors.append("stance must be risk-on, neutral, defensive, or mixed")
    confidence = report.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be between 0 and 1")
    for field in (
        "changesSincePrevious", "signalRadar", "highlights", "memoryChangeSuggestions",
        "portfolioSuggestions", "nextChecks", "sources",
    ):
        errors.extend(_validate_list(report, field))
    for field, maximum in (("signalRadar", 8), ("highlights", 8), ("portfolioSuggestions", 6), ("nextChecks", 6)):
        entries = report.get(field)
        if isinstance(entries, list) and len(entries) > maximum:
            errors.append(f"{field} must contain at most {maximum} items")
    for field in (
        "changesSincePrevious", "signalRadar", "highlights", "memoryChangeSuggestions",
        "portfolioSuggestions", "nextChecks",
    ):
        entries = report.get(field)
        if isinstance(entries, list):
            for index, item in enumerate(entries):
                _validate_report_item(errors, f"{field}[{index}]", item)
    sources = report.get("sources")
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            prefix = f"sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("name", "url"):
                if not isinstance(source.get(field), str) or not source[field].strip():
                    errors.append(f"{prefix}.{field} must be a non-empty string")
            _validate_score(errors, prefix, source)
    return errors


def _validate_score(errors: list[str], prefix: str, value: dict[str, object]) -> None:
    if "score" in value and value["score"] is not None and (
        isinstance(value["score"], bool) or not isinstance(value["score"], (int, float))
    ):
        errors.append(f"{prefix}.score must be numeric or null")


def _validate_report_item(errors: list[str], prefix: str, item: object) -> None:
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return
    if not any(isinstance(value, str) and value.strip() for value in item.values()):
        errors.append(f"{prefix} must contain a non-empty string field")
    _validate_score(errors, prefix, item)


def validate_feed_row(value: object) -> list[str]:
    row = _object(value)
    if row is None:
        return ["row must be an object"]
    required = (
        "schemaVersion", "id", "sourceFingerprint", "feedId", "feedTitle",
        "feedSourceUrl", "sourceUrl", "title", "sourcePublishedAt", "publishedAt",
        "publishedAtOffsetMinutes", "fetchedAt", "status", "importanceCandidate",
    )
    errors = _missing(row, required)
    errors.extend(_validate_schema_version(row))
    for field in required:
        if field not in {"schemaVersion", "publishedAtOffsetMinutes"}:
            errors.extend(_validate_string(row, field, nonempty=True))
    if not _is_int(row.get("publishedAtOffsetMinutes")):
        errors.append("publishedAtOffsetMinutes must be an integer")
    for field in ("sourcePublishedAt", "publishedAt", "fetchedAt"):
        if not _is_nonempty_utc(row.get(field)):
            errors.append(f"{field} must be UTC ISO 8601")
    fingerprint = row.get("sourceFingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        errors.append("sourceFingerprint must be 64 lowercase hexadecimal characters")
    # The raw publication text is intentionally not stored, so do not recompute the
    # fingerprint.  Shape and ID coupling still detect corrupted durable rows.
    if isinstance(fingerprint, str) and row.get("id") != f"nf_{fingerprint[:18]}":
        errors.append("id must be nf_ plus the first 18 sourceFingerprint characters")
    feed_id = row.get("feedId")
    source = SOURCE_BY_ID.get(feed_id) if isinstance(feed_id, str) else None
    if source is None or any(row.get(field) != expected for field, expected in (
        ("feedTitle", source[1] if source else None),
        ("feedSourceUrl", source[2] if source else None),
        ("publishedAtOffsetMinutes", source[3] if source else None),
    )):
        errors.append("feed source metadata must match configured source")
    if _is_nonempty_utc(row.get("sourcePublishedAt")) and _is_nonempty_utc(row.get("publishedAt")) and _is_int(row.get("publishedAtOffsetMinutes")):
        if _parse_utc(row["publishedAt"]) != _parse_utc(row["sourcePublishedAt"]) + timedelta(minutes=row["publishedAtOffsetMinutes"]):
            errors.append("publishedAt must equal sourcePublishedAt plus publishedAtOffsetMinutes")
    if not _is_one_of(row.get("status"), FEED_STATUSES):
        errors.append("status must be pending or processed")
    if not _is_one_of(row.get("importanceCandidate"), {"unassessed", *IMPORTANCE}):
        errors.append("importanceCandidate must be unassessed, high, medium, or low")
    return errors


def validate_world_event(value: object) -> list[str]:
    row = _object(value)
    if row is None:
        return ["row must be an object"]
    required = (
        "schema_version", "entry_type", "event_id", "logged_at", "as_of", "date",
        "category", "region", "importance", "entry_mode", "dedupe_key", "title",
        "summary", "sources",
    )
    errors = _missing(row, required)
    errors.extend(_validate_schema_version(row, "schema_version"))
    for field in (
        "entry_type", "event_id", "logged_at", "as_of", "date", "category", "region",
        "importance", "entry_mode", "dedupe_key", "title", "summary",
    ):
        errors.extend(_validate_string(row, field, nonempty=True))
    if row.get("entry_type") != "world_issue":
        errors.append("entry_type must be world_issue")
    for field in ("logged_at", "as_of"):
        if not _is_nonempty_utc(row.get(field)):
            errors.append(f"{field} must be UTC ISO 8601")
    if not _is_valid_date(row.get("date")):
        errors.append("date must be a valid YYYY-MM-DD date")
    if not _is_one_of(row.get("category"), CATEGORIES):
        errors.append("category must be stock_bond, geopolitics, or emerging")
    if not _is_one_of(row.get("region"), REGIONS):
        errors.append("region must be US, KR, or GLOBAL")
    if not _is_one_of(row.get("importance"), IMPORTANCE):
        errors.append("importance must be high, medium, or low")
    if not _is_one_of(row.get("entry_mode"), {"issue", "brief"}):
        errors.append("entry_mode must be issue or brief")
    errors.extend(_validate_list(row, "sources"))
    sources = row.get("sources")
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            prefix = f"sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("name", "url"):
                if not isinstance(source.get(field), str) or not source[field].strip():
                    errors.append(f"{prefix}.{field} must be a non-empty string")
            if "published_at" in source and not _is_nonempty_utc(source["published_at"]):
                errors.append(f"{prefix}.published_at must be UTC ISO 8601")
            if "note" in source and not isinstance(source["note"], str):
                errors.append(f"{prefix}.note must be a string")
    for field in EVENT_LIST_FIELDS:
        if field in row and (
            not isinstance(row[field], list)
            or any(not isinstance(item, str) or not item.strip() for item in row[field])
        ):
            errors.append(f"{field} must be a list of non-empty strings")
    for field in EVENT_STRING_FIELDS:
        if field in row and not isinstance(row[field], str):
            errors.append(f"{field} must be a string")
    for field in row:
        if field.startswith("state_") and not isinstance(row[field], str):
            errors.append(f"{field} must be a string")
    anchors = (
        isinstance(row.get("event_kind"), str) and bool(row["event_kind"].strip()),
        any(isinstance(item, str) and item.strip() for item in row.get("subjects", []) if isinstance(row.get("subjects"), list)),
        any(isinstance(item, str) and item.strip() for item in row.get("industries", []) if isinstance(row.get("industries"), list)),
    )
    if row.get("entry_mode") == "brief" and not any(anchors):
        errors.append("brief requires subjects, industries, or event_kind")
    return errors


def validate_audit(value: object) -> list[str]:
    row = _object(value)
    if row is None:
        return ["row must be an object"]
    errors = []
    exact_fields = {
        "timestamp", "trigger", "feed", "materialChange", "worldMemory",
        "notification", "audit", "commit",
    }
    if set(row) != exact_fields:
        errors.append("audit row must contain exactly the canonical top-level fields")
    if not _is_nonempty_utc(row.get("timestamp")):
        errors.append("timestamp must be UTC ISO 8601")
    if not _is_one_of(row.get("trigger"), {"scheduled", "manual", "force-world-memory"}):
        errors.append("trigger must be scheduled, manual, or force-world-memory")
    for field in ("feed", "materialChange", "worldMemory", "notification", "audit", "commit"):
        if not isinstance(row.get(field), dict):
            errors.append(f"{field} must be an object")
    feed = row.get("feed")
    if isinstance(feed, dict):
        required_feed_fields = {
            "sourceOutcomes", "successCount", "failureCount", "newItemCount",
        }
        for field in sorted(required_feed_fields - set(feed)):
            errors.append(f"feed missing required key: {field}")
        outcomes = feed.get("sourceOutcomes")
        configured_ids = [source[0] for source in CONFIGURED_SOURCES]
        if not isinstance(outcomes, list) or len(outcomes) != len(configured_ids):
            errors.append("feed.sourceOutcomes must contain exactly five configured outcomes")
        else:
            observed_ids: list[object] = []
            for index, outcome in enumerate(outcomes):
                prefix = f"feed.sourceOutcomes[{index}]"
                if not isinstance(outcome, dict):
                    errors.append(f"{prefix} must be an object")
                    observed_ids.append(None)
                    continue
                expected_outcome_fields = {
                    "feedId", "status", "itemCount", "cursor", "error",
                }
                if set(outcome) != expected_outcome_fields:
                    errors.append(f"{prefix} keys are not exact")
                observed_ids.append(outcome.get("feedId"))
                status = outcome.get("status")
                if not _is_one_of(status, {"ok", "error"}):
                    errors.append(f"{prefix}.status must be ok or error")
                if not _is_int(outcome.get("itemCount")) or outcome["itemCount"] < 0:
                    errors.append(f"{prefix}.itemCount must be a non-negative integer")
                for field in ("cursor", "error"):
                    if not isinstance(outcome.get(field), str):
                        errors.append(f"{prefix}.{field} must be a string")
                cursor = outcome.get("cursor")
                error_text = outcome.get("error")
                cursor_is_valid = (
                    isinstance(cursor, str)
                    and (cursor == "" or re.fullmatch(r"[0-9a-f]{64}", cursor) is not None)
                )
                if not cursor_is_valid:
                    errors.append(
                        f"{prefix}.cursor must be empty or lowercase sha256"
                    )
                if status == "ok" and error_text != "":
                    errors.append(f"{prefix} ok outcome error must be empty")
                if status == "error":
                    if outcome.get("itemCount") != 0:
                        errors.append(f"{prefix} error outcome itemCount must be zero")
                    if cursor != "":
                        errors.append(f"{prefix} error outcome cursor must be empty")
                    if not isinstance(error_text, str) or not error_text:
                        errors.append(
                            f"{prefix} error outcome error must be non-empty"
                        )
            if observed_ids != configured_ids:
                errors.append(
                    "feed.sourceOutcomes must preserve configured feed order"
                )
        for field in ("successCount", "failureCount", "newItemCount"):
            if not _is_int(feed.get(field)) or feed[field] < 0:
                errors.append(f"feed.{field} must be a non-negative integer")
        if isinstance(outcomes, list):
            success_count = sum(
                isinstance(outcome, dict) and outcome.get("status") == "ok"
                for outcome in outcomes
            )
            failure_count = sum(
                isinstance(outcome, dict) and outcome.get("status") == "error"
                for outcome in outcomes
            )
            if feed.get("successCount") != success_count:
                errors.append("feed.successCount must match sourceOutcomes")
            if feed.get("failureCount") != failure_count:
                errors.append("feed.failureCount must match sourceOutcomes")
            if success_count + failure_count != len(configured_ids):
                errors.append("feed successCount plus failureCount must equal five")
            if failure_count == len(configured_ids) and feed.get("newItemCount") != 0:
                errors.append("feed.newItemCount must be zero when every source failed")
    audit = row.get("audit")
    inventory = audit.get("expectedChildren") if isinstance(audit, dict) else None
    if not isinstance(inventory, dict) or set(inventory) != {"feed", "memory", "report"}:
        errors.append("audit.expectedChildren must contain exactly feed, memory, and report")
        return errors
    entry_fields = {
        "feed": {"key", "pageId", "payloadDigest", "fingerprintWindowDigest"},
        "memory": {"key", "pageId", "payloadDigest"},
        "report": {"key", "pageId", "payloadDigest", "renderingDigest"},
    }
    seen_keys: set[str] = set()
    seen_page_ids: set[str] = set()
    digest_pattern = re.compile(r"[0-9a-f]{64}")
    for kind in ("feed", "memory", "report"):
        entries = inventory.get(kind)
        if not isinstance(entries, list):
            errors.append(f"audit.expectedChildren.{kind} must be a list")
            continue
        keys: list[str] = []
        for index, entry in enumerate(entries):
            prefix = f"audit.expectedChildren.{kind}[{index}]"
            if not isinstance(entry, dict) or set(entry) != entry_fields[kind]:
                errors.append(f"{prefix} keys are not exact")
                continue
            key = entry.get("key")
            if not isinstance(key, str) or not key:
                errors.append(f"{prefix}.key must be a non-empty string")
            else:
                keys.append(key)
                if key in seen_keys:
                    errors.append(f"{prefix}.key is duplicated")
                seen_keys.add(key)
            page_id = entry.get("pageId")
            try:
                UUID(page_id) if isinstance(page_id, str) else (_ for _ in ()).throw(ValueError())
            except (ValueError, AttributeError, TypeError):
                errors.append(f"{prefix}.pageId must be a UUID string")
            else:
                if page_id in seen_page_ids:
                    errors.append(f"{prefix}.pageId is duplicated")
                seen_page_ids.add(page_id)
            payload_digest = entry.get("payloadDigest")
            if not isinstance(payload_digest, str) or digest_pattern.fullmatch(payload_digest) is None:
                errors.append(f"{prefix}.payloadDigest must be lowercase sha256")
            if kind == "report":
                rendering_digest = entry.get("renderingDigest")
                if not isinstance(rendering_digest, str) or digest_pattern.fullmatch(rendering_digest) is None:
                    errors.append(f"{prefix}.renderingDigest must be lowercase sha256")
            if kind == "feed":
                fingerprint_digest = entry.get("fingerprintWindowDigest")
                is_first = isinstance(key, str) and key.endswith(":feed:001")
                if is_first:
                    if not isinstance(fingerprint_digest, str) or digest_pattern.fullmatch(fingerprint_digest) is None:
                        errors.append(
                            f"{prefix}.fingerprintWindowDigest must be lowercase sha256 for part one"
                        )
                elif fingerprint_digest != "":
                    errors.append(
                        f"{prefix}.fingerprintWindowDigest must be empty after part one"
                    )
        if keys != sorted(keys):
            errors.append(f"audit.expectedChildren.{kind} must be sorted by key")
    return errors


_DATABASE_KEYS = frozenset({"installations", "runs", "feed_batches", "memory", "reports"})
_REGISTRY_KEYS = {
    "skill", "installation_key", "notion_workspace_id", "hub_page_id", "hub_url",
    "schema_version", "skill_contract_version", "bootstrap_allowed",
    "scheduled_schema_mutation_allowed", "data_sources",
}
_SOURCE_KEYS = {"database_id", "data_source_id", "url"}


def _keyset_errors(value: dict, expected: set[str] | frozenset[str], prefix: str) -> list[str]:
    errors = [f"{prefix} missing required key: {key}" for key in sorted(expected - set(value))]
    labels = []
    for key in set(value) - expected:
        try:
            label = key if isinstance(key, str) else repr(key)
        except Exception:
            label = f"<{type(key).__name__}>"
        labels.append(label)
    errors.extend(f"{prefix} has unsupported key: {label}" for label in sorted(labels))
    return errors


def _uuid_error(value: object, field: str) -> str | None:
    if not isinstance(value, str):
        return f"{field} must be a UUID string"
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return f"{field} must be a UUID string"
    return None


def installation_key(workspace_id: str) -> str:
    """Return the canonical singleton installation key for a Notion workspace."""
    error = _uuid_error(workspace_id, "workspace_id")
    if error:
        raise ValueError(error)
    return f"wm:{str(UUID(workspace_id))}:default"


def _url_error(value: object, field: str) -> str | None:
    if not isinstance(value, str) or not value:
        return f"{field} must be a non-empty HTTP(S) URL"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return f"{field} must be a non-empty HTTP(S) URL"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"{field} must be a non-empty HTTP(S) URL"
    return None


def validate_registry(value: object) -> list[str]:
    """Validate the exact reusable World Memory registry."""
    if not isinstance(value, dict):
        return ["registry must be an object"]
    errors = _keyset_errors(value, {"world_memory"}, "registry")
    registry = value.get("world_memory")
    if not isinstance(registry, dict):
        errors.append("world_memory must be an object")
        return errors
    errors.extend(_keyset_errors(registry, _REGISTRY_KEYS, "world_memory"))
    if registry.get("skill") != "world-memory-autopilot":
        errors.append("world_memory.skill must be world-memory-autopilot")
    workspace_error = _uuid_error(
        registry.get("notion_workspace_id"), "world_memory.notion_workspace_id"
    )
    if workspace_error:
        errors.append(workspace_error)
    hub_error = _uuid_error(registry.get("hub_page_id"), "world_memory.hub_page_id")
    if hub_error:
        errors.append(hub_error)
    hub_url_error = _url_error(registry.get("hub_url"), "world_memory.hub_url")
    if hub_url_error:
        errors.append(hub_url_error)
    if type(registry.get("schema_version")) is not int or registry.get("schema_version") != 2:
        errors.append("world_memory.schema_version must be integer 2")
    if registry.get("skill_contract_version") != "notion-v2":
        errors.append("world_memory.skill_contract_version must be notion-v2")
    if registry.get("bootstrap_allowed") is not False:
        errors.append("world_memory.bootstrap_allowed must be false")
    if registry.get("scheduled_schema_mutation_allowed") is not False:
        errors.append("world_memory.scheduled_schema_mutation_allowed must be false")
    workspace_id = registry.get("notion_workspace_id")
    if workspace_error is None:
        if registry.get("installation_key") != installation_key(workspace_id):
            errors.append("world_memory.installation_key does not match notion_workspace_id")
    elif not isinstance(registry.get("installation_key"), str):
        errors.append("world_memory.installation_key must be a string")
    sources = registry.get("data_sources")
    if not isinstance(sources, dict):
        errors.append("world_memory.data_sources must be an object")
        return errors
    errors.extend(_keyset_errors(sources, _DATABASE_KEYS, "world_memory.data_sources"))
    for database_key in sorted(_DATABASE_KEYS & set(sources)):
        source = sources[database_key]
        prefix = f"world_memory.data_sources.{database_key}"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_keyset_errors(source, _SOURCE_KEYS, prefix))
        for field in ("database_id", "data_source_id"):
            error = _uuid_error(source.get(field), f"{prefix}.{field}")
            if error:
                errors.append(error)
        error = _url_error(source.get("url"), f"{prefix}.url")
        if error:
            errors.append(error)
    return errors


def _property(property_type: str) -> dict:
    return {"type": property_type}


def _select(*options: str) -> dict:
    return {"type": "SELECT", "options": list(options)}


def _relation(target: str, dual_property: str | None = None) -> dict:
    value = {"type": "RELATION", "target": target}
    if dual_property is not None:
        value["dual_property"] = dual_property
    return value


def _expected_data_source_properties(ids: dict[str, str]) -> dict[str, dict[str, dict]]:
    installations = {
        "Name": _property("TITLE"),
        "Installation Key": _property("RICH_TEXT"),
        "Hub Page ID": _property("RICH_TEXT"),
        "Hub URL": _property("URL"),
        "Status": _select("initializing", "active", "paused", "error"),
        "Enabled": _property("CHECKBOX"),
        "Autopilot Enabled": _property("CHECKBOX"),
        "Timezone": _select("Asia/Seoul"),
        "Hourly Interval Minutes": _property("NUMBER"),
        "World Memory Interval Hours": _property("NUMBER"),
        "Schema Version": _property("NUMBER"),
        "Skill Contract Version": _property("RICH_TEXT"),
        "Feed Cursor State": _property("RICH_TEXT"),
        "Last Feed Attempt": _property("DATE"),
        "Last Feed Success": _property("DATE"),
        "Last World Memory Success": _property("DATE"),
        "Last Report Success": _property("DATE"),
        "Next World Memory At": _property("DATE"),
        "Last Briefing At": _property("DATE"),
        "Last Error": _property("RICH_TEXT"),
        "Created At": _property("CREATED_TIME"),
        "Updated At": _property("LAST_EDITED_TIME"),
        "Runs": _relation(ids["runs"], "Installation"),
    }
    runs = {
        "Name": _property("TITLE"),
        "Slot Key": _property("RICH_TEXT"),
        "Run Key": _property("RICH_TEXT"),
        "Integration Key": _property("RICH_TEXT"),
        "Attempt": _property("NUMBER"),
        "Trigger": _select("scheduled", "manual", "force-world-memory"),
        "Status": _select("preparing", "committed", "failed", "superseded"),
        "Started At": _property("DATE"),
        "Scheduled Slot": _property("DATE"),
        "Collection Cutoff": _property("DATE"),
        "Finished At": _property("DATE"),
        "Feed Success Count": _property("NUMBER"),
        "Feed Failure Count": _property("NUMBER"),
        "New Item Count": _property("NUMBER"),
        "Material Change": _property("CHECKBOX"),
        "Integration Due": _property("CHECKBOX"),
        "Integration Performed": _property("CHECKBOX"),
        "Output Prepared": _property("CHECKBOX"),
        "Cache Reconciled": _property("CHECKBOX"),
        "Notification Plan": _select("silent", "hourly-briefing", "six-hour", "error"),
        "Input Digest": _property("RICH_TEXT"),
        "Output Digest": _property("RICH_TEXT"),
        "Error Summary": _property("RICH_TEXT"),
        "Created At": _property("CREATED_TIME"),
        "Updated At": _property("LAST_EDITED_TIME"),
        "Installation": _relation(ids["installations"], "Runs"),
        "Feed Batches": _relation(ids["feed_batches"], "Run"),
        "Memory Records": _relation(ids["memory"], "Run"),
        "Reports": _relation(ids["reports"], "Run"),
    }
    feed_batches = {
        "Name": _property("TITLE"),
        "Batch Key": _property("RICH_TEXT"),
        "Run Key": _property("RICH_TEXT"),
        "Payload Digest": _property("RICH_TEXT"),
        "Fingerprint Window Digest": _property("RICH_TEXT"),
        "Body Format": _property("RICH_TEXT"),
        "Part Index": _property("NUMBER"),
        "Part Count": _property("NUMBER"),
        "Feed Success Count": _property("NUMBER"),
        "Feed Failure Count": _property("NUMBER"),
        "New Item Count": _property("NUMBER"),
        "Item Count": _property("NUMBER"),
        "Fetched At": _property("DATE"),
        "All Sources Failed": _property("CHECKBOX"),
        "Created At": _property("CREATED_TIME"),
        "Run": _relation(ids["runs"], "Feed Batches"),
    }
    memory = {
        "Name": _property("TITLE"),
        "Record Key": _property("RICH_TEXT"),
        "Revision Key": _property("RICH_TEXT"),
        "Run Key": _property("RICH_TEXT"),
        "Dedupe Key": _property("RICH_TEXT"),
        "Continuity ID": _property("RICH_TEXT"),
        "Target": _property("RICH_TEXT"),
        "Payload Digest": _property("RICH_TEXT"),
        "Body Format": _property("RICH_TEXT"),
        "Record Type": _select("brief", "state", "story-link", "taxonomy", "suggestion"),
        "Record Status": _select("active", "open", "watching", "completed"),
        "Importance": _select("high", "medium", "low"),
        "Category": _select("stock_bond", "geopolitics", "emerging"),
        "Region": _select("US", "KR", "GLOBAL"),
        "Action": _select(
            "brief-add", "state-add", "state-supersede", "story-link",
            "taxonomy-refresh", "suggestion-status-update", "investigate",
        ),
        "Revision": _property("NUMBER"),
        "Confidence": _property("NUMBER"),
        "Effective At": _property("DATE"),
        "Verified Evidence": _property("CHECKBOX"),
        "Created At": _property("CREATED_TIME"),
        "Updated At": _property("LAST_EDITED_TIME"),
        "Run": _relation(ids["runs"], "Memory Records"),
        "Supersedes": _relation(ids["memory"]),
    }
    reports = {
        "Name": _property("TITLE"),
        "Report Key": _property("RICH_TEXT"),
        "Run Key": _property("RICH_TEXT"),
        "Integration Key": _property("RICH_TEXT"),
        "Payload Digest": _property("RICH_TEXT"),
        "Rendering Digest": _property("RICH_TEXT"),
        "Body Format": _property("RICH_TEXT"),
        "Report Type": _select("hourly-briefing", "six-hour"),
        "As Of": _property("DATE"),
        "Coverage Start": _property("DATE"),
        "Coverage End": _property("DATE"),
        "Stance": _select("risk-on", "neutral", "defensive", "mixed"),
        "Confidence": _property("NUMBER"),
        "Data Gap Count": _property("NUMBER"),
        "Material Change": _property("CHECKBOX"),
        "User Visible": _property("CHECKBOX"),
        "Created At": _property("CREATED_TIME"),
        "Run": _relation(ids["runs"], "Reports"),
        "Evidence Records": _relation(ids["memory"]),
    }
    return {
        "installations": installations,
        "runs": runs,
        "feed_batches": feed_batches,
        "memory": memory,
        "reports": reports,
    }


def validate_data_source_schema(
    database_key: str,
    actual: dict,
    expected_ids: dict[str, str],
) -> list[str]:
    """Compare one normalized source schema with its exact v2 property contract."""
    errors: list[str] = []
    if database_key not in _DATABASE_KEYS:
        return [f"unknown database key: {database_key}"]
    if not isinstance(expected_ids, dict) or set(expected_ids) != _DATABASE_KEYS:
        return ["expected_ids must contain exactly the five World Memory database keys"]
    for key in sorted(_DATABASE_KEYS):
        error = _uuid_error(expected_ids[key], f"expected_ids[{key!r}]")
        if error:
            errors.append(error)
    if errors:
        return errors
    if not isinstance(actual, dict):
        return ["actual schema must be an object"]
    errors.extend(_keyset_errors(actual, {"properties"}, "actual schema"))
    properties = actual.get("properties")
    if not isinstance(properties, dict):
        errors.append("actual schema properties must be an object")
        return errors
    expected = _expected_data_source_properties(expected_ids)[database_key]
    errors.extend(_keyset_errors(properties, set(expected), database_key))
    for name in sorted(set(expected) & set(properties)):
        observed = properties[name]
        wanted = expected[name]
        prefix = f"{database_key}.{name}"
        if not isinstance(observed, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_keyset_errors(observed, set(wanted), prefix))
        if observed.get("type") != wanted["type"]:
            errors.append(f"{prefix} type must be {wanted['type']}")
        if wanted["type"] == "SELECT" and observed.get("options") != wanted["options"]:
            errors.append(f"{prefix} SELECT options do not match")
        if wanted["type"] == "RELATION":
            if observed.get("target") != wanted["target"]:
                errors.append(f"{prefix} relation target does not match")
            if observed.get("dual_property") != wanted.get("dual_property"):
                errors.append(f"{prefix} DUAL inverse property does not match")
    return errors
