from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import unittest

import world_memory.scheduler as scheduler


FEED_IDS = (
    "financial_juice",
    "walter_bloomberg",
    "wall_st_engine",
    "first_squawk",
    "unusual_whales",
)


def task3_call(name: str, *args, **kwargs):
    function = getattr(scheduler, name, None)
    if function is None:
        raise AssertionError(f"missing Task 3 scheduler API: {name}")
    return function(*args, **kwargs)


def run_policy(*args, **kwargs):
    return task3_call("run_policy", *args, **kwargs)


def effective_last_integration(*args, **kwargs):
    return task3_call("effective_last_integration", *args, **kwargs)


def world_memory_due(*args, **kwargs):
    return task3_call("world_memory_due", *args, **kwargs)


def reconcile_installation_cache(*args, **kwargs):
    return task3_call("reconcile_installation_cache", *args, **kwargs)


def reconstruct_installation_cache(*args, **kwargs):
    return task3_call("reconstruct_installation_cache", *args, **kwargs)


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def installation(**overrides: object) -> dict:
    key = "wm:123e4567-e89b-42d3-a456-426614174000:default"
    value = {
        "page_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "Name": key,
        "Installation Key": key,
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
    value.update(overrides)
    return value


def outcomes(*, failed: tuple[str, ...] = (), suffix: str = "1") -> dict:
    result = {}
    for index, feed_id in enumerate(FEED_IDS, 1):
        if feed_id in failed:
            result[feed_id] = {
                "status": "error", "itemCount": 0, "cursor": "", "error": "timeout",
            }
        else:
            result[feed_id] = {
                "status": "ok",
                "itemCount": index,
                "cursor": f"{index}{suffix}".ljust(64, "0"),
                "error": "",
            }
    return result


def committed_run(
    run_key: str,
    cutoff: str,
    *,
    integration: bool = False,
    integration_key: str = "",
    notification: str = "silent",
    source_outcomes: dict | None = None,
    finished_at: str | None = None,
) -> dict:
    return {
        "Run Key": run_key,
        "Status": "committed",
        "Collection Cutoff": cutoff,
        "Finished At": finished_at or cutoff,
        "Integration Key": integration_key,
        "Integration Performed": integration,
        "Notification Plan": notification,
        "sourceOutcomes": outcomes() if source_outcomes is None else source_outcomes,
    }


ALL_FALSE_ERROR = {
    "action": "setup-required", "reason": "registry-invalid",
    "run": False, "collect": False, "analyze": False,
    "schemaMutation": False, "childMutation": False, "cacheMutation": False,
    "memoryMutation": False, "completeSuggestions": False,
    "notification": "error",
}


class PolicyTests(unittest.TestCase):
    def test_registry_and_installation_fail_closed_for_every_trigger(self):
        missing = {
            **ALL_FALSE_ERROR,
            "reason": "installation-missing",
        }
        for trigger in ("scheduled", "manual", "force-world-memory"):
            with self.subTest(trigger=trigger, case="registry-invalid"):
                self.assertEqual(
                    run_policy(installation(), trigger, registry_valid=False),
                    ALL_FALSE_ERROR,
                )
            with self.subTest(trigger=trigger, case="installation-missing"):
                self.assertEqual(
                    run_policy(None, trigger, registry_valid=True),
                    missing,
                )

    def test_initializing_requires_explicit_direct_setup(self):
        blocked = {
            "action": "setup-required", "reason": "initializing",
            "run": False, "collect": False, "analyze": False,
            "schemaMutation": False, "childMutation": False, "cacheMutation": False,
            "memoryMutation": False, "completeSuggestions": False,
            "notification": "error",
        }
        allowed = {
            "action": "run", "reason": "explicit-setup",
            "run": True, "collect": True, "analyze": True,
            "schemaMutation": False, "childMutation": True, "cacheMutation": True,
            "memoryMutation": True, "completeSuggestions": True,
            "notification": "normal",
        }
        row = installation(Status="initializing")
        for trigger in ("scheduled", "manual", "force-world-memory"):
            with self.subTest(trigger=trigger, explicit=False):
                self.assertEqual(
                    run_policy(row, trigger, registry_valid=True), blocked
                )
        for trigger in ("manual", "force-world-memory"):
            with self.subTest(trigger=trigger, explicit=True):
                self.assertEqual(
                    run_policy(
                        row, trigger, registry_valid=True, explicit_setup=True
                    ),
                    allowed,
                )

    def test_scheduled_explicit_setup_is_invalid_before_other_policy_checks(self):
        with self.assertRaisesRegex(ValueError, "scheduled trigger cannot use explicit setup"):
            run_policy(None, "scheduled", registry_valid=False, explicit_setup=True)
        with self.assertRaisesRegex(ValueError, "scheduled trigger cannot use explicit setup"):
            run_policy(None, "scheduled", registry_valid=1, explicit_setup=True)

    def test_active_and_autopilot_disabled_have_distinct_memory_permissions(self):
        active = {
            "action": "run", "reason": "active",
            "run": True, "collect": True, "analyze": True,
            "schemaMutation": False, "childMutation": True, "cacheMutation": True,
            "memoryMutation": True, "completeSuggestions": True,
            "notification": "normal",
        }
        no_autopilot = {
            **active,
            "reason": "autopilot-disabled",
            "memoryMutation": False,
            "completeSuggestions": False,
        }
        for trigger in ("scheduled", "manual", "force-world-memory"):
            with self.subTest(trigger=trigger, autopilot=True):
                self.assertEqual(
                    run_policy(installation(), trigger, registry_valid=True), active
                )
            with self.subTest(trigger=trigger, autopilot=False):
                self.assertEqual(
                    run_policy(
                        installation(**{"Autopilot Enabled": False}),
                        trigger,
                        registry_valid=True,
                    ),
                    no_autopilot,
                )

    def test_paused_error_and_disabled_scheduled_policies_write_nothing(self):
        cases = (
            (
                installation(Status="paused"),
                {
                    "action": "silent-noop", "reason": "paused",
                    "run": False, "collect": False, "analyze": False,
                    "schemaMutation": False, "childMutation": False,
                    "cacheMutation": False, "memoryMutation": False,
                    "completeSuggestions": False, "notification": "silent",
                },
            ),
            (
                installation(Status="error"),
                {
                    "action": "stored-error", "reason": "stored-error",
                    "run": False, "collect": False, "analyze": False,
                    "schemaMutation": False, "childMutation": False,
                    "cacheMutation": False, "memoryMutation": False,
                    "completeSuggestions": False, "notification": "error",
                },
            ),
            (
                installation(Enabled=False),
                {
                    "action": "silent-noop", "reason": "disabled",
                    "run": False, "collect": False, "analyze": False,
                    "schemaMutation": False, "childMutation": False,
                    "cacheMutation": False, "memoryMutation": False,
                    "completeSuggestions": False, "notification": "silent",
                },
            ),
        )
        for row, expected in cases:
            with self.subTest(reason=expected["reason"]):
                self.assertEqual(
                    run_policy(row, "scheduled", registry_valid=True), expected
                )

    def test_paused_error_and_disabled_direct_calls_are_read_only(self):
        for trigger in ("manual", "force-world-memory"):
            for row, reason, notification in (
                (installation(Status="paused"), "paused", "disabled"),
                (installation(Status="error"), "stored-error", "error"),
                (installation(Enabled=False), "disabled", "disabled"),
            ):
                with self.subTest(trigger=trigger, reason=reason):
                    self.assertEqual(
                        run_policy(row, trigger, registry_valid=True),
                        {
                            "action": "read-only", "reason": reason,
                            "run": True, "collect": True, "analyze": True,
                            "schemaMutation": False, "childMutation": False,
                            "cacheMutation": False, "memoryMutation": False,
                            "completeSuggestions": False,
                            "notification": notification,
                        },
                    )

    def test_structural_fields_and_trigger_are_strict(self):
        invalid_rows = (
            installation(Status="unknown"),
            {key: value for key, value in installation().items() if key != "Status"},
            installation(Enabled=1),
            installation(**{"Autopilot Enabled": 1}),
            installation(Status="unknown", Enabled=False),
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    run_policy(row, "manual", registry_valid=True)
        with self.assertRaisesRegex(ValueError, "unsupported trigger"):
            run_policy(installation(), "surprise", registry_valid=True)
        for field, value in (("registry_valid", 1), ("explicit_setup", 1)):
            with self.subTest(field=field):
                arguments = {"registry_valid": True, "explicit_setup": False}
                arguments[field] = value
                with self.assertRaisesRegex(ValueError, "must be a boolean"):
                    run_policy(installation(), "manual", **arguments)


class IntegrationGateTests(unittest.TestCase):
    def test_committed_integration_cutoff_overrides_older_or_newer_cache(self):
        row = committed_run(
            "run-integration", "2026-08-10T06:00:00Z",
            integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
        )
        for cached in ("2026-08-09T00:00:00Z", "2026-08-11T00:00:00Z"):
            with self.subTest(cached=cached):
                self.assertEqual(
                    effective_last_integration(
                        installation(**{"Last World Memory Success": cached}), [row]
                    ),
                    "2026-08-10T06:00:00Z",
                )

    def test_report_only_run_does_not_advance_integration_cutoff(self):
        report_only = committed_run(
            "run-report", "2026-08-10T08:00:00Z",
            notification="hourly-briefing",
        )
        self.assertEqual(
            effective_last_integration(
                installation(**{"Last World Memory Success": "2026-08-10T01:00:00Z"}),
                [report_only],
            ),
            "",
        )

    def test_due_uses_five_hours_forty_five_minutes_for_nominal_six_hour_gate(self):
        row = committed_run(
            "run-integration", "2026-08-10T06:00:00Z",
            integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
        )
        current = installation()
        self.assertTrue(world_memory_due(current, [], utc("2026-08-10T00:00:00Z"), "manual"))
        self.assertFalse(world_memory_due(current, [row], utc("2026-08-10T11:44:59Z"), "scheduled"))
        self.assertTrue(world_memory_due(current, [row], utc("2026-08-10T11:45:00Z"), "scheduled"))
        self.assertTrue(world_memory_due(current, [row], utc("2026-08-10T12:00:00Z"), "manual"))
        self.assertTrue(world_memory_due(current, [row], utc("2026-08-10T06:01:00Z"), "force-world-memory"))

    def test_due_rejects_naive_now_future_cutoff_and_non_six_hour_installation(self):
        future = committed_run(
            "run-future", "2026-08-10T07:00:00Z",
            integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            world_memory_due(installation(), [], datetime(2026, 8, 10), "manual")
        with self.assertRaisesRegex(ValueError, "future"):
            world_memory_due(
                installation(), [future], utc("2026-08-10T06:00:00Z"),
                "force-world-memory",
            )
        with self.assertRaisesRegex(ValueError, "exactly 6"):
            world_memory_due(
                installation(**{"World Memory Interval Hours": 5}), [],
                utc("2026-08-10T06:00:00Z"), "manual",
            )

    def test_malformed_or_duplicate_committed_integration_rows_raise(self):
        first = committed_run(
            "run-1", "2026-08-10T00:00:00Z", integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
        )
        duplicate = committed_run(
            "run-2", "2026-08-10T06:00:00Z", integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
        )
        with self.assertRaisesRegex(ValueError, "duplicate committed Integration Key"):
            effective_last_integration(installation(), [first, duplicate])
        malformed = {**first, "Collection Cutoff": "not-a-time"}
        with self.assertRaisesRegex(ValueError, "Collection Cutoff"):
            effective_last_integration(installation(), [malformed])
        wrong_installation = {**first, "Integration Key": "wmi_000000000000_genesis"}
        with self.assertRaisesRegex(ValueError, "Installation Key"):
            effective_last_integration(installation(), [wrong_installation])
        wrong_boolean = {**first, "Integration Performed": 1}
        with self.assertRaisesRegex(ValueError, "Integration Performed"):
            effective_last_integration(installation(), [wrong_boolean])
        unhashable_status = {**first, "Status": []}
        with self.assertRaisesRegex(ValueError, "Status"):
            effective_last_integration(installation(), [unhashable_status])


class CacheReconciliationTests(unittest.TestCase):
    def test_reconstruction_replays_committed_authority_from_empty_cache(self):
        current = installation(**{
            "Feed Cursor State": {"financial_juice": "f" * 64},
            "Last Feed Attempt": "2026-08-11T00:00:00Z",
            "Last Feed Success": "2026-08-11T00:00:00Z",
            "Last World Memory Success": "2026-08-11T00:00:00Z",
            "Last Report Success": "2026-08-11T00:00:00Z",
            "Next World Memory At": "2026-08-11T06:00:00Z",
            "Last Briefing At": "2026-08-11T00:00:00Z",
            "Last Error": "poisoned cache",
        })
        older = committed_run(
            "run-old", "2026-08-10T01:00:00Z",
            source_outcomes=outcomes(
                failed=("walter_bloomberg",), suffix="3"
            ),
        )
        latest = committed_run(
            "run-latest", "2026-08-10T02:00:00Z",
            integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
            notification="six-hour",
            source_outcomes=outcomes(
                failed=("financial_juice",), suffix="4"
            ),
            finished_at="2026-08-10T02:04:00Z",
        )
        superseded = {
            "Run Key": "run-bad",
            "Status": "superseded",
        }
        inputs_before = deepcopy((current, [latest, superseded, older]))

        rebuilt = reconstruct_installation_cache(
            current, [latest, superseded, older]
        )

        self.assertEqual(
            rebuilt["Feed Cursor State"]["financial_juice"],
            "1300000000000000000000000000000000000000000000000000000000000000",
        )
        self.assertEqual(
            rebuilt["Feed Cursor State"]["walter_bloomberg"],
            "2400000000000000000000000000000000000000000000000000000000000000",
        )
        self.assertEqual(rebuilt["Last Feed Attempt"], "2026-08-10T02:00:00Z")
        self.assertEqual(rebuilt["Last Feed Success"], "2026-08-10T02:00:00Z")
        self.assertEqual(
            rebuilt["Last World Memory Success"], "2026-08-10T02:00:00Z"
        )
        self.assertEqual(rebuilt["Next World Memory At"], "2026-08-10T08:00:00Z")
        self.assertEqual(rebuilt["Last Report Success"], "2026-08-10T02:04:00Z")
        self.assertEqual(rebuilt["Last Briefing At"], "")
        self.assertEqual(rebuilt["Last Error"], "financial_juice: timeout")
        self.assertEqual(rebuilt["Installation Key"], current["Installation Key"])
        self.assertEqual((current, [latest, superseded, older]), inputs_before)

    def test_partial_sources_preserve_failed_cursor_and_advance_successes(self):
        current = installation(**{
            "Feed Cursor State": {
                "financial_juice": "a" * 64,
                "walter_bloomberg": "b" * 64,
            },
        })
        partial = committed_run(
            "run-partial", "2026-08-10T02:00:00Z",
            source_outcomes=outcomes(failed=("walter_bloomberg",), suffix="9"),
        )
        updated = reconcile_installation_cache(current, partial, [partial])
        self.assertEqual(updated["Feed Cursor State"]["financial_juice"], "1900000000000000000000000000000000000000000000000000000000000000")
        self.assertEqual(updated["Feed Cursor State"]["walter_bloomberg"], "b" * 64)
        self.assertEqual(updated["Last Feed Attempt"], "2026-08-10T02:00:00Z")
        self.assertEqual(updated["Last Feed Success"], "2026-08-10T02:00:00Z")
        self.assertEqual(updated["Last Error"], "walter_bloomberg: timeout")

    def test_failed_or_nonauthoritative_candidate_returns_exact_current_copy(self):
        current = installation(**{"Last Feed Success": "2026-08-10T01:00:00Z"})
        failed = committed_run(
            "run-failed-sources", "2026-08-10T02:00:00Z",
            source_outcomes=outcomes(failed=FEED_IDS),
        )
        failed["Status"] = "failed"
        success = committed_run("run-success", "2026-08-10T03:00:00Z")
        for candidate, authority in ((failed, [success]), (success, [])):
            with self.subTest(run_key=candidate["Run Key"]):
                self.assertEqual(
                    reconcile_installation_cache(current, candidate, authority), current
                )

    def test_committed_all_source_failed_snapshot_is_corrupt(self):
        corrupt = committed_run(
            "run-corrupt", "2026-08-10T02:00:00Z",
            source_outcomes=outcomes(failed=FEED_IDS),
        )
        with self.assertRaisesRegex(ValueError, "all sources failed"):
            reconcile_installation_cache(installation(), corrupt, [corrupt])

    def test_complete_authority_not_candidate_age_controls_forward_and_backward_repair(self):
        current = installation(**{
            "Feed Cursor State": {"financial_juice": "f" * 64},
            "Last Feed Attempt": "2026-08-11T00:00:00Z",
            "Last Feed Success": "2026-08-11T00:00:00Z",
        })
        older = committed_run("run-old", "2026-08-10T01:00:00Z", source_outcomes=outcomes(suffix="3"))
        newer = committed_run("run-new", "2026-08-10T02:00:00Z", source_outcomes=outcomes(suffix="4"))
        repaired = reconcile_installation_cache(current, older, [newer, older])
        self.assertEqual(repaired["Last Feed Attempt"], "2026-08-10T02:00:00Z")
        self.assertEqual(repaired["Last Feed Success"], "2026-08-10T02:00:00Z")
        self.assertEqual(repaired["Feed Cursor State"]["financial_juice"], "1400000000000000000000000000000000000000000000000000000000000000")

    def test_integration_report_briefing_and_partial_error_cache_are_derived(self):
        partial = committed_run(
            "run-1", "2026-08-10T01:00:00Z",
            source_outcomes=outcomes(failed=("first_squawk",)),
        )
        integration = committed_run(
            "run-2", "2026-08-10T02:00:00Z", integration=True,
            integration_key="wmi_b12ee94ad696_genesis",
            notification="six-hour", finished_at="2026-08-10T02:04:00Z",
        )
        briefing = committed_run(
            "run-3", "2026-08-10T03:00:00Z",
            notification="hourly-briefing", finished_at="2026-08-10T03:02:00Z",
        )
        updated = reconcile_installation_cache(
            installation(), briefing, [briefing, partial, integration]
        )
        self.assertEqual(updated["Last World Memory Success"], "2026-08-10T02:00:00Z")
        self.assertEqual(updated["Next World Memory At"], "2026-08-10T08:00:00Z")
        self.assertEqual(updated["Last Report Success"], "2026-08-10T03:02:00Z")
        self.assertEqual(updated["Last Briefing At"], "2026-08-10T03:02:00Z")
        self.assertEqual(updated["Last Error"], "first_squawk: timeout")

    def test_duplicate_or_malformed_authoritative_run_snapshots_raise(self):
        row = committed_run("run-1", "2026-08-10T01:00:00Z")
        with self.assertRaisesRegex(ValueError, "duplicate Run Key"):
            reconcile_installation_cache(installation(), row, [row, deepcopy(row)])
        malformed = {**row, "sourceOutcomes": {"unknown": outcomes()["financial_juice"]}}
        with self.assertRaisesRegex(ValueError, "sourceOutcomes"):
            reconcile_installation_cache(installation(), malformed, [malformed])

    def test_unhashable_cache_enums_raise_value_errors(self):
        row = committed_run("run-1", "2026-08-10T01:00:00Z")
        cases = (
            ("Status", {**row, "Status": []}, "Status"),
            ("Notification Plan", {**row, "Notification Plan": []}, "Notification Plan"),
            (
                "outcome status",
                {
                    **row,
                    "sourceOutcomes": {
                        **row["sourceOutcomes"],
                        "financial_juice": {
                            **row["sourceOutcomes"]["financial_juice"],
                            "status": [],
                        },
                    },
                },
                "status",
            ),
        )
        for name, malformed, message in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, message):
                    reconcile_installation_cache(installation(), malformed, [malformed])

    def test_candidate_all_supplied_fields_must_match_authoritative_snapshot(self):
        authority = {
            **committed_run("run-1", "2026-08-10T01:00:00Z"),
            "Output Digest": "a" * 64,
            "Unrelated Notion Field": "authority-only",
        }
        matching_candidate = {
            key: value
            for key, value in authority.items()
            if key != "Unrelated Notion Field"
        }
        current = installation()
        authoritative_runs = [authority]
        inputs_before = deepcopy((current, matching_candidate, authoritative_runs))
        self.assertEqual(
            reconcile_installation_cache(
                current, matching_candidate, authoritative_runs
            )["Last Feed Success"],
            "2026-08-10T01:00:00Z",
        )
        self.assertEqual(
            (current, matching_candidate, authoritative_runs), inputs_before
        )

        divergent = {**matching_candidate, "Output Digest": "b" * 64}
        with self.assertRaisesRegex(ValueError, "Output Digest"):
            reconcile_installation_cache(installation(), divergent, [authority])

        absent_from_authority = {**matching_candidate, "Cache Reconciled": False}
        with self.assertRaisesRegex(ValueError, "Cache Reconciled"):
            reconcile_installation_cache(
                installation(), absent_from_authority, [authority]
            )


if __name__ == "__main__":
    unittest.main()
