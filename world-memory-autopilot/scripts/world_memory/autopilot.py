"""Safety gates for model-proposed World Memory actions."""

from __future__ import annotations

from copy import deepcopy

from .contracts import is_utc_iso


MUTATIONS = {
    "brief-add", "state-add", "state-supersede", "story-link",
    "taxonomy-refresh", "suggestion-status-update",
}
READ_ONLY = {"investigate"}
STATUSES = {"open", "watching", "completed"}


def validate_action(value: object) -> list[str]:
    """Return validation errors for the narrowly allowlisted action shape."""
    if not isinstance(value, dict):
        return ["action is not allowlisted", "target must be a non-empty string"]
    errors = []
    action = value.get("action")
    if not isinstance(action, str) or action not in MUTATIONS | READ_ONLY:
        errors.append("action is not allowlisted")
    if not isinstance(value.get("target"), str) or not value["target"].strip():
        errors.append("target must be a non-empty string")
    return errors


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(min(1, max(0, value)))


def normalize_suggestion(
    value: dict, known_continuity_ids: set[str], *, mutation_succeeded: bool = False
) -> dict:
    """Return a safe, schema-shaped suggestion from an untrusted model proposal."""
    proposal = value if isinstance(value, dict) else {}
    action = _string(proposal.get("action"))
    target = _string(proposal.get("target"))
    if validate_action({"action": action, "target": target}):
        action = ""
        target = ""

    continuity_id = _string(proposal.get("continuityId"))
    if continuity_id not in known_continuity_ids:
        continuity_id = ""
    status = proposal.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        status = "open"
    if status == "completed":
        if action not in MUTATIONS or mutation_succeeded is not True:
            status = "watching"

    handled_at = _string(proposal.get("handledAt"))
    if not is_utc_iso(handled_at):
        handled_at = ""
    evidence = proposal.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    return {
        "continuityId": continuity_id,
        "text": _string(proposal.get("text")),
        "status": status,
        "action": action,
        "target": target,
        "evidence": deepcopy(evidence),
        "confidence": _confidence(proposal.get("confidence")),
        "handledAt": handled_at,
    }
