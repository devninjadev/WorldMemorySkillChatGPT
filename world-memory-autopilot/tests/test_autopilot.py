import unittest

from world_memory.autopilot import normalize_suggestion, validate_action


class AutopilotTests(unittest.TestCase):
    def test_allowed_mutation_passes(self):
        self.assertEqual(validate_action({"action": "state-add", "target": "inflation_us"}), [])

    def test_shell_and_unknown_mutation_are_rejected(self):
        self.assertIn("action is not allowlisted", validate_action({"action": "shell", "target": "rm"}))

    def test_validate_action_rejects_non_objects_and_unhashable_fields_without_raising(self):
        for value in (None, ["state-add"], {"action": [], "target": {}}, {"action": {}, "target": []}):
            with self.subTest(value=value):
                errors = validate_action(value)
                self.assertTrue(errors)
                self.assertIn("action is not allowlisted", errors)

    def test_invented_continuity_id_becomes_new(self):
        value = normalize_suggestion({
            "continuityId": "invented", "text": "Investigate spreads", "status": "watching",
            "action": "investigate", "target": "credit", "evidence": [], "confidence": 0.5,
            "handledAt": ""
        }, {"known"})
        self.assertEqual(value["continuityId"], "")

    def test_completed_requires_successful_allowlisted_mutation(self):
        value = normalize_suggestion({
            "continuityId": "known", "text": "Add the CPI state", "status": "completed",
            "action": "state-add", "target": "inflation_us", "evidence": [], "confidence": 0.8,
            "handledAt": "2026-08-09T03:00:00Z", "mutationSucceeded": False,
        }, {"known"})
        self.assertEqual(value["status"], "watching")

    def test_proposal_cannot_claim_its_mutation_succeeded(self):
        completed = normalize_suggestion({
            "continuityId": "known", "text": "Add the CPI state", "status": "completed",
            "action": "state-add", "target": "inflation_us", "evidence": [], "confidence": 0.8,
            "handledAt": "2026-08-09T03:00:00Z", "mutationSucceeded": True,
        }, {"known"})
        self.assertEqual(completed["status"], "watching")

    def test_completed_requires_authoritative_execution_success(self):
        completed = normalize_suggestion({
            "continuityId": "known", "text": "Add the CPI state", "status": "completed",
            "action": "state-add", "target": "inflation_us", "evidence": [], "confidence": 0.8,
            "handledAt": "2026-08-09T03:00:00Z",
        }, {"known"}, mutation_succeeded=True)
        watching = normalize_suggestion({
            "continuityId": "known", "text": "Investigate spreads", "status": "completed",
            "action": "investigate", "target": "credit", "evidence": [], "confidence": 0.8,
            "handledAt": "2026-08-09T03:00:00Z",
        }, {"known"}, mutation_succeeded=True)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(watching["status"], "watching")

    def test_invalid_fields_are_safely_normalized_and_confidence_is_clamped(self):
        value = normalize_suggestion({
            "continuityId": 7, "text": 3, "status": "done", "action": "shell", "target": " ",
            "evidence": "not-a-list", "confidence": 2, "handledAt": "not-utc",
        }, set())
        self.assertEqual(value, {
            "continuityId": "", "text": "", "status": "open", "action": "", "target": "",
            "evidence": [], "confidence": 1.0, "handledAt": "",
        })

    def test_unhashable_status_is_safely_normalized(self):
        value = normalize_suggestion({
            "continuityId": "", "text": "Review", "status": ["completed"],
            "action": "investigate", "target": "credit", "evidence": [], "confidence": 0.5,
            "handledAt": "",
        }, set())
        self.assertEqual(value["status"], "open")


if __name__ == "__main__":
    unittest.main()
