from dataclasses import replace
from datetime import datetime
import hashlib
from pathlib import Path
import unittest

from world_memory.feed import (
    FINANCIAL_JUICE,
    FIRST_SQUAWK,
    SOURCES,
    fetch_sources,
    merge_buffer,
    parse_feed,
    source_fingerprint,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/rss-app-sample.csv"
HEADER = (
    "ID,Feed URL,Feed Link,Feed Title,Feed Description,Feed Icon,Title,Link,"
    "Description,Image,Plain Description,Author,Date\n"
)


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FeedTests(unittest.TestCase):
    def test_configured_sources_use_csv_only(self):
        self.assertTrue(all(source.url.endswith(".csv") for source in SOURCES))
        self.assertFalse(any(".xml" in source.url for source in SOURCES))

    def test_fingerprint_matches_source_contract(self):
        expected = hashlib.sha256(b"first_squawk\nguid-7\nSun, 09 Aug 2026 12:00:00 GMT").hexdigest()
        self.assertEqual(source_fingerprint(
            "first_squawk", "guid-7", "Sun, 09 Aug 2026 12:00:00 GMT"
        ), expected)

    def test_first_squawk_applies_minus_540_minutes(self):
        rows = parse_feed(FIRST_SQUAWK, FIXTURE.read_bytes(), utc("2026-08-09T13:00:00Z"))
        self.assertEqual(rows[0]["sourcePublishedAt"], "2026-08-09T12:00:00Z")
        self.assertEqual(rows[0]["publishedAt"], "2026-08-09T03:00:00Z")
        self.assertEqual(rows[0]["publishedAtOffsetMinutes"], -540)

    def test_csv_uses_link_identity_and_preserves_raw_date_for_fingerprint(self):
        rows = parse_feed(FINANCIAL_JUICE, FIXTURE.read_bytes(), utc("2026-08-09T13:00:00Z"))
        expected = source_fingerprint(
            "financial_juice",
            "https://example.test/markets-open-higher",
            "2026-08-09T12:00:00.000Z",
        )
        self.assertEqual(rows[0]["sourceFingerprint"], expected)
        self.assertEqual(rows[0]["title"], "Markets open higher")
        self.assertEqual(rows[0]["sourceUrl"], "https://example.test/markets-open-higher")
        self.assertEqual(rows[0]["feedSourceUrl"], FINANCIAL_JUICE.url)

    def test_csv_falls_back_to_collapsed_title_identity_and_configured_url(self):
        payload = (HEADER + ",,,,,,  Title   only  ,,,,,,2026-08-09T12:00:00Z\n").encode()
        rows = parse_feed(FINANCIAL_JUICE, payload, utc("2026-08-09T13:00:00Z"))
        self.assertEqual(rows[0]["title"], "Title only")
        self.assertEqual(rows[0]["sourceUrl"], FINANCIAL_JUICE.url)
        self.assertEqual(
            rows[0]["sourceFingerprint"],
            source_fingerprint("financial_juice", "Title only", "2026-08-09T12:00:00Z"),
        )

    def test_second_ingest_does_not_grow_buffer(self):
        rows = parse_feed(FINANCIAL_JUICE, FIXTURE.read_bytes(), utc("2026-08-09T13:00:00Z"))
        self.assertEqual(len(merge_buffer(rows, rows)), len(rows))

    def test_one_source_failure_keeps_other_source_result(self):
        def opener(source):
            if source.feed_id == "bad":
                raise TimeoutError("timeout")
            return FIXTURE.read_bytes()
        outcomes = fetch_sources([replace(FINANCIAL_JUICE, feed_id="ok"), replace(FINANCIAL_JUICE, feed_id="bad")], opener, utc("2026-08-09T13:00:00Z"))
        self.assertTrue(outcomes["ok"].ok)
        self.assertFalse(outcomes["bad"].ok)
        self.assertGreater(len(outcomes["ok"].items), 0)
        self.assertEqual(outcomes["bad"].items, [])

    def test_csv_rejects_non_utf8_bom_and_nonexact_headers(self):
        valid_row = ",,,,,,Story,https://example.test/story,,,,,2026-08-09T12:00:00Z\n"
        cases = (
            b"\xff",
            b"\xef\xbb\xbf" + (HEADER + valid_row).encode(),
            (HEADER.replace("Feed URL,Feed Link", "Feed Link,Feed URL") + valid_row).encode(),
            (HEADER.replace("Title,Link", "Title,Title") + valid_row).encode(),
        )
        for payload in cases:
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(ValueError):
                    parse_feed(FINANCIAL_JUICE, payload, utc("2026-08-09T13:00:00Z"))

    def test_csv_rejects_missing_identity_date_and_invalid_date(self):
        cases = (
            ",,,,,,,,,,,,,2026-08-09T12:00:00Z\n",
            ",,,,,,Story,https://example.test/story,,,,,\n",
            ",,,,,,Story,https://example.test/story,,,,,not-a-date\n",
        )
        for row in cases:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    parse_feed(
                        FINANCIAL_JUICE,
                        (HEADER + row).encode(),
                        utc("2026-08-09T13:00:00Z"),
                    )


if __name__ == "__main__":
    unittest.main()
