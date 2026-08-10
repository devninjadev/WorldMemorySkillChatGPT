from dataclasses import replace
from datetime import datetime
import hashlib
from pathlib import Path
import unittest

from world_memory.feed import (
    FINANCIAL_JUICE,
    FIRST_SQUAWK,
    fetch_sources,
    merge_buffer,
    parse_feed,
    source_fingerprint,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/rss-sample.xml"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FeedTests(unittest.TestCase):
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

    def test_atom_uses_id_and_link_href(self):
        payload = b'''<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Atom source</title>
          <entry>
            <id>atom-7</id>
            <title> Atom   story </title>
            <link href="https://example.test/atom-story" />
            <published>2026-08-09T12:00:00+00:00</published>
          </entry>
        </feed>'''
        rows = parse_feed(FINANCIAL_JUICE, payload, utc("2026-08-09T13:00:00Z"))
        self.assertEqual(rows[0]["title"], "Atom story")
        self.assertEqual(rows[0]["sourceUrl"], "https://example.test/atom-story")
        self.assertEqual(rows[0]["sourceFingerprint"], source_fingerprint(
            "financial_juice", "atom-7", "2026-08-09T12:00:00+00:00"
        ))


if __name__ == "__main__":
    unittest.main()
