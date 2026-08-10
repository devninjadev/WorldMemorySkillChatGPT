"""Normalize RSS and Atom feed entries into World Memory buffer rows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from itertools import chain
from typing import Callable, Iterable
from xml.etree import ElementTree


@dataclass(frozen=True)
class FeedSource:
    """One configured upstream feed and its publication-time correction."""

    feed_id: str
    title: str
    url: str
    published_at_offset_minutes: int


@dataclass(frozen=True)
class FeedItem:
    """The normalized fields required to turn an XML entry into a buffer row."""

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
    FeedSource("financial_juice", "FinancialJuice", "https://rss.app/feeds/5VaycMAa8SwPhOAP.xml", 0),
    FeedSource("walter_bloomberg", "Walter Bloomberg", "https://rss.app/feeds/YcRRdWN5eSO3o2LP.xml", 0),
    FeedSource("wall_st_engine", "Wall St Engine", "https://rss.app/feeds/Hf52VRUllNu7gABF.xml", 0),
    FeedSource("first_squawk", "First Squawk", "https://rss.app/feeds/d68ow40E3dkwaEvN.xml", -540),
    FeedSource("unusual_whales", "unusual_whales", "https://rss.app/feeds/nikLNBATmLDuprRz.xml", -540),
)

FINANCIAL_JUICE, WALTER_BLOOMBERG, WALL_ST_ENGINE, FIRST_SQUAWK, UNUSUAL_WHALES = SOURCES


def source_fingerprint(feed_id: str, identity: str, raw_published: str) -> str:
    """Return the stable upstream identity hash for one feed entry."""
    material = f"{feed_id}\n{identity}\n{raw_published}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text.strip()


def _collapsed_text(value: str) -> str:
    return " ".join(value.split())


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local_name(child) == name), None)


def _child_text(element: ElementTree.Element, name: str) -> str:
    return _text(_child(element, name))


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(raw_published: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(raw_published)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw_published.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid published timestamp: {raw_published}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rss_item(entry: ElementTree.Element, source: FeedSource) -> FeedItem:
    title = _collapsed_text(_child_text(entry, "title"))
    link = _child_text(entry, "link")
    identity = _child_text(entry, "guid") or link or title
    raw_published = _child_text(entry, "pubDate")
    if not identity or not raw_published:
        raise ValueError("RSS item requires an identity and pubDate")
    return FeedItem(identity, link or source.url, title, raw_published, _parse_timestamp(raw_published))


def _atom_link(entry: ElementTree.Element) -> str:
    for link in entry:
        if _local_name(link) == "link" and link.get("href"):
            return link.get("href", "").strip()
    return ""


def _atom_item(entry: ElementTree.Element, source: FeedSource) -> FeedItem:
    title = _collapsed_text(_child_text(entry, "title"))
    link = _atom_link(entry)
    identity = _child_text(entry, "id") or link or title
    raw_published = _child_text(entry, "published") or _child_text(entry, "updated")
    if not identity or not raw_published:
        raise ValueError("Atom entry requires an identity and published timestamp")
    return FeedItem(identity, link or source.url, title, raw_published, _parse_timestamp(raw_published))


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
    """Parse RSS 2.0 or Atom XML bytes into pending World Memory buffer rows."""
    root = ElementTree.fromstring(payload)
    root_name = _local_name(root)
    if root_name == "rss":
        entries = [child for node in root if _local_name(node) == "channel" for child in node if _local_name(child) == "item"]
        return [_row(source, _rss_item(entry, source), fetched_at) for entry in entries]
    if root_name == "feed":
        entries = [child for child in root if _local_name(child) == "entry"]
        return [_row(source, _atom_item(entry, source), fetched_at) for entry in entries]
    raise ValueError("unsupported feed format")


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
