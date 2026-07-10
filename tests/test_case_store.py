import json

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts import OperationLogEntry


def test_case_store_creates_canonical_case_and_index(tmp_path):
    store = CaseStore(tmp_path / "cases")

    manifest = store.create_case(
        review_id="review-1",
        batch_id="batch-1",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="自来水生产",
    )

    case_dir = tmp_path / "cases" / "active" / "review-1"
    assert manifest.case_dir == "active/review-1"
    assert (case_dir / "case.json").exists()
    for subdir in ("snapshots", "sources", "precheck", "source-checks", "reports", "operations"):
        assert (case_dir / subdir).is_dir()

    records = list(store.iter_index())
    assert records[0]["review_id"] == "review-1"
    assert records[0]["status"] == "initialized"
    assert store.get_case("review-1").dataset_id == "dataset-1"


def test_case_store_updates_index_and_operation_log(tmp_path):
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(review_id="review-1", batch_id="batch-1")
    manifest.status = "reported"
    manifest.report = "active/review-1/reports/audit-report.md"

    store.write_case(manifest)
    oplog = store.append_operation(
        manifest,
        OperationLogEntry(operation="source_fetch", status="completed", target_id="review-1"),
    )

    assert store.list_cases(status="reported")[0]["review_id"] == "review-1"
    line = oplog.read_text(encoding="utf-8").strip()
    assert json.loads(line)["operation"] == "source_fetch"
