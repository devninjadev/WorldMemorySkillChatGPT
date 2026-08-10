import unittest

from world_memory.contracts import (
    is_utc_iso,
    validate_audit,
    validate_data_source_schema,
    validate_feed_row,
    validate_registry,
    validate_report,
    validate_suggestions,
    validate_world_event,
    validate_world_state,
)


WORKSPACE_ID = "123e4567-e89b-42d3-a456-426614174000"
DATA_SOURCE_IDS = {
    "installations": "11111111-1111-4111-8111-111111111111",
    "runs": "22222222-2222-4222-8222-222222222222",
    "feed_batches": "33333333-3333-4333-8333-333333333333",
    "memory": "44444444-4444-4444-8444-444444444444",
    "reports": "55555555-5555-4555-8555-555555555555",
}


def valid_registry() -> dict:
    sources = {}
    database_ids = (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
    )
    for index, key in enumerate(DATA_SOURCE_IDS):
        sources[key] = {
            "database_id": database_ids[index],
            "data_source_id": DATA_SOURCE_IDS[key],
            "url": f"https://www.notion.so/{key}",
        }
    return {
        "world_memory": {
            "skill": "world-memory-autopilot",
            "installation_key": "wm:123e4567-e89b-42d3-a456-426614174000:default",
            "notion_workspace_id": WORKSPACE_ID,
            "hub_page_id": "99999999-9999-4999-8999-999999999999",
            "hub_url": "https://www.notion.so/world-memory-hub",
            "schema_version": 2,
            "skill_contract_version": "notion-v2",
            "bootstrap_allowed": False,
            "scheduled_schema_mutation_allowed": False,
            "data_sources": sources,
        }
    }


def field(property_type: str, options: list[str] | None = None) -> dict:
    value = {"type": property_type}
    if options is not None:
        value["options"] = options
    return value


def relation(target: str, dual_property: str | None = None) -> dict:
    value = {"type": "RELATION", "target": target}
    if dual_property is not None:
        value["dual_property"] = dual_property
    return value


def normalized_schemas() -> dict[str, dict]:
    installations = {
        "Name": field("TITLE"),
        "Installation Key": field("RICH_TEXT"),
        "Hub Page ID": field("RICH_TEXT"),
        "Hub URL": field("URL"),
        "Status": field("SELECT", ["initializing", "active", "paused", "error"]),
        "Enabled": field("CHECKBOX"),
        "Autopilot Enabled": field("CHECKBOX"),
        "Timezone": field("SELECT", ["Asia/Seoul"]),
        "Hourly Interval Minutes": field("NUMBER"),
        "World Memory Interval Hours": field("NUMBER"),
        "Schema Version": field("NUMBER"),
        "Skill Contract Version": field("RICH_TEXT"),
        "Feed Cursor State": field("RICH_TEXT"),
        "Last Feed Attempt": field("DATE"),
        "Last Feed Success": field("DATE"),
        "Last World Memory Success": field("DATE"),
        "Last Report Success": field("DATE"),
        "Next World Memory At": field("DATE"),
        "Last Briefing At": field("DATE"),
        "Last Error": field("RICH_TEXT"),
        "Created At": field("CREATED_TIME"),
        "Updated At": field("LAST_EDITED_TIME"),
        "Runs": relation(DATA_SOURCE_IDS["runs"], "Installation"),
    }
    runs = {
        "Name": field("TITLE"),
        "Slot Key": field("RICH_TEXT"),
        "Run Key": field("RICH_TEXT"),
        "Integration Key": field("RICH_TEXT"),
        "Attempt": field("NUMBER"),
        "Trigger": field("SELECT", ["scheduled", "manual", "force-world-memory"]),
        "Status": field("SELECT", ["preparing", "committed", "failed", "superseded"]),
        "Started At": field("DATE"),
        "Scheduled Slot": field("DATE"),
        "Collection Cutoff": field("DATE"),
        "Finished At": field("DATE"),
        "Feed Success Count": field("NUMBER"),
        "Feed Failure Count": field("NUMBER"),
        "New Item Count": field("NUMBER"),
        "Material Change": field("CHECKBOX"),
        "Integration Due": field("CHECKBOX"),
        "Integration Performed": field("CHECKBOX"),
        "Output Prepared": field("CHECKBOX"),
        "Cache Reconciled": field("CHECKBOX"),
        "Notification Plan": field("SELECT", ["silent", "hourly-briefing", "six-hour", "error"]),
        "Input Digest": field("RICH_TEXT"),
        "Output Digest": field("RICH_TEXT"),
        "Error Summary": field("RICH_TEXT"),
        "Created At": field("CREATED_TIME"),
        "Updated At": field("LAST_EDITED_TIME"),
        "Installation": relation(DATA_SOURCE_IDS["installations"], "Runs"),
        "Feed Batches": relation(DATA_SOURCE_IDS["feed_batches"], "Run"),
        "Memory Records": relation(DATA_SOURCE_IDS["memory"], "Run"),
        "Reports": relation(DATA_SOURCE_IDS["reports"], "Run"),
    }
    feed_batches = {
        "Name": field("TITLE"),
        "Batch Key": field("RICH_TEXT"),
        "Run Key": field("RICH_TEXT"),
        "Payload Digest": field("RICH_TEXT"),
        "Fingerprint Window Digest": field("RICH_TEXT"),
        "Body Format": field("RICH_TEXT"),
        "Part Index": field("NUMBER"),
        "Part Count": field("NUMBER"),
        "Feed Success Count": field("NUMBER"),
        "Feed Failure Count": field("NUMBER"),
        "New Item Count": field("NUMBER"),
        "Item Count": field("NUMBER"),
        "Fetched At": field("DATE"),
        "All Sources Failed": field("CHECKBOX"),
        "Created At": field("CREATED_TIME"),
        "Run": relation(DATA_SOURCE_IDS["runs"], "Feed Batches"),
    }
    memory = {
        "Name": field("TITLE"),
        "Record Key": field("RICH_TEXT"),
        "Revision Key": field("RICH_TEXT"),
        "Run Key": field("RICH_TEXT"),
        "Dedupe Key": field("RICH_TEXT"),
        "Continuity ID": field("RICH_TEXT"),
        "Target": field("RICH_TEXT"),
        "Payload Digest": field("RICH_TEXT"),
        "Body Format": field("RICH_TEXT"),
        "Record Type": field("SELECT", ["brief", "state", "story-link", "taxonomy", "suggestion"]),
        "Record Status": field("SELECT", ["active", "open", "watching", "completed"]),
        "Importance": field("SELECT", ["high", "medium", "low"]),
        "Category": field("SELECT", ["stock_bond", "geopolitics", "emerging"]),
        "Region": field("SELECT", ["US", "KR", "GLOBAL"]),
        "Action": field("SELECT", [
            "brief-add", "state-add", "state-supersede", "story-link",
            "taxonomy-refresh", "suggestion-status-update", "investigate",
        ]),
        "Revision": field("NUMBER"),
        "Confidence": field("NUMBER"),
        "Effective At": field("DATE"),
        "Verified Evidence": field("CHECKBOX"),
        "Created At": field("CREATED_TIME"),
        "Updated At": field("LAST_EDITED_TIME"),
        "Run": relation(DATA_SOURCE_IDS["runs"], "Memory Records"),
        "Supersedes": relation(DATA_SOURCE_IDS["memory"]),
    }
    reports = {
        "Name": field("TITLE"),
        "Report Key": field("RICH_TEXT"),
        "Run Key": field("RICH_TEXT"),
        "Integration Key": field("RICH_TEXT"),
        "Payload Digest": field("RICH_TEXT"),
        "Rendering Digest": field("RICH_TEXT"),
        "Body Format": field("RICH_TEXT"),
        "Report Type": field("SELECT", ["hourly-briefing", "six-hour"]),
        "As Of": field("DATE"),
        "Coverage Start": field("DATE"),
        "Coverage End": field("DATE"),
        "Stance": field("SELECT", ["risk-on", "neutral", "defensive", "mixed"]),
        "Confidence": field("NUMBER"),
        "Data Gap Count": field("NUMBER"),
        "Material Change": field("CHECKBOX"),
        "User Visible": field("CHECKBOX"),
        "Created At": field("CREATED_TIME"),
        "Run": relation(DATA_SOURCE_IDS["runs"], "Reports"),
        "Evidence Records": relation(DATA_SOURCE_IDS["memory"]),
    }
    return {
        "installations": {"properties": installations},
        "runs": {"properties": runs},
        "feed_batches": {"properties": feed_batches},
        "memory": {"properties": memory},
        "reports": {"properties": reports},
    }


class RegistryTests(unittest.TestCase):
    def test_exact_project_registry_is_valid(self):
        self.assertEqual(validate_registry(valid_registry()), [])

    def test_registry_rejects_missing_or_extra_database_key(self):
        missing = valid_registry()
        missing["world_memory"]["data_sources"].pop("reports")
        extra = valid_registry()
        extra["world_memory"]["data_sources"]["other"] = {
            "database_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "data_source_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "url": "https://www.notion.so/other",
        }
        for registry in (missing, extra):
            with self.subTest(registry=registry):
                self.assertTrue(validate_registry(registry))

    def test_registry_rejects_non_uuid_ids_and_mismatched_installation_key(self):
        invalid_id = valid_registry()
        invalid_id["world_memory"]["data_sources"]["memory"]["data_source_id"] = "not-a-uuid"
        mismatched = valid_registry()
        mismatched["world_memory"]["installation_key"] = "wm:wrong:default"
        for registry in (invalid_id, mismatched):
            with self.subTest(registry=registry):
                self.assertTrue(validate_registry(registry))

    def test_registry_rejects_wrong_versions_and_true_bootstrap_flags(self):
        mutations = (
            ("schema_version", 1),
            ("schema_version", 2.0),
            ("skill_contract_version", "obsolete-v1"),
            ("bootstrap_allowed", True),
            ("scheduled_schema_mutation_allowed", True),
        )
        for field_name, value in mutations:
            registry = valid_registry()
            registry["world_memory"][field_name] = value
            with self.subTest(field=field_name):
                self.assertTrue(validate_registry(registry))

    def test_registry_rejects_extra_keys_at_every_level_and_non_http_url(self):
        outer = valid_registry()
        outer["extra"] = True
        inner = valid_registry()
        inner["world_memory"]["extra"] = True
        source = valid_registry()
        source["world_memory"]["data_sources"]["runs"]["extra"] = True
        mixed_keys = valid_registry()
        mixed_keys["extra"] = True
        mixed_keys[7] = True
        bad_url = valid_registry()
        bad_url["world_memory"]["hub_url"] = "not-a-url"
        for registry in (outer, inner, source, mixed_keys, bad_url):
            with self.subTest(registry=registry):
                self.assertTrue(validate_registry(registry))


class DataSourceSchemaTests(unittest.TestCase):
    def test_every_normalized_data_source_schema_is_exact(self):
        for key, actual in normalized_schemas().items():
            with self.subTest(database=key):
                self.assertEqual(validate_data_source_schema(key, actual, DATA_SOURCE_IDS), [])

    def test_schema_rejects_missing_property(self):
        actual = normalized_schemas()["runs"]
        actual["properties"].pop("Run Key")
        self.assertTrue(validate_data_source_schema("runs", actual, DATA_SOURCE_IDS))

    def test_schema_rejects_wrong_select_option(self):
        actual = normalized_schemas()["memory"]
        actual["properties"]["Importance"]["options"] = ["critical", "medium", "low"]
        self.assertTrue(validate_data_source_schema("memory", actual, DATA_SOURCE_IDS))

    def test_schema_rejects_dual_where_one_way_is_required(self):
        for database_key, property_name, inverse in (
            ("memory", "Supersedes", "Superseded By"),
            ("reports", "Evidence Records", "Reports"),
        ):
            actual = normalized_schemas()[database_key]
            actual["properties"][property_name]["dual_property"] = inverse
            with self.subTest(database=database_key, property=property_name):
                self.assertTrue(validate_data_source_schema(database_key, actual, DATA_SOURCE_IDS))

    def test_schema_rejects_wrong_relation_target_and_inverse_name(self):
        wrong_target = normalized_schemas()["feed_batches"]
        wrong_target["properties"]["Run"]["target"] = DATA_SOURCE_IDS["memory"]
        wrong_inverse = normalized_schemas()["installations"]
        wrong_inverse["properties"]["Runs"]["dual_property"] = "Wrong"
        self.assertTrue(validate_data_source_schema("feed_batches", wrong_target, DATA_SOURCE_IDS))
        self.assertTrue(validate_data_source_schema("installations", wrong_inverse, DATA_SOURCE_IDS))


class PayloadContractTests(unittest.TestCase):
    def test_utc_validator_accepts_empty_or_utc_and_rejects_other_forms(self):
        self.assertTrue(is_utc_iso(""))
        self.assertTrue(is_utc_iso("2026-08-09T03:00:00Z"))
        for value in ("2026-08-09Z", "2026-08-09 03:00:00Z", "2026-08-09T12:00:00+09:00"):
            with self.subTest(value=value):
                self.assertFalse(is_utc_iso(value))

    def test_feed_row_rejects_noncanonical_source_and_fingerprint_id_mismatch(self):
        row = {
            "schemaVersion": 1,
            "id": "nf_abcdefabcdefabcdef",
            "sourceFingerprint": "a" * 64,
            "feedId": "financial_juice",
            "feedTitle": "FinancialJuice",
            "feedSourceUrl": "https://wrong.example/rss.xml",
            "sourceUrl": "https://example.com/item",
            "title": "Headline",
            "sourcePublishedAt": "2026-08-09T03:00:00Z",
            "publishedAt": "2026-08-09T03:00:00Z",
            "publishedAtOffsetMinutes": 0,
            "fetchedAt": "2026-08-09T03:01:00Z",
            "status": "queued",
            "importanceCandidate": "unassessed",
        }
        errors = validate_feed_row(row)
        self.assertIn("feed source metadata must match configured source", errors)
        self.assertIn("id must be nf_ plus the first 18 sourceFingerprint characters", errors)
        self.assertIn("status must be pending or processed", errors)

    def test_world_event_and_brief_validation_remain_storage_neutral(self):
        event = {
            "schema_version": 1, "entry_type": "world_issue", "event_id": "evt_1",
            "logged_at": "2026-08-09T03:00:00Z", "as_of": "2026-08-09T03:00:00Z",
            "date": "2026-08-09", "category": "emerging", "region": "GLOBAL",
            "importance": "medium", "entry_mode": "brief", "dedupe_key": "x",
            "title": "x", "summary": "x", "sources": [],
        }
        self.assertIn(
            "brief requires subjects, industries, or event_kind",
            validate_world_event(event),
        )

    def test_world_state_rejects_malformed_state_story_and_taxonomy(self):
        state = {
            "schemaVersion": 1,
            "states": [{"state_id": "only-one-field", "confidence": 2}],
            "storyLinks": ["not-an-object"],
            "taxonomy": [],
            "updatedAt": "",
        }
        errors = validate_world_state(state)
        self.assertIn("states[0].state_key must be a string", errors)
        self.assertIn("states[0].confidence must be between 0 and 1", errors)
        self.assertIn("storyLinks[0] must be an object", errors)
        self.assertIn("taxonomy must be an object", errors)

    def test_suggestions_reject_shell_and_completed_read_only_action(self):
        suggestions = {
            "schemaVersion": 1,
            "items": [{
                "continuityId": "", "text": "Run command", "status": "completed",
                "action": "shell", "target": "rm -rf", "evidence": [],
                "confidence": 0.5, "handledAt": "",
            }],
            "updatedAt": "",
        }
        errors = validate_suggestions(suggestions)
        self.assertIn("items[0].action is not allowlisted", errors)
        self.assertIn("items[0].status completed requires a mutation action", errors)

    def test_report_rejects_overlong_radar_and_malformed_sources(self):
        report = {
            "schemaVersion": 1,
            "title": "Report", "asOf": "", "coverage": {},
            "dataQuality": {"gaps": [1]}, "stance": "neutral", "confidence": 0.5,
            "changesSincePrevious": [], "signalRadar": [{} for _ in range(9)],
            "highlights": [], "memoryChangeSuggestions": [], "portfolioSuggestions": [],
            "nextChecks": [], "sources": [{"name": "", "url": 5}],
        }
        errors = validate_report(report)
        self.assertIn("dataQuality.gaps[0] must be a string", errors)
        self.assertIn("signalRadar must contain at most 8 items", errors)
        self.assertIn("signalRadar[0] must contain a non-empty string field", errors)
        self.assertIn("sources[0].name must be a non-empty string", errors)

    def test_report_v2_requires_three_complete_scenarios(self):
        report = {
            "schemaVersion": 2,
            "title": "World Memory", "asOf": "2026-08-10T02:00:00Z", "coverage": "6h",
            "dataQuality": {"gaps": []}, "stance": "neutral", "confidence": 0.7,
            "summary": "요약", "narrative": "서사", "changesSincePrevious": [],
            "signalRadar": [], "highlights": [], "memoryChangeSuggestions": [],
            "portfolioSuggestions": [], "nextChecks": [], "sources": [],
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
        self.assertEqual(validate_report(report), [])
        missing = {**report, "scenarios": {key: value for key, value in report["scenarios"].items() if key != "비관"}}
        empty = {
            **report,
            "scenarios": {
                **report["scenarios"],
                "낙관": {**report["scenarios"]["낙관"], "transmission": ""},
            },
        }
        extra = {**report, "scenarios": {**report["scenarios"], "중립": report["scenarios"]["기준"]}}
        for name, invalid in (("missing", missing), ("empty", empty), ("extra", extra)):
            with self.subTest(name=name):
                self.assertTrue(validate_report(invalid))

    def test_report_v1_is_rejected_after_notion_v2_migration(self):
        report = {
            "schemaVersion": 1,
            "title": "Legacy", "asOf": "", "coverage": "", "dataQuality": {"gaps": []},
            "stance": "neutral", "confidence": 0.5, "summary": "", "narrative": "",
            "changesSincePrevious": [], "signalRadar": [], "highlights": [],
            "memoryChangeSuggestions": [], "portfolioSuggestions": [], "nextChecks": [],
            "sources": [],
        }
        errors = validate_report(report)
        self.assertIn("schemaVersion must be 2", errors)
        self.assertIn("missing required key: scenarios", errors)

    def test_audit_rejects_empty_object_without_run_sections(self):
        errors = validate_audit({})
        self.assertIn("timestamp must be UTC ISO 8601", errors)
        self.assertIn("trigger must be scheduled, manual, or force-world-memory", errors)
        self.assertIn("feed must be an object", errors)
        self.assertIn("commit must be an object", errors)


if __name__ == "__main__":
    unittest.main()
