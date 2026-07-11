"""Shared contract for projecting audit findings into platform comments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PLATFORM_DISPOSITIONS = {
    "required",
    "clarification",
    "suggested",
    "internal_only",
}

PLATFORM_ORIGINS = {
    "agent",
    "deterministic",
    "source_check",
    "semantic_context",
    "validation",
    "extraction",
    "workflow",
}

_INTERNAL_BLOCKING_ORIGINS = {
    "semantic_context",
    "validation",
    "extraction",
    "workflow",
}

_ALLOWED_DISPOSITIONS_BY_SEVERITY = {
    "blocking": {"required"},
    "advisory": {"suggested", "internal_only"},
    "manual_review": {"clarification", "internal_only"},
    "input_gap": {"clarification", "internal_only"},
}


@dataclass(frozen=True, slots=True)
class PlatformProjection:
    """One validated intent for communicating a finding to the submitter."""

    disposition: str
    message: str = ""

    @classmethod
    def from_dict(cls, payload: Any) -> "PlatformProjection":
        if not isinstance(payload, dict):
            raise ValueError("platform projection must be an object")
        unknown = set(payload) - {"disposition", "message"}
        if unknown:
            raise ValueError(
                "platform projection contains unknown properties: "
                + ", ".join(sorted(unknown))
            )
        raw_disposition = payload.get("disposition")
        if not isinstance(raw_disposition, str):
            raise ValueError("platform disposition must be a string")
        disposition = raw_disposition
        if disposition not in PLATFORM_DISPOSITIONS:
            raise ValueError(
                "platform disposition must be one of "
                + ", ".join(sorted(PLATFORM_DISPOSITIONS))
            )
        raw_message = payload.get("message", "")
        if "message" in payload and not isinstance(raw_message, str):
            raise ValueError("platform message must be a string")
        message = raw_message.strip()
        if disposition == "internal_only" and "message" in payload:
            raise ValueError("internal_only platform projection forbids message")
        if disposition != "internal_only" and not message:
            raise ValueError(
                f"{disposition} platform projection requires a non-empty message"
            )
        return cls(disposition=disposition, message=message)

    def to_dict(self) -> dict[str, str]:
        payload = {"disposition": self.disposition}
        if self.disposition != "internal_only":
            payload["message"] = self.message
        return payload


def validate_platform_projection(severity: str, payload: Any) -> list[str]:
    """Validate projection syntax and its relationship to finding severity."""

    if isinstance(payload, PlatformProjection):
        projection = payload
    else:
        try:
            projection = PlatformProjection.from_dict(payload)
        except ValueError as exc:
            return [str(exc)]

    allowed = _ALLOWED_DISPOSITIONS_BY_SEVERITY.get(severity)
    if allowed is None:
        return [f"unknown finding severity {severity!r}"]
    if projection.disposition not in allowed:
        return [
            f"severity {severity!r} does not permit platform disposition "
            f"{projection.disposition!r}; expected one of {sorted(allowed)}"
        ]
    return []


def is_internal_blocking_origin(origin: str) -> bool:
    """Whether unresolved findings from this origin block platform drafting."""

    return origin in _INTERNAL_BLOCKING_ORIGINS
