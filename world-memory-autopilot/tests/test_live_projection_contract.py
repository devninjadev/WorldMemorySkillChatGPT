import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
STORAGE = ROOT / "references" / "storage-contract.md"


class LiveProjectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.storage = STORAGE.read_text(encoding="utf-8")
        cls.combined = cls.skill + "\n" + cls.storage

    def test_post_mutation_reads_use_exhaustive_live_view_projection(self):
        self.assertIn("## Fresh live projections after mutation", self.storage)
        self.assertIn('query_data_sources` with `mode:"view"', self.combined)
        self.assertIn("`has_more=false`", self.combined)
        self.assertIn("`next_cursor`", self.combined)
        self.assertIn("application-filter", self.combined)

    def test_sql_search_and_fetch_cannot_prove_post_mutation_uniqueness(self):
        self.assertIn(
            "SQL mode is never a post-mutation 0/1/N or uniqueness authority",
            self.combined,
        )
        self.assertIn(
            "Search ranking and direct fetch cannot prove absence or uniqueness",
            self.combined,
        )

    def test_every_mutable_ledger_source_has_an_unfiltered_live_view(self):
        for mapping in (
            "Runs -> `Recent`",
            "Feed Batches -> `Recent`",
            "Memory -> `Recent Revisions`",
            "Reports -> `Latest`",
        ):
            with self.subTest(mapping=mapping):
                self.assertIn(mapping, self.storage)

    def test_post_create_and_precommit_require_live_projection(self):
        self.assertIn(
            "After creating a preparing Run, use the Runs live projection",
            self.storage,
        )
        self.assertIn(
            "Every post-create child read-back and every precommit query",
            self.storage,
        )


if __name__ == "__main__":
    unittest.main()
