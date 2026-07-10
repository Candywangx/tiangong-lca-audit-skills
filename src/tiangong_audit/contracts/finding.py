from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FINDING_SCHEMA_VERSION = "tiangong-audit-finding-v1"
VALID_SEVERITIES = {"blocking", "advisory", "manual_review", "input_gap"}


@dataclass(slots=True)
class Finding:
    """Shared finding shape for precheck, source checks, and Agent review."""

    rule_id: str
    severity: str
    location: str
    evidence: str
    judgment: str
    suggestion: str
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid finding severity: {self.severity}")
        return {
            "schema_version": FINDING_SCHEMA_VERSION,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "location": self.location,
            "evidence": self.evidence,
            "judgment": self.judgment,
            "suggestion": self.suggestion,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Finding":
        return cls(
            rule_id=str(payload.get("rule_id") or ""),
            severity=str(payload.get("severity") or ""),
            location=str(payload.get("location") or ""),
            evidence=str(payload.get("evidence") or ""),
            judgment=str(payload.get("judgment") or ""),
            suggestion=str(payload.get("suggestion") or ""),
            source=str(payload.get("source") or ""),
        )
