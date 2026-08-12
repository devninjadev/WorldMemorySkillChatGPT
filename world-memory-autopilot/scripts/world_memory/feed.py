"""Normalize strict RSS.app CSV rows into World Memory buffer rows."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
from itertools import chain
from typing import Callable, Iterable


@dataclass(frozen=True)
class FeedSource:
    """One configured upstream feed and its publication-time correction."""

    feed_id: str
    title: str
    url: str
    published_at_offset_minutes: int


@dataclass(frozen=True)
class FeedItem:
    """The normalized fields required to turn a CSV row into a buffer row."""

    identity: str
    source_url: str
    title: str
    raw_published: str
    source_published_at: datetime


@dataclass(frozen=True)
class FetchOutcome:
    """The independent result of fetching a single feed source."""

    ok: bool
    items: list[dict]
    error: str


SOURCES = (
    FeedSource("financial_juice", "FinancialJuice", "https://rss.app/feeds/5VaycMAa8SwPhOAP.csv", 0),
    FeedSource("walter_bloomberg", "Walter Bloomberg", "https://rss.app/feeds/YcRRdWN5eSO3o2LP.csv", 0),
    FeedSource("wall_st_engine", "Wall St Engine", "https://rss.app/feeds/Hf52VRUllNu7gABF.csv", 0),
    FeedSource("first_squawk", "First Squawk", "https://rss.app/feeds/d68ow40E3dkwaEvN.csv", -540),
    FeedSource("unusual_whales", "unusual_whales", "https://rss.app/feeds/nikLNBATmLDuprRz.csv", -540),
)

RSS_APP_CSV_HEADER = (
    "ID",
    "Feed URL",
    "Feed Link",
    "Feed Title",
    "Feed Description",
    "Feed Icon",
    "Title",
    "Link",
    "Description",
    "Image",
    "Plain Description",
    "Author",
    "Date",
)

FINANCIAL_JUICE, WALTER_BLOOMBERG, WALL_ST_ENGINE, FIRST_SQUAWK, UNUSUAL_WHALES = SOURCES


def source_fingerprint(feed_id: str, identity: str, raw_published: str) -> str:
    """Return the stable upstream identity hash for one feed entry."""
    material = f"{feed_id}\n{identity}\n{raw_published}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _collapsed_text(value: str) -> str:
    return " ".join(value.split())


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(raw_published: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw_published.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid published timestamp: {raw_published}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _csv_item(row: dict[str, str], source: FeedSource) -> FeedItem:
    title = _collapsed_text(row["Title"])
    link = row["Link"].strip()
    identity = link or title
    raw_published = row["Date"].strip()
    if not title:
        raise ValueError("RSS.app CSV row requires a non-empty Title")
    if not identity:
        raise ValueError("RSS.app CSV row requires Link or Title identity")
    if not raw_published:
        raise ValueError("RSS.app CSV row requires Date")
    return FeedItem(
        identity,
        link or source.url,
        title,
        raw_published,
        _parse_timestamp(raw_published),
    )


def _row(source: FeedSource, item: FeedItem, fetched_at: datetime) -> dict:
    fingerprint = source_fingerprint(source.feed_id, item.identity, item.raw_published)
    source_published_at = _format_utc(item.source_published_at)
    published_at = _format_utc(
        item.source_published_at + timedelta(minutes=source.published_at_offset_minutes)
    )
    return {
        "schemaVersion": 1,
        "id": f"nf_{fingerprint[:18]}",
        "sourceFingerprint": fingerprint,
        "feedId": source.feed_id,
        "feedTitle": source.title,
        "feedSourceUrl": source.url,
        "sourceUrl": item.source_url,
        "title": item.title,
        "sourcePublishedAt": source_published_at,
        "publishedAt": published_at,
        "publishedAtOffsetMinutes": source.published_at_offset_minutes,
        "fetchedAt": _format_utc(fetched_at),
        "status": "pending",
        "importanceCandidate": "unassessed",
    }


def parse_feed(source: FeedSource, payload: bytes, fetched_at: datetime) -> list[dict]:
    """Parse exact RSS.app UTF-8 CSV bytes into pending buffer rows."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("RSS.app CSV payload must be valid UTF-8") from exc
    if text.startswith("\ufeff"):
        raise ValueError("RSS.app CSV payload must not contain a UTF-8 BOM")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if header != list(RSS_APP_CSV_HEADER):
            raise ValueError("RSS.app CSV header must match the exact configured schema")
        items = []
        for index, values in enumerate(reader, start=2):
            if len(values) != len(RSS_APP_CSV_HEADER):
                raise ValueError(f"RSS.app CSV row {index} has an invalid column count")
            record = dict(zip(RSS_APP_CSV_HEADER, values, strict=True))
            items.append(_row(source, _csv_item(record, source), fetched_at))
        return items
    except csv.Error as exc:
        raise ValueError(f"invalid RSS.app CSV payload: {exc}") from exc


def merge_buffer(existing: Iterable[dict], incoming: Iterable[dict]) -> list[dict]:
    """Deduplicate buffer rows while preserving processed entries over pending ones."""
    by_key: dict[str, dict] = {}
    for row in chain(existing, incoming):
        key = row.get("sourceFingerprint") or row.get("id")
        if not key:
            raise ValueError("feed row requires sourceFingerprint or id")
        previous = by_key.get(key)
        if previous is None or previous.get("status") == "pending":
            by_key[key] = deepcopy(row)
    return sorted(by_key.values(), key=lambda row: (row["publishedAt"], row["id"]))


def fetch_sources(
    sources: Iterable[FeedSource], opener: Callable[[FeedSource], bytes], now: datetime
) -> dict[str, FetchOutcome]:
    """Fetch every source, isolating failures so successful peers still produce rows."""
    outcomes = {}
    for source in sources:
        try:
            payload = opener(source)
            outcomes[source.feed_id] = FetchOutcome(True, parse_feed(source, payload, now), "")
        except Exception as exc:
            outcomes[source.feed_id] = FetchOutcome(False, [], f"{type(exc).__name__}: {exc}")
    return outcomes
