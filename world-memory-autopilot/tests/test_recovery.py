from __future__ import annotations

from copy import deepcopy
import unittest

from world_memory import storage

from tests.test_task5_hardening import (
    feed_page,
    feed_payload,
    installation,
    parent_run,
    run_audit,
)


def eligible_bundle() -> dict:
    payload = feed_payload(fetched_at="2026-08-10T02:00:11Z")
    feed, _expected = feed_page(payload)
    feed["Fetched At"] = "2026-08-10T02:00:00Z"
    run = parent_run(
        Status="committed",
        **{
            "Integration Key": "",
            "Finished At": "2026-08-10T02:04:00Z",
            "Material Change": False,
            "Integration Due": False,
            "Integration Performed": False,
            "Cache Reconciled": False,
            "Notification Plan": "silent",
            "body": storage.encode_notion_body(run_audit(feed)),
        },
    )
    return {
        "explicitApproval": True,
        "invocation": "manual",
        "installation": installation(),
        "targetRun": run,
        "slotRows": [deepcopy(run)],
        "exactRunRows": [deepcopy(run)],
        "authoritativeRuns": [deepcopy(run)],
        "feedRows": [feed],
        "memoryRows": [],
        "reportRows": [],
    }


class RecoveryPlannerTests(unittest.TestCase):
    def test_exact_fixture_emits_status_only_plan(self):
        planner = getattr(storage, "plan_run_supersession", None)
        self.assertIsNotNone(planner, "run supersession planner is missing")
        bundle = eligible_bundle()
        before = deepcopy(bundle)

        result = planner(bundle)

        self.assertEqual(
            result,
            {
                "action": "supersede-run",
                "reason": "feed-fetched-at-property-payload-mismatch",
                "runPageId": bundle["targetRun"]["page_id"],
                "runKey": bundle["targetRun"]["Run Key"],
                "expectedStatus": "committed",
                "nextStatus": "superseded",
                "propertyUpdates": {"Status": "superseded"},
                "cacheRepairRequired": True,
            },
        )
        self.assertEqual(bundle, before)

    def test_ineligible_or_ambiguous_repairs_are_blocked(self):
        planner = storage.plan_run_supersession

        def target_change(bundle: dict, **changes: object) -> None:
            bundle["targetRun"].update(changes)
            for field in ("slotRows", "exactRunRows", "authoritativeRuns"):
                bundle[field][0] = deepcopy(bundle["targetRun"])

        cases = []

        no_approval = eligible_bundle()
        no_approval["explicitApproval"] = False
        cases.append(("approval", no_approval))

        scheduled = eligible_bundle()
        scheduled["invocation"] = "scheduled"
        cases.append(("scheduled", scheduled))

        drift = eligible_bundle()
        drift["installation"]["Hourly Interval Minutes"] = 30
        cases.append(("installation", drift))

        duplicate = eligible_bundle()
        duplicate["slotRows"].append(deepcopy(duplicate["targetRun"]))
        cases.append(("duplicate", duplicate))

        for field, value in (
            ("Status", "failed"),
            ("Integration Due", True),
            ("Integration Performed", True),
            ("Integration Key", "wmi_b12ee94ad696_genesis"),
            ("Material Change", True),
            ("Output Prepared", False),
            ("Cache Reconciled", True),
            ("Notification Plan", "hourly-briefing"),
        ):
            bundle = eligible_bundle()
            target_change(bundle, **{field: value})
            cases.append((field, bundle))

        multipart = eligible_bundle()
        multipart["feedRows"][0]["Part Count"] = 2
        cases.append(("multipart", multipart))

        memory = eligible_bundle()
        memory["memoryRows"] = [{"page_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"}]
        cases.append(("memory", memory))

        report = eligible_bundle()
        report["reportRows"] = [{"page_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}]
        cases.append(("report", report))

        bad_audit = eligible_bundle()
        target_change(bad_audit, body="not canonical")
        cases.append(("audit", bad_audit))

        bad_feed = eligible_bundle()
        bad_feed["feedRows"][0]["Payload Digest"] = "f" * 64
        cases.append(("feed corruption", bad_feed))

        no_mismatch = eligible_bundle()
        no_mismatch["feedRows"][0]["Fetched At"] = "2026-08-10T02:00:11Z"
        cases.append(("no mismatch", no_mismatch))

        later = eligible_bundle()
        later_run = deepcopy(later["targetRun"])
        later_run.update({
            "page_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
            "Run Key": "run-later",
            "Collection Cutoff": "2026-08-10T03:00:00Z",
        })
        later["authoritativeRuns"].append(later_run)
        cases.append(("later authority", later))

        for label, bundle in cases:
            with self.subTest(label=label):
                result = planner(bundle)
                self.assertEqual(result["action"], "blocked")
                self.assertTrue(result["errors"])

    def test_readback_verifier_allows_only_status_and_system_updated_at(self):
        verifier = getattr(storage, "verify_run_supersession_readback", None)
        self.assertIsNotNone(verifier, "supersession read-back verifier is missing")
        bundle = eligible_bundle()
        before = deepcopy(bundle["targetRun"])
        after = deepcopy(before)
        after["Status"] = "superseded"
        after["Updated At"] = "2026-08-10T04:30:00.392Z"
        feed_before = deepcopy(bundle["feedRows"][0])

        self.assertEqual(
            verifier(
                before, after, feed_before, deepcopy(feed_before)
            ),
            [],
        )

        changed_run = deepcopy(after)
        changed_run["Notification Plan"] = "error"
        self.assertTrue(
            verifier(
                before, changed_run, feed_before, deepcopy(feed_before)
            )
        )

        changed_feed = deepcopy(feed_before)
        changed_feed["Fetched At"] = "2026-08-10T02:00:05Z"
        self.assertTrue(
            verifier(
                before, after, feed_before, changed_feed
            )
        )


if __name__ == "__main__":
    unittest.main()
