from __future__ import annotations

import json
from collections.abc import Mapping, Iterator
from pathlib import Path
from typing import Any

# Resolve against installed source, never an unrelated case workspace root.
DEFAULT_RULES_DIR = Path(__file__).resolve().parents[3] / "skill/tiangong-lca-audit/rules"


def load_rule_catalog(dataset_type: str, *, rules_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    directory = Path(rules_dir) if rules_dir is not None else DEFAULT_RULES_DIR
    catalog: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("dataset_type") not in {"all", dataset_type}:
            continue
        for rule in payload.get("rules", []):
            for field in ("agent_review_required", "allow_not_applicable"):
                if not isinstance(rule.get(field), bool):
                    raise ValueError(f"{rule.get('id')}: {field} must be a boolean")
            if rule["id"] in catalog:
                raise ValueError(f"duplicate rule id: {rule['id']}")
            catalog[rule["id"]] = rule
    if not catalog:
        raise ValueError(f"No rules for {dataset_type!r} in {directory}")
    return catalog


def required_rule_ids(dataset_type: str, *, rules_dir: Path | None = None) -> tuple[str, ...]:
    if dataset_type not in {"process", "model"}:
        return ()
    return tuple(rule_id for rule_id, rule in load_rule_catalog(dataset_type, rules_dir=rules_dir).items()
                 if rule["agent_review_required"])


class RequiredRuleIds(Mapping[str, tuple[str, ...]]):
    """Legacy mapping API with no import-time catalog snapshot."""

    def __getitem__(self, key: str) -> tuple[str, ...]:
        if key not in self:
            raise KeyError(key)
        return required_rule_ids(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("process", "model"))

    def __len__(self) -> int:
        return 2

    def __contains__(self, key: object) -> bool:
        return key in ("process", "model")
