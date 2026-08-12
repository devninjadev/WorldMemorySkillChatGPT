# CSV Feed Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace XML ingestion with strict RSS.app CSV ingestion and publish World Memory Autopilot v0.9.9.

**Architecture:** `feed.py` owns deterministic CSV decoding and normalization. `cli.py` owns bounded direct HTTP and exposes the existing `normalize-feed` and `verify-live` interfaces. Contracts and fixtures share the same five canonical `.csv` URLs; no general web fallback exists.

**Tech Stack:** Python 3.10+, standard-library `csv`, `io`, `urllib.request`, `unittest`, GitHub Actions.

## Global Constraints

- RSS.app CSV is the only configured FEED format.
- All five RSS.app acquisitions use packaged direct HTTP only.
- Generic web fetch, web search, and browser navigation are forbidden as RSS.app fallbacks.
- Existing normalized item, Feed Batch, Notion, gate, and cache contracts remain unchanged except canonical source URLs.
- Release version is exactly `0.9.9` / `v0.9.9`.

---

### Task 1: CSV parser and canonical sources

**Files:**
- Create: `world-memory-autopilot/tests/fixtures/rss-app-sample.csv`
- Modify: `world-memory-autopilot/tests/test_feed.py`
- Modify: `world-memory-autopilot/scripts/world_memory/feed.py`
- Modify: `world-memory-autopilot/scripts/world_memory/contracts.py`

**Interfaces:**
- Consumes: `parse_feed(source: FeedSource, payload: bytes, fetched_at: datetime)`.
- Produces: the same normalized row list, now exclusively from strict RSS.app CSV bytes.

- [ ] Write tests for canonical `.csv` URLs, Link-first identity, Title fallback, offsets, exact headers, malformed UTF-8, BOM, invalid dates, and missing identity.
- [ ] Run `python3 -m unittest tests.test_feed -v` and verify XML-era behavior fails against the new contract.
- [ ] Replace XML parsing with strict `csv.DictReader` parsing and update canonical source constants.
- [ ] Run `python3 -m unittest tests.test_feed -v` and verify all Feed tests pass.

### Task 2: CLI and direct-HTTP enforcement

**Files:**
- Modify: `world-memory-autopilot/tests/test_cli.py`
- Modify: `world-memory-autopilot/scripts/world_memory/cli.py`

**Interfaces:**
- Consumes: strict `parse_feed` and existing `urlopen(Request(...), timeout=...)` path.
- Produces: unchanged JSON envelopes for `normalize-feed` and `verify-live`.

- [ ] Change CLI fixtures and expectations to CSV; add tests proving direct `urllib` Request use and CSV-specific errors.
- [ ] Run targeted CLI tests and verify failures mention obsolete XML behavior or wrong source URLs.
- [ ] Remove XML exception handling/imports, keep direct HTTP as the sole live collector, and return CSV validation errors per source.
- [ ] Run targeted CLI tests and verify they pass.

### Task 3: Durable contracts and skill instructions

**Files:**
- Modify: `world-memory-autopilot/references/source-contract.md`
- Modify: `world-memory-autopilot/SKILL.md`
- Modify: `world-memory-autopilot/tests/test_analysis_contract_policy.py`
- Modify: all test helpers carrying canonical RSS.app URLs.
- Modify: `README.md`

**Interfaces:**
- Produces: v0.9.9 instructions that require direct HTTP and prohibit generic web/browser RSS.app fallback.

- [ ] Add contract tests that require `.csv`, direct HTTP, and the no-web-fallback rule and reject canonical `.xml` feed URLs.
- [ ] Run the contract tests and verify they fail before documentation/fixture changes.
- [ ] Update source contract, skill procedure, helpers, README, and version metadata.
- [ ] Run all contract and storage tests and verify they pass.

### Task 4: Package verification and release

**Files:**
- Create temporarily: `.github/workflows/publish-v0.9.9.yml`

**Interfaces:**
- Produces: `world-memory-autopilot-v0.9.9.zip`, checksum asset, tag, and GitHub Release.

- [ ] Run the complete test suite, quick skill validation, live direct-HTTP verification, archive integrity check, and repository diff review.
- [ ] Commit the v0.9.9 implementation and one-time release workflow, then push `main`.
- [ ] Confirm GitHub Release `v0.9.9`, release assets, and workflow success.
- [ ] Remove the one-time workflow, commit, push `main`, and confirm the release remains available.
