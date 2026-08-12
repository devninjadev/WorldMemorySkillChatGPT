"""Read-only machine interface for World Memory Notion v2 orchestration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .contracts import validate_registry
from .feed import SOURCES, FeedSource, parse_feed
from .market import collect_market_data, market_data_plan
from .scheduler import (
    effective_last_integration,
    normalize_trigger,
    parse_utc,
    run_policy,
    world_memory_due,
)
from .storage import (
    advance_fingerprint_window,
    base_database_schemas,
    canonical_digest,
    canonical_json_bytes,
    installation_cache_properties,
    new_feed_items,
    plan_run_supersession,
    relation_statements,
    run_key,
    slot_key,
)


USER_AGENT = "WorldMemoryAutopilot/2.0 (feed contract verifier)"
_DATABASES = ("installations", "runs", "feed_batches", "memory", "reports")
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArgumentParser(argparse.ArgumentParser):
    """Convert parser failures into the JSON invalid-input contract."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(prog="world-memory")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-registry")
    validate.add_argument("path")

    scheduled_prompt = sub.add_parser("render-scheduled-prompt")
    scheduled_prompt.add_argument("path")

    schema = sub.add_parser("schema")
    schema.add_argument("--database", choices=_DATABASES)

    relations = sub.add_parser("relations")
    relations.add_argument("path")

    key = sub.add_parser("run-key")
    key.add_argument("--installation-key", required=True)
    key.add_argument("--trigger", required=True)
    key.add_argument("--now", required=True)
    key.add_argument("--attempt", required=True, type=int)

    digest = sub.add_parser("digest")
    digest.add_argument("path")

    serialize_cache = sub.add_parser("serialize-installation-cache")
    serialize_cache.add_argument("path")

    supersession = sub.add_parser("plan-run-supersession")
    supersession.add_argument("path")

    normalize = sub.add_parser("normalize-feed")
    normalize.add_argument("--feed-id", required=True)
    normalize.add_argument("--payload", required=True)
    normalize.add_argument("--now", required=True)
    normalize.add_argument("--fingerprint-window")

    gate_parser = sub.add_parser("gate")
    gate_parser.add_argument("--installation", required=True)
    gate_parser.add_argument("--committed-integrations", required=True)
    gate_parser.add_argument("--trigger", required=True)
    gate_parser.add_argument("--now", required=True)
    gate_parser.add_argument("--registry-valid", action="store_true")
    gate_parser.add_argument("--explicit-setup", action="store_true")

    live = sub.add_parser("verify-live")
    live.add_argument("--timeout", type=float, default=20.0)

    market_plan = sub.add_parser("market-data-plan")
    market_plan.add_argument("--now", required=True)

    market_collect = sub.add_parser("collect-market-data")
    market_collect.add_argument("--now", required=True)
    market_collect.add_argument("--timeout", type=float, default=20.0)
    return parser


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _ensure_single_stdin(*paths: str | None) -> None:
    if sum(path == "-" for path in paths if path is not None) > 1:
        raise ValueError("stdin may be used by at most one input operand")


def _read_bytes(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    return Path(path).read_bytes()


def _read_json(path: str) -> object:
    raw = _read_bytes(path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("JSON input must be valid UTF-8") from exc
    if text.startswith("\ufeff"):
        raise ValueError("JSON input must not contain a UTF-8 BOM")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    canonical_json_bytes(value)
    return value


def _source_by_id(feed_id: str) -> FeedSource:
    for source in SOURCES:
        if source.feed_id == feed_id:
            return source
    raise ValueError(f"unknown feed id: {feed_id}")


def _strict_prior_window(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("fingerprint window must be an array")
    seen: dict[str, str] = {}
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"sourceFingerprint", "publishedAt"}:
            raise ValueError(
                f"fingerprint window[{index}] requires exact sourceFingerprint and publishedAt"
            )
        fingerprint = entry.get("sourceFingerprint")
        published_at = entry.get("publishedAt")
        if not isinstance(fingerprint, str) or _LOWER_SHA256.fullmatch(fingerprint) is None:
            raise ValueError(f"fingerprint window[{index}] fingerprint is invalid")
        if fingerprint in seen:
            qualifier = "conflicting duplicate" if seen[fingerprint] != published_at else "duplicate"
            raise ValueError(f"fingerprint window contains {qualifier} fingerprint")
        if not isinstance(published_at, str):
            raise ValueError(f"fingerprint window[{index}] publishedAt is invalid")
        seen[fingerprint] = published_at
    normalized = advance_fingerprint_window([], value)
    if normalized != value:
        raise ValueError("fingerprint window must be canonical, sorted, and capped")
    return value


def validate_registry_command(path: str) -> tuple[dict, bool]:
    value = _read_json(path)
    errors = validate_registry(value)
    return {"errors": errors, "valid": not errors}, not errors


def render_scheduled_prompt_command(path: str) -> dict:
    registry = _read_json(path)
    errors = validate_registry(registry)
    if errors:
        raise ValueError("registry is invalid: " + "; ".join(errors))
    registry_text = _compact_json(registry)
    prompt = (
        "아래 World Memory 레지스트리와 `$world-memory-autopilot` 스킬을 사용해 "
        "`scheduled` 월드 메모리 실행을 1회 수행하세요.\n\n"
        "<world_memory_registry>\n"
        f"{registry_text}\n"
        "</world_memory_registry>\n\n"
        "이 레지스트리는 예약 본문에 내장된 고정 권위입니다. 프로젝트 지침이나 파일 "
        "접근 여부와 무관하게 이 값만을 로컬 검증하고, 검증에 실패하면 Notion을 포함한 "
        "외부 호출 전에 스킬의 정책 오류로 중단하세요. 등록된 Hub와 5개 데이터 소스 외의 "
        "ID를 추측하거나 사용하지 마세요.\n\n"
        "스킬의 레지스트리·Notion 권위·수집·6시간 통합·커밋·캐시·출력 계약을 모두 "
        "준수하세요. 예약 실행에서는 초기화, 스키마 변경, 자동 복구, 원장 supersession "
        "또는 대체 Hub 탐색을 하지 마세요. 성공한 예약 실행은 매시간 누적 풀사이즈 보고서를 "
        "사용자에게 반환하세요. 비통합 보고서는 직전 커밋된 6시간 통합 이후 현재 수집 시점까지 "
        "누적된 피드와 기존 월드 메모리를 함께 사용하고, 월드 메모리 통합은 6시간 게이트가 "
        "열릴 때만 수행하세요. 정책상 오류도 사용자에게 반환하세요."
    )
    return {"prompt": prompt}


def schema_command(database: str | None) -> dict:
    schemas = base_database_schemas()
    if database is not None:
        schemas = {database: schemas[database]}
    return {"schemas": schemas}


def relations_command(path: str) -> dict:
    value = _read_json(path)
    return {
        "relations": {
            key: list(statements)
            for key, statements in relation_statements(value).items()  # type: ignore[arg-type]
        }
    }


def run_key_command(
    installation_key: str,
    trigger: str,
    now: str,
    attempt: int,
) -> dict:
    normalized = normalize_trigger(trigger)
    started_at = parse_utc(now)
    logical_slot = slot_key(installation_key, normalized, started_at)
    return {
        "runKey": run_key(logical_slot, attempt),
        "slotKey": logical_slot,
    }


def digest_command(path: str) -> dict:
    return {"digest": canonical_digest(_read_json(path))}


def serialize_installation_cache_command(path: str) -> dict:
    return {"properties": installation_cache_properties(_read_json(path))}


def plan_run_supersession_command(path: str) -> dict:
    return plan_run_supersession(_read_json(path))


def normalize_feed_command(
    feed_id: str,
    payload_path: str,
    now: str,
    fingerprint_window_path: str | None,
) -> dict:
    _ensure_single_stdin(payload_path, fingerprint_window_path)
    source = _source_by_id(feed_id)
    fetched_at = parse_utc(now)
    payload = _read_bytes(payload_path)
    received = parse_feed(source, payload, fetched_at)
    prior: list[dict] = []
    if fingerprint_window_path is not None:
        prior = _strict_prior_window(_read_json(fingerprint_window_path))
    items, new_count = new_feed_items(prior, received)
    received_entries = [
        {
            "sourceFingerprint": row["sourceFingerprint"],
            "publishedAt": row["publishedAt"],
        }
        for row in received
    ]
    window = advance_fingerprint_window(prior, received_entries)
    cursor = ""
    if received:
        cursor = max(
            received,
            key=lambda row: (row["publishedAt"], row["sourceFingerprint"]),
        )["sourceFingerprint"]
    return {
        "cursor": cursor,
        "feedId": source.feed_id,
        "fingerprintWindow": window,
        "items": items,
        "newCount": new_count,
        "receivedCount": len(received),
    }


def gate_command(
    installation_path: str,
    integrations_path: str,
    trigger: str,
    now: str,
    *,
    registry_valid: bool,
    explicit_setup: bool,
) -> dict:
    _ensure_single_stdin(installation_path, integrations_path)
    installation = _read_json(installation_path)
    integrations = _read_json(integrations_path)
    normalized = normalize_trigger(trigger)
    current = parse_utc(now)
    policy = run_policy(
        installation,
        normalized,
        registry_valid=registry_valid,
        explicit_setup=explicit_setup,
    )
    if not registry_valid:
        return {
            "effectiveLastIntegration": "",
            "policy": policy,
            "worldMemoryDue": False,
        }
    if installation is not None and not isinstance(installation, dict):
        raise ValueError("installation must be an object or null")
    if not isinstance(integrations, list):
        raise ValueError("committed integrations must be an array")
    effective = ""
    due = False
    if registry_valid and isinstance(installation, dict):
        effective = effective_last_integration(installation, integrations)
        if policy["childMutation"] is True:
            due = world_memory_due(installation, integrations, current, normalized)
    return {
        "effectiveLastIntegration": effective,
        "policy": policy,
        "worldMemoryDue": due,
    }


def _response_status(response: object) -> int | None:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()  # type: ignore[union-attr]
    return status if isinstance(status, int) else None


def _live_outcome(
    source: FeedSource,
    timeout: float,
    opener: Callable[..., object] = urlopen,
) -> dict:
    status: int | None = None
    try:
        request = Request(source.url, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            if status is not None and not 200 <= status < 300:
                raise ValueError(f"unexpected HTTP status: {status}")
            rows = parse_feed(source, response.read(), datetime.now(timezone.utc))
        if not rows:
            raise ValueError("feed contains no items")
        return {
            "feedId": source.feed_id,
            "httpStatus": status,
            "itemCount": len(rows),
            "error": "",
        }
    except HTTPError as exc:
        return {
            "feedId": source.feed_id,
            "httpStatus": exc.code,
            "itemCount": 0,
            "error": f"HTTPError: {exc}",
        }
    except Exception as exc:
        return {
            "feedId": source.feed_id,
            "httpStatus": status,
            "itemCount": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def verify_live(timeout: float) -> tuple[dict, bool]:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite number greater than zero")
    sources = [_live_outcome(source, float(timeout)) for source in SOURCES]
    valid = all(not source["error"] for source in sources)
    return {"sources": sources, "valid": valid}, valid


def execute(arguments: argparse.Namespace) -> tuple[dict, bool]:
    if arguments.command == "validate-registry":
        _ensure_single_stdin(arguments.path)
        return validate_registry_command(arguments.path)
    if arguments.command == "render-scheduled-prompt":
        _ensure_single_stdin(arguments.path)
        return render_scheduled_prompt_command(arguments.path), True
    if arguments.command == "schema":
        return schema_command(arguments.database), True
    if arguments.command == "relations":
        _ensure_single_stdin(arguments.path)
        return relations_command(arguments.path), True
    if arguments.command == "run-key":
        return run_key_command(
            arguments.installation_key,
            arguments.trigger,
            arguments.now,
            arguments.attempt,
        ), True
    if arguments.command == "digest":
        _ensure_single_stdin(arguments.path)
        return digest_command(arguments.path), True
    if arguments.command == "serialize-installation-cache":
        _ensure_single_stdin(arguments.path)
        return serialize_installation_cache_command(arguments.path), True
    if arguments.command == "plan-run-supersession":
        _ensure_single_stdin(arguments.path)
        return plan_run_supersession_command(arguments.path), True
    if arguments.command == "normalize-feed":
        return normalize_feed_command(
            arguments.feed_id,
            arguments.payload,
            arguments.now,
            arguments.fingerprint_window,
        ), True
    if arguments.command == "gate":
        return gate_command(
            arguments.installation,
            arguments.committed_integrations,
            arguments.trigger,
            arguments.now,
            registry_valid=arguments.registry_valid,
            explicit_setup=arguments.explicit_setup,
        ), True
    if arguments.command == "verify-live":
        return verify_live(arguments.timeout)
    if arguments.command == "market-data-plan":
        return market_data_plan(arguments.now), True
    if arguments.command == "collect-market-data":
        return collect_market_data(arguments.now, timeout=arguments.timeout), True
    raise ValueError(f"unsupported command: {arguments.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
        result, ok = execute(arguments)
        line = _compact_json(result)
        print(line)
    except (
        OSError,
        UnicodeError,
        ValueError,
        SyntaxError,
        TypeError,
        OverflowError,
        RecursionError,
    ) as exc:
        error = {"error": {"code": "invalid-input", "message": str(exc).strip() or "invalid input"}}
        print(
            json.dumps(
                error,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 2
    return 0 if ok else 1
