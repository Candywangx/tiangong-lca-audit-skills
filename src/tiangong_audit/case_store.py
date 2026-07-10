from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from tiangong_audit.contracts import AuditCaseManifest, OperationLogEntry

CASE_SUBDIRS = (
    "snapshots",
    "sources",
    "precheck",
    "source-checks",
    "agent-review",
    "reports",
    "operations",
)


class CaseStoreError(RuntimeError):
    """Raised when local case storage cannot satisfy a request."""


class CaseStore:
    """Manage the canonical cases/active/<review-id> layout."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / "index.jsonl"

    def init_batch(self, batch_id: str) -> Path:
        self._validate_id(batch_id, "batch id")
        batch_dir = self.root / "batches" / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        manifest = batch_dir / "manifest.json"
        if not manifest.exists():
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "tiangong-audit-batch-v1",
                        "batch_id": batch_id,
                        "reviews": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return batch_dir

    def create_case(
        self,
        *,
        review_id: str,
        batch_id: str,
        dataset_id: str = "",
        version: str = "",
        dataset_type: str = "",
        name_zh: str = "",
        name_en: str = "",
        force: bool = False,
    ) -> AuditCaseManifest:
        self._validate_id(review_id, "review id")
        case_dir = self.root / "active" / review_id
        case_path = case_dir / "case.json"
        if case_path.exists() and not force:
            raise CaseStoreError(f"Case already exists: {case_dir}")

        for subdir in CASE_SUBDIRS:
            (case_dir / subdir).mkdir(parents=True, exist_ok=True)

        manifest = AuditCaseManifest(
            review_id=review_id,
            batch_id=batch_id,
            dataset_id=dataset_id,
            version=version,
            dataset_type=dataset_type,
            name_zh=name_zh,
            name_en=name_en,
            case_dir=str(case_dir.relative_to(self.root)),
        )
        self.write_case(manifest)
        return manifest

    def write_case(self, manifest: AuditCaseManifest) -> None:
        case_dir = self.root / manifest.case_dir
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "case.json").write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._upsert_index(manifest)

    def get_case(self, review_id: str, batch_id: str | None = None) -> AuditCaseManifest:
        for record in self.iter_index():
            if record.get("review_id") != review_id:
                continue
            if batch_id and record.get("batch_id") != batch_id:
                continue
            case_dir = str(record.get("case_dir") or "")
            if not case_dir:
                break
            return self.read_case_path(self.root / case_dir / "case.json")
        raise CaseStoreError(f"Case not found: {review_id}")

    def read_case_path(self, path: Path) -> AuditCaseManifest:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise CaseStoreError(f"Unable to read case manifest: {path}") from error
        return AuditCaseManifest.from_dict(payload)

    def list_cases(self, *, status: str | None = None) -> list[dict]:
        records = list(self.iter_index())
        if status:
            records = [record for record in records if record.get("status") == status]
        return sorted(
            records,
            key=lambda item: (
                str(item.get("batch_id") or ""),
                str(item.get("review_id") or ""),
            ),
        )

    def iter_index(self) -> Iterable[dict]:
        if not self.index_path.exists():
            return []
        records = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records

    def append_operation(
        self, manifest: AuditCaseManifest, entry: OperationLogEntry
    ) -> Path:
        target = self.root / manifest.case_dir / "operations" / "oplog.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return target

    def _upsert_index(self, manifest: AuditCaseManifest) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        key = manifest.review_id
        records = [
            record
            for record in self.iter_index()
            if record.get("review_id") != key
        ]
        records.append(manifest.index_record())
        content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        self.index_path.write_text((content + "\n") if content else "", encoding="utf-8")

    @staticmethod
    def _upsert_batch_review(path: Path, review_id: str) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reviews = list(payload.get("reviews") or [])
        if review_id not in reviews:
            reviews.append(review_id)
        payload["reviews"] = sorted(reviews)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        if not value or "/" in value or "\\" in value:
            raise CaseStoreError(f"Invalid {label}: {value!r}")
