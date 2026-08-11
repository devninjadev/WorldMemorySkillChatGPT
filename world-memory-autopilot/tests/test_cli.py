from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import world_memory.cli as world_memory_cli

from tests.test_recovery import eligible_bundle


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "rss-sample.xml"
INSTALLATION_KEY = "wm:123e4567-e89b-42d3-a456-426614174000:default"
IDS = {
    "installations": "11111111-1111-4111-8111-111111111111",
    "runs": "22222222-2222-4222-8222-222222222222",
    "feed_batches": "33333333-3333-4333-8333-333333333333",
    "memory": "44444444-4444-4444-8444-444444444444",
    "reports": "55555555-5555-4555-8555-555555555555",
}


def compact(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"


def run_cli_raw(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SCRIPTS)
    return subprocess.run(
        [sys.executable, "-m", "world_memory", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        input=input_text,
        capture_output=True,
        check=False,
    )


def write_json(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def valid_registry() -> dict:
    database_ids = (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
    )
    return {
        "world_memory": {
            "skill": "world-memory-autopilot",
            "installation_key": INSTALLATION_KEY,
            "notion_workspace_id": "123e4567-e89b-42d3-a456-426614174000",
            "hub_page_id": "99999999-9999-4999-8999-999999999999",
            "hub_url": "https://www.notion.so/world-memory-hub",
            "schema_version": 2,
            "skill_contract_version": "notion-v2",
            "bootstrap_allowed": False,
            "scheduled_schema_mutation_allowed": False,
            "data_sources": {
                key: {
                    "database_id": database_ids[index],
                    "data_source_id": IDS[key],
                    "url": f"https://www.notion.so/{key}",
                }
                for index, key in enumerate(IDS)
            },
        }
    }


def installation(**overrides: object) -> dict:
    value = {
        "page_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "Name": INSTALLATION_KEY,
        "Installation Key": INSTALLATION_KEY,
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


class CliContractTests(unittest.TestCase):
    def assert_invalid(self, result: subprocess.CompletedProcess[str], contains: str = "") -> None:
        self.assertEqual(result.returncode, 2, result)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["code"], "invalid-input")
        self.assertEqual(set(payload["error"]), {"code", "message"})
        if contains:
            self.assertIn(contains, payload["error"]["message"])
        try:
            expected = compact(payload)
            expected.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            expected = json.dumps(
                payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ) + "\n"
        self.assertEqual(result.stderr, expected)

    def test_validate_registry_has_exact_success_and_ordinary_negative_envelopes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            valid_path = write_json(root, "registry.json", valid_registry())
            invalid_path = write_json(root, "invalid.json", {})
            valid = run_cli_raw("validate-registry", str(valid_path))
            invalid = run_cli_raw("validate-registry", str(invalid_path))

        self.assertEqual(valid.returncode, 0)
        self.assertEqual(valid.stderr, "")
        self.assertEqual(valid.stdout, '{"errors":[],"valid":true}\n')
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(invalid.stderr, "")
        self.assertEqual(invalid.stdout, compact({
            "errors": [
                "registry missing required key: world_memory",
                "world_memory must be an object",
            ],
            "valid": False,
        }))

    def test_validate_registry_accepts_stdin(self):
        result = run_cli_raw(
            "validate-registry", "-", input_text=json.dumps(valid_registry())
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '{"errors":[],"valid":true}\n')

    def test_validate_registry_surrogate_json_is_invalid_input_without_traceback(self):
        result = run_cli_raw(
            "validate-registry", "-", input_text=r'{"\ud800":1}'
        )
        self.assert_invalid(result, "valid UTF-8")

    def test_validate_registry_malformed_url_is_an_ordinary_negative(self):
        registry = valid_registry()
        registry["world_memory"]["hub_url"] = "https://["
        result = run_cli_raw(
            "validate-registry", "-", input_text=json.dumps(registry)
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertIn(
            "world_memory.hub_url must be a non-empty HTTP(S) URL",
            payload["errors"],
        )

    def test_render_scheduled_prompt_is_self_contained_and_deterministic(self):
        registry = valid_registry()
        reordered = {
            "world_memory": dict(reversed(list(registry["world_memory"].items())))
        }
        with TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = write_json(root, "registry.json", registry)
            reordered_path = write_json(root, "reordered.json", reordered)
            before = registry_path.read_bytes()
            rendered = run_cli_raw("render-scheduled-prompt", str(registry_path))
            rendered_reordered = run_cli_raw(
                "render-scheduled-prompt", str(reordered_path)
            )
            after = registry_path.read_bytes()

        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(rendered.stderr, "")
        self.assertEqual(rendered.stdout, rendered_reordered.stdout)
        self.assertEqual(after, before)
        payload = json.loads(rendered.stdout)
        self.assertEqual(set(payload), {"prompt"})
        prompt = payload["prompt"]
        marker = "<world_memory_registry>\n"
        registry_text = prompt.split(marker, 1)[1].split(
            "\n</world_memory_registry>", 1
        )[0]
        self.assertEqual(json.loads(registry_text), registry)
        self.assertEqual(
            registry_text,
            json.dumps(
                registry,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        for required in (
            "`scheduled` 월드 메모리 실행을 1회 수행하세요.",
            "예약 본문에 내장된 고정 권위",
            "초기화, 스키마 변경, 자동 복구, 원장 supersession",
            "대체 Hub 탐색",
            "매시간 누적 풀사이즈 보고서",
            "월드 메모리 통합은 6시간 게이트가 열릴 때만",
            "직전 커밋된 6시간 통합 이후 현재 수집 시점까지",
        ):
            with self.subTest(required=required):
                self.assertIn(required, prompt)
        self.assertNotIn("비통합·비중요 실행은 스킬 정책대로 침묵", prompt)

    def test_render_scheduled_prompt_accepts_stdin_and_rejects_invalid_registry(self):
        valid = run_cli_raw(
            "render-scheduled-prompt",
            "-",
            input_text=json.dumps(valid_registry()),
        )
        invalid_registry = valid_registry()
        invalid_registry["world_memory"]["bootstrap_allowed"] = True
        invalid = run_cli_raw(
            "render-scheduled-prompt",
            "-",
            input_text=json.dumps(invalid_registry),
        )

        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn("<world_memory_registry>", json.loads(valid.stdout)["prompt"])
        self.assert_invalid(invalid, "bootstrap_allowed must be false")

    def test_installation_contract_uses_embedded_scheduled_registry_not_project_instruction(self):
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        storage_text = (ROOT / "references" / "storage-contract.md").read_text(
            encoding="utf-8"
        )
        combined = skill_text + "\n" + storage_text

        for stale in (
            "pasted into the project instruction",
            "placed in the project instruction",
            "project-instruction registry",
            "프로젝트 지침에 유효한 World Memory 레지스트리가 없어",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, combined)
        self.assertIn("render-scheduled-prompt", combined)
        self.assertIn("self-contained automation prompt", combined)

    def test_schema_optional_selection_always_uses_schemas_wrapper(self):
        selected = run_cli_raw("schema", "--database", "installations")
        expected = '''CREATE TABLE (
"Name" TITLE, "Installation Key" RICH_TEXT, "Hub Page ID" RICH_TEXT,
"Hub URL" URL, "Status" SELECT('initializing':yellow, 'active':green, 'paused':gray, 'error':red),
"Enabled" CHECKBOX, "Autopilot Enabled" CHECKBOX, "Timezone" SELECT('Asia/Seoul':blue),
"Hourly Interval Minutes" NUMBER, "World Memory Interval Hours" NUMBER,
"Schema Version" NUMBER, "Skill Contract Version" RICH_TEXT, "Feed Cursor State" RICH_TEXT,
"Last Feed Attempt" DATE, "Last Feed Success" DATE, "Last World Memory Success" DATE,
"Last Report Success" DATE, "Next World Memory At" DATE, "Last Briefing At" DATE,
"Last Error" RICH_TEXT, "Created At" CREATED_TIME, "Updated At" LAST_EDITED_TIME)'''
        self.assertEqual(selected.returncode, 0)
        self.assertEqual(selected.stdout, compact({"schemas": {"installations": expected}}))
        all_schemas = json.loads(run_cli_raw("schema").stdout)["schemas"]
        self.assertEqual(
            list(all_schemas),
            ["feed_batches", "installations", "memory", "reports", "runs"],
        )
        self.assert_invalid(
            run_cli_raw("schema", "--database", "unknown"), "invalid choice"
        )

    def test_market_data_plan_exposes_exact_no_auth_sources_and_time_contracts(self):
        result = run_cli_raw(
            "market-data-plan",
            "--now",
            "2026-08-10T08:00:00Z",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["schemaVersion"], 1)
        self.assertEqual(plan["plannedAt"], "2026-08-10T08:00:00Z")

        fred = {item["id"]: item for item in plan["fred"]["series"]}
        self.assertEqual(
            set(fred),
            {"NFCIRISK", "WALCL", "WDTGAL", "RRPONTSYD", "DTWEXBGS"},
        )
        self.assertEqual(
            fred["WALCL"]["url"],
            "https://fred.stlouisfed.org/graph/fredgraph.csv?cosd=2026-02-11&id=WALCL",
        )
        self.assertEqual(plan["fred"]["csv"]["dateField"], "observation_date")
        self.assertEqual(plan["fred"]["csv"]["missingValues"], ["", "."])

        ratio = plan["creditRatio"]
        self.assertEqual(ratio["symbols"], ["HYG", "LQD"])
        self.assertEqual(
            ratio["sourceOrder"],
            ["nasdaq-close", "ishares-nav", "yahoo-close", "cache"],
        )
        self.assertIn("api.nasdaq.com/api/quote/HYG/historical", ratio["nasdaqHistoryUrls"]["HYG"])
        self.assertIn("portfolioId=239565", ratio["isharesHistoryUrls"]["HYG"])
        self.assertEqual(
            ratio.get("historyUrls"),
            {
                "HYG": "https://query1.finance.yahoo.com/v8/finance/chart/HYG?events=history&includeAdjustedClose=true&interval=1d&range=3mo",
                "LQD": "https://query1.finance.yahoo.com/v8/finance/chart/LQD?events=history&includeAdjustedClose=true&interval=1d&range=3mo",
            },
        )
        self.assertEqual(ratio["preferredValueBasis"], "Close")
        self.assertEqual(ratio["alignment"], "inner-common-session")
        self.assertEqual(
            ratio["formulas"],
            {
                "Close": "HYG Close / LQD Close",
                "NAV": "HYG NAV per Share / LQD NAV per Share",
            },
        )
        self.assertEqual(ratio["change5Sessions"], "(ratio_t / ratio_t-5 - 1) * 100")

        derived = {item["id"]: item for item in plan["derived"]}
        self.assertEqual(
            derived["US_NET_LIQUIDITY"]["formula"],
            "WALCL - WDTGAL - (RRPONTSYD * 1000)",
        )
        self.assertEqual(
            derived["US_NET_LIQUIDITY"]["anchor"],
            "WALCL observation dates",
        )
        self.assertEqual(derived["US_NET_LIQUIDITY"]["changeWeeks"], [1, 4, 13])

        binance = {item["symbol"]: item for item in plan["binance"]}
        self.assertEqual(
            set(binance),
            {"CLUSDT", "XAUUSDT", "BTCUSDT", "QQQUSDT", "SPYUSDT"},
        )
        self.assertEqual(
            binance["CLUSDT"]["url"],
            "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=CLUSDT",
        )
        self.assertEqual(binance["XAUUSDT"]["market"], "usdm-perpetual")
        self.assertEqual(
            binance["BTCUSDT"]["url"],
            "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
        )
        self.assertEqual(binance["BTCUSDT"]["market"], "spot")
        self.assertEqual(binance["QQQUSDT"]["role"], "us-growth-equity-proxy")
        self.assertEqual(binance["SPYUSDT"]["role"], "us-large-cap-equity-proxy")
        self.assertEqual(binance["QQQUSDT"]["market"], "usdm-perpetual")
        self.assertEqual(binance["SPYUSDT"]["market"], "usdm-perpetual")
        self.assertEqual(
            binance["BTCUSDT"]["fields"],
            ["lastPrice", "priceChangePercent", "closeTime", "quoteVolume", "count"],
        )
        self.assertEqual(plan["collection"]["binanceWindow"], "rolling-24h")

        breadth = plan["equityBreadth"]
        self.assertEqual(breadth["symbols"], ["RSP", "SPY"])
        self.assertEqual(
            breadth["sourceOrder"],
            ["nasdaq-close", "sp-global-price-return", "yahoo-close", "cache"],
        )
        self.assertIn(
            "api.nasdaq.com/api/quote/RSP/historical",
            breadth["nasdaqHistoryUrls"]["RSP"],
        )
        self.assertIn("indexId=370", breadth["spGlobalHistoryUrls"]["RSP"])
        self.assertIn("indexId=340", breadth["spGlobalHistoryUrls"]["SPY"])
        self.assertEqual(breadth["changeSessions"], [1, 5, 20])
        self.assertEqual(breadth["minimumCommonSessions"], 21)
        self.assertTrue(plan["failurePolicy"]["attemptIndependently"])
        self.assertTrue(plan["failurePolicy"]["netLiquidityRequiresAllComponents"])

    def test_collect_market_data_command_dispatches_bounded_public_collection(self):
        parser = world_memory_cli.build_parser()
        try:
            arguments = parser.parse_args(
                [
                    "collect-market-data",
                    "--now",
                    "2026-08-10T08:00:00Z",
                    "--timeout",
                    "9",
                ]
            )
        except ValueError as exc:
            self.fail(f"collect-market-data command is missing: {exc}")

        expected = {"schemaVersion": 1, "fred": {}, "dataQuality": {"gaps": []}}
        with patch.object(
            world_memory_cli,
            "collect_market_data",
            return_value=expected,
            create=True,
        ) as collect:
            result, ok = world_memory_cli.execute(arguments)

        self.assertTrue(ok)
        self.assertEqual(result, expected)
        collect.assert_called_once_with("2026-08-10T08:00:00Z", timeout=9.0)

    def test_relations_emits_exact_independently_retryable_statements(self):
        with TemporaryDirectory() as temp:
            ids_path = write_json(Path(temp), "ids.json", IDS)
            result = run_cli_raw("relations", str(ids_path))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, compact({
            "relations": {
                "feed_batches": [
                    'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Feed Batches\')'
                ],
                "memory": [
                    'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Memory Records\')',
                    'ADD COLUMN "Supersedes" RELATION(\'44444444-4444-4444-8444-444444444444\')',
                ],
                "reports": [
                    'ADD COLUMN "Run" RELATION(\'22222222-2222-4222-8222-222222222222\', DUAL \'Reports\')',
                    'ADD COLUMN "Evidence Records" RELATION(\'44444444-4444-4444-8444-444444444444\')',
                ],
                "runs": [
                    'ADD COLUMN "Installation" RELATION(\'11111111-1111-4111-8111-111111111111\', DUAL \'Runs\')'
                ],
            }
        }))

    def test_serialize_installation_cache_emits_exact_notion_update_properties(self):
        row = installation()
        row["Feed Cursor State"] = {
            "financial_juice": "1" * 64,
            "walter_bloomberg": "2" * 64,
            "wall_st_engine": "3" * 64,
            "first_squawk": "4" * 64,
            "unusual_whales": "5" * 64,
        }
        row["Last Feed Attempt"] = "2026-08-10T01:00:00Z"
        row["Last Error"] = "first_squawk: timeout"
        with TemporaryDirectory() as temp:
            path = write_json(Path(temp), "installation.json", row)
            result = run_cli_raw("serialize-installation-cache", str(path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        cursor_text = (
            '{"financial_juice":"' + "1" * 64
            + '","first_squawk":"' + "4" * 64
            + '","unusual_whales":"' + "5" * 64
            + '","wall_st_engine":"' + "3" * 64
            + '","walter_bloomberg":"' + "2" * 64 + '"}'
        )
        self.assertEqual(payload, {"properties": {
            "Feed Cursor State": cursor_text,
            "Last Error": "first_squawk: timeout",
            "date:Last Feed Attempt:start": "2026-08-10T01:00:00Z",
            "date:Last Feed Attempt:is_datetime": 1,
            "date:Last Feed Success:start": None,
            "date:Last World Memory Success:start": None,
            "date:Last Report Success:start": None,
            "date:Next World Memory At:start": None,
            "date:Last Briefing At:start": None,
        }})

    def test_plan_run_supersession_emits_exact_status_only_plan(self):
        with TemporaryDirectory() as temp:
            path = write_json(Path(temp), "repair.json", eligible_bundle())
            result = run_cli_raw("plan-run-supersession", str(path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {
            "action": "supersede-run",
            "reason": "feed-fetched-at-property-payload-mismatch",
            "runPageId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "runKey": "wms_b12ee94ad696_scheduled_20260810T020000Z_a001",
            "expectedStatus": "committed",
            "nextStatus": "superseded",
            "propertyUpdates": {"Status": "superseded"},
            "cacheRepairRequired": True,
        })

    def test_run_key_accepts_aware_offsets_and_rejects_naive_time_or_trigger(self):
        result = run_cli_raw(
            "run-key", "--installation-key", INSTALLATION_KEY,
            "--trigger", "manual", "--now", "2026-08-10T11:34:59+09:00",
            "--attempt", "7",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, compact({
            "runKey": "wms_b12ee94ad696_manual_20260810T023400Z_a007",
            "slotKey": "wms_b12ee94ad696_manual_20260810T023400Z",
        }))
        self.assert_invalid(
            run_cli_raw(
                "run-key", "--installation-key", INSTALLATION_KEY,
                "--trigger", "manual", "--now", "2026-08-10T02:34:59",
                "--attempt", "1",
            ),
            "timezone-aware",
        )
        self.assert_invalid(
            run_cli_raw(
                "run-key", "--installation-key", INSTALLATION_KEY,
                "--trigger", "surprise", "--now", "2026-08-10T02:34:59Z",
                "--attempt", "1",
            ),
            "unsupported trigger",
        )

    def test_run_key_utc_normalization_overflow_is_invalid_input(self):
        result = run_cli_raw(
            "run-key", "--installation-key", INSTALLATION_KEY,
            "--trigger", "manual", "--now", "9999-12-31T23:59:59-23:59",
            "--attempt", "1",
        )
        self.assert_invalid(result)

    def test_digest_accepts_any_json_value_and_is_canonical(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            mapping = write_json(root, "mapping.json", {"b": 2, "a": 1})
            scalar = write_json(root, "scalar.json", 3)
            first = run_cli_raw("digest", str(mapping))
            second = run_cli_raw("digest", str(scalar))
        self.assertEqual(first.stdout, compact({
            "digest": "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
        }))
        self.assertEqual(second.stdout, compact({
            "digest": "4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce"
        }))

    def test_normalize_feed_emits_exact_rows_window_cursor_and_counts(self):
        result = run_cli_raw(
            "normalize-feed", "--feed-id", "financial_juice",
            "--payload", str(FIXTURE), "--now", "2026-08-10T02:00:00Z",
        )
        fingerprint_early = "e47383df85601d680ea481128453392f17d73f49d195806ddb4ce18df16006e8"
        fingerprint_late = "42975509b21fdbc8dbf02486af9a60a661d7042832dcf063ae7cb7a109a4ba71"
        expected = {
            "cursor": fingerprint_late,
            "feedId": "financial_juice",
            "fingerprintWindow": [
                {"sourceFingerprint": fingerprint_early, "publishedAt": "2026-08-09T11:30:00Z"},
                {"sourceFingerprint": fingerprint_late, "publishedAt": "2026-08-09T12:00:00Z"},
            ],
            "items": [
                {
                    "schemaVersion": 1, "id": "nf_e47383df85601d680e",
                    "sourceFingerprint": fingerprint_early,
                    "feedId": "financial_juice", "feedTitle": "FinancialJuice",
                    "feedSourceUrl": "https://rss.app/feeds/5VaycMAa8SwPhOAP.xml",
                    "sourceUrl": "https://example.test/inflation-cools",
                    "title": "Inflation cools",
                    "sourcePublishedAt": "2026-08-09T11:30:00Z",
                    "publishedAt": "2026-08-09T11:30:00Z",
                    "publishedAtOffsetMinutes": 0,
                    "fetchedAt": "2026-08-10T02:00:00Z",
                    "status": "pending", "importanceCandidate": "unassessed",
                },
                {
                    "schemaVersion": 1, "id": "nf_42975509b21fdbc8db",
                    "sourceFingerprint": fingerprint_late,
                    "feedId": "financial_juice", "feedTitle": "FinancialJuice",
                    "feedSourceUrl": "https://rss.app/feeds/5VaycMAa8SwPhOAP.xml",
                    "sourceUrl": "https://example.test/markets-open-higher",
                    "title": "Markets open higher",
                    "sourcePublishedAt": "2026-08-09T12:00:00Z",
                    "publishedAt": "2026-08-09T12:00:00Z",
                    "publishedAtOffsetMinutes": 0,
                    "fetchedAt": "2026-08-10T02:00:00Z",
                    "status": "pending", "importanceCandidate": "unassessed",
                },
            ],
            "newCount": 2,
            "receivedCount": 2,
        }
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, compact(expected))

    def test_normalize_feed_dedupes_against_strict_prior_window_but_keeps_cursor(self):
        window = [
            {
                "sourceFingerprint": "e47383df85601d680ea481128453392f17d73f49d195806ddb4ce18df16006e8",
                "publishedAt": "2026-08-09T11:30:00Z",
            },
            {
                "sourceFingerprint": "42975509b21fdbc8dbf02486af9a60a661d7042832dcf063ae7cb7a109a4ba71",
                "publishedAt": "2026-08-09T12:00:00Z",
            },
        ]
        with TemporaryDirectory() as temp:
            prior = write_json(Path(temp), "window.json", window)
            result = run_cli_raw(
                "normalize-feed", "--feed-id", "financial_juice",
                "--payload", str(FIXTURE), "--now", "2026-08-10T02:00:00Z",
                "--fingerprint-window", str(prior),
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {
            "cursor": "42975509b21fdbc8dbf02486af9a60a661d7042832dcf063ae7cb7a109a4ba71",
            "feedId": "financial_juice",
            "fingerprintWindow": window,
            "items": [],
            "newCount": 0,
            "receivedCount": 2,
        })

    def test_normalize_feed_rejects_noncanonical_prior_window_and_bad_xml(self):
        duplicate = [
            {"sourceFingerprint": "a" * 64, "publishedAt": "2026-08-09T00:00:00Z"},
            {"sourceFingerprint": "a" * 64, "publishedAt": "2026-08-09T00:00:00Z"},
        ]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            prior = write_json(root, "window.json", duplicate)
            malformed = root / "bad.xml"
            malformed.write_text("<rss>", encoding="utf-8")
            duplicate_result = run_cli_raw(
                "normalize-feed", "--feed-id", "financial_juice",
                "--payload", str(FIXTURE), "--now", "2026-08-10T02:00:00Z",
                "--fingerprint-window", str(prior),
            )
            xml_result = run_cli_raw(
                "normalize-feed", "--feed-id", "financial_juice",
                "--payload", str(malformed), "--now", "2026-08-10T02:00:00Z",
            )
        self.assert_invalid(duplicate_result, "duplicate")
        self.assert_invalid(xml_result, "XML")

    def test_normalize_feed_unknown_xml_encoding_is_invalid_input(self):
        with TemporaryDirectory() as temp:
            payload = Path(temp) / "unknown-encoding.xml"
            payload.write_bytes(
                b'<?xml version="1.0" encoding="does-not-exist"?><rss></rss>'
            )
            result = run_cli_raw(
                "normalize-feed", "--feed-id", "financial_juice",
                "--payload", str(payload), "--now", "2026-08-10T02:00:00Z",
            )
        self.assert_invalid(result, "encoding")

    def test_gate_combines_policy_with_authoritative_clock(self):
        expected_policy = {
            "action": "run", "reason": "active", "run": True,
            "collect": True, "analyze": True, "schemaMutation": False,
            "childMutation": True, "cacheMutation": True,
            "memoryMutation": True, "completeSuggestions": True,
            "notification": "normal",
        }
        integration = {
            "Status": "committed", "Integration Performed": True,
            "Integration Key": "wmi_b12ee94ad696_genesis",
            "Collection Cutoff": "2026-08-10T02:00:00Z",
        }
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install_path = write_json(root, "installation.json", installation())
            runs_path = write_json(root, "runs.json", [integration])
            result = run_cli_raw(
                "gate", "--installation", str(install_path),
                "--committed-integrations", str(runs_path),
                "--trigger", "manual", "--now", "2026-08-10T08:00:00Z",
                "--registry-valid",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, compact({
            "effectiveLastIntegration": "2026-08-10T02:00:00Z",
            "policy": expected_policy,
            "worldMemoryDue": True,
        }))

    def test_gate_forces_due_false_when_policy_cannot_mutate_children(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install_path = write_json(root, "installation.json", installation(Enabled=False))
            runs_path = write_json(root, "runs.json", [])
            result = run_cli_raw(
                "gate", "--installation", str(install_path),
                "--committed-integrations", str(runs_path),
                "--trigger", "force-world-memory", "--now", "2026-08-10T08:00:00Z",
                "--registry-valid",
            )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["worldMemoryDue"])
        self.assertEqual(payload["effectiveLastIntegration"], "")
        self.assertEqual(payload["policy"]["action"], "read-only")
        self.assertFalse(payload["policy"]["childMutation"])

    def test_gate_registry_invalid_fails_closed_without_trusting_installation_cache(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install_path = write_json(root, "installation.json", {})
            runs_path = write_json(root, "runs.json", [])
            result = run_cli_raw(
                "gate", "--installation", str(install_path),
                "--committed-integrations", str(runs_path),
                "--trigger", "manual", "--now", "2026-08-10T08:00:00Z",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["effectiveLastIntegration"], "")
        self.assertFalse(payload["worldMemoryDue"])
        self.assertEqual(payload["policy"]["reason"], "registry-invalid")

    def test_gate_registry_invalid_ignores_decoded_installation_and_projection_shapes(self):
        for index, (installation_value, projection_value) in enumerate((
            (7, {}),
            (["not", "an", "installation"], "not-a-projection"),
        )):
            with self.subTest(index=index), TemporaryDirectory() as temp:
                root = Path(temp)
                install_path = write_json(root, "installation.json", installation_value)
                runs_path = write_json(root, "runs.json", projection_value)
                result = run_cli_raw(
                    "gate", "--installation", str(install_path),
                    "--committed-integrations", str(runs_path),
                    "--trigger", "manual", "--now", "2026-08-10T08:00:00Z",
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["policy"]["reason"], "registry-invalid")
            self.assertEqual(json.loads(result.stdout)["effectiveLastIntegration"], "")
            self.assertFalse(json.loads(result.stdout)["worldMemoryDue"])

    def test_gate_registry_invalid_still_rejects_malformed_json(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install_path = root / "installation.json"
            install_path.write_text('{"x":1,"x":2}', encoding="utf-8")
            runs_path = write_json(root, "runs.json", {})
            result = run_cli_raw(
                "gate", "--installation", str(install_path),
                "--committed-integrations", str(runs_path),
                "--trigger", "manual", "--now", "2026-08-10T08:00:00Z",
            )
        self.assert_invalid(result, "duplicate JSON key")

    def test_digest_deep_json_returns_invalid_input_without_traceback(self):
        deeply_nested = "[" * 1500 + "0" + "]" * 1500
        result = run_cli_raw("digest", "-", input_text=deeply_nested)
        self.assert_invalid(result, "nesting")

    def test_digest_surrogate_keys_always_emit_utf8_safe_invalid_input(self):
        for payload in (
            r'{"\ud800":1}',
            r'{"\ud800":1,"\ud800":2}',
        ):
            with self.subTest(payload=payload):
                result = run_cli_raw("digest", "-", input_text=payload)
                self.assert_invalid(result)
                result.stderr.encode("utf-8", errors="strict")

    def test_gate_unhashable_integration_status_is_invalid_input(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            install_path = write_json(root, "installation.json", installation())
            runs_path = write_json(root, "runs.json", [{
                "Status": [],
                "Integration Performed": False,
            }])
            result = run_cli_raw(
                "gate", "--installation", str(install_path),
                "--committed-integrations", str(runs_path),
                "--trigger", "manual", "--now", "2026-08-10T08:00:00Z",
                "--registry-valid",
            )
        self.assert_invalid(result, "Status")

    def test_json_loader_rejects_duplicates_nonfinite_bom_and_invalid_utf8(self):
        malformed_documents = (
            b'{"outer":{"x":1,"x":2}}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1e309}',
            b'\xef\xbb\xbf{}',
            b'\xff',
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for index, raw in enumerate(malformed_documents):
                path = root / f"bad-{index}.json"
                path.write_bytes(raw)
                with self.subTest(index=index):
                    self.assert_invalid(run_cli_raw("digest", str(path)))

    def test_json_loader_path_errors_are_compact_invalid_input(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing.json"
            for path in (missing, root):
                with self.subTest(path=path):
                    self.assert_invalid(run_cli_raw("digest", str(path)))

    def test_dual_stdin_is_rejected_before_reading_and_unknown_feed_is_invalid(self):
        dual = run_cli_raw(
            "normalize-feed", "--feed-id", "financial_juice", "--payload", "-",
            "--now", "2026-08-10T02:00:00Z", "--fingerprint-window", "-",
            input_text="unused",
        )
        self.assert_invalid(dual, "stdin")
        self.assert_invalid(
            run_cli_raw(
                "normalize-feed", "--feed-id", "unknown", "--payload", str(FIXTURE),
                "--now", "2026-08-10T02:00:00Z",
            ),
            "unknown feed id",
        )

    def test_json_and_xml_input_paths_remain_byte_identical(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            value_path = write_json(root, "value.json", {"b": 2, "a": 1})
            xml_path = root / "sample.xml"
            xml_path.write_bytes(FIXTURE.read_bytes())
            before = {value_path: value_path.read_bytes(), xml_path: xml_path.read_bytes()}
            self.assertEqual(run_cli_raw("digest", str(value_path)).returncode, 0)
            self.assertEqual(run_cli_raw(
                "normalize-feed", "--feed-id", "financial_juice",
                "--payload", str(xml_path), "--now", "2026-08-10T02:00:00Z",
            ).returncode, 0)
            after = {path: path.read_bytes() for path in before}
        self.assertEqual(after, before)

    def test_legacy_commands_are_unknown_and_help_is_the_only_prose_success(self):
        for command in ("bootstrap", "validate", "ingest"):
            with self.subTest(command=command):
                self.assert_invalid(run_cli_raw(command), "invalid choice")
        help_result = run_cli_raw("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("validate-registry", help_result.stdout)
        self.assertEqual(help_result.stderr, "")

    def test_verify_live_reports_failed_source_without_hiding_later_sources(self):
        def source_outcome(source, timeout):
            if source.feed_id == "walter_bloomberg":
                return {
                    "feedId": source.feed_id, "httpStatus": 503,
                    "itemCount": 0, "error": "HTTPError: unavailable",
                }
            return {
                "feedId": source.feed_id, "httpStatus": 200,
                "itemCount": 2, "error": "",
            }

        with patch.object(world_memory_cli, "_live_outcome", side_effect=source_outcome):
            payload, valid = world_memory_cli.verify_live(20)

        self.assertFalse(valid)
        self.assertEqual(len(payload["sources"]), 5)
        self.assertEqual(payload["sources"][1], {
            "feedId": "walter_bloomberg", "httpStatus": 503,
            "itemCount": 0, "error": "HTTPError: unavailable",
        })
        self.assertEqual(payload["sources"][-1]["feedId"], "unusual_whales")

    @unittest.skipUnless(os.environ.get("WORLD_MEMORY_LIVE") == "1", "live network test")
    def test_all_five_feeds_are_live(self):
        result = run_cli_raw("verify-live", "--timeout", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(
            [row["feedId"] for row in payload["sources"]],
            ["financial_juice", "walter_bloomberg", "wall_st_engine", "first_squawk", "unusual_whales"],
        )


if __name__ == "__main__":
    unittest.main()
