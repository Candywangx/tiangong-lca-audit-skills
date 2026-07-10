from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

OPERATION_SCHEMA_VERSION = "tiangong-audit-operation-v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@dataclass(slots=True)
class OperationLogEntry:
    """Append-only record for platform operations and dry runs."""

    operation: str
    status: str
    target_id: str = ""
    dry_run: bool = True
    timestamp: str = field(default_factory=utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OPERATION_SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "operation": self.operation,
            "status": self.status,
            "target_id": self.target_id,
            "dry_run": self.dry_run,
            "details": dict(self.details),
            "error": self.error,
        }
