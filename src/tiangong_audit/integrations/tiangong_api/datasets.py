"""Read process and lifecycle-model datasets from Tiangong."""

from __future__ import annotations

from typing import Any

from .client import TiangongAPIClient, TiangongAPIError
from .models import DatasetType

PROCESS_COLUMNS = (
    "id,version,json,modified_at,state_code,rule_verification,team_id,reviews"
)
MODEL_COLUMNS = (
    "id,version,json,json_tg,modified_at,state_code,rule_verification,team_id,reviews"
)
SOURCE_COLUMNS = (
    "id,version,json,json_ordered,modified_at,state_code,rule_verification,user_id"
)
FLOW_COLUMNS = "id,version,json"


class DatasetAPI:
    """Read-only access to auditable Tiangong datasets."""

    def __init__(self, client: TiangongAPIClient):
        self.client = client

    def get_dataset(
        self,
        dataset_id: str,
        version: str,
        dataset_type: DatasetType,
    ) -> dict[str, Any]:
        table = "processes" if dataset_type == DatasetType.PROCESS else "lifecyclemodels"
        columns = PROCESS_COLUMNS if dataset_type == DatasetType.PROCESS else MODEL_COLUMNS
        rows = self.client.select(
            table,
            columns=columns,
            filters={"id": f"eq.{dataset_id}", "version": f"eq.{version}"},
            limit=1,
        )
        if not rows:
            raise TiangongAPIError(
                f"{dataset_type.value} dataset not found: {dataset_id} {version}"
            )
        return rows[0]

    def get_process(self, dataset_id: str, version: str) -> dict[str, Any]:
        return self.get_dataset(dataset_id, version, DatasetType.PROCESS)

    def get_model(self, dataset_id: str, version: str) -> dict[str, Any]:
        return self.get_dataset(dataset_id, version, DatasetType.MODEL)

    def get_source(self, source_id: str, version: str = "") -> dict[str, Any]:
        filters = {"id": f"eq.{source_id}"}
        if version:
            filters["version"] = f"eq.{version}"
        rows = self.client.select(
            "sources",
            columns=SOURCE_COLUMNS,
            filters=filters,
            limit=1,
        )
        if not rows:
            version_label = f" {version}" if version else ""
            raise TiangongAPIError(f"source dataset not found: {source_id}{version_label}")
        return rows[0]

    def get_flow(self, flow_id: str, version: str = "") -> dict[str, Any]:
        if not version:
            raise TiangongAPIError(
                f"flow dataset lookup requires an explicit version: {flow_id}"
            )
        filters = {"id": f"eq.{flow_id}"}
        filters["version"] = f"eq.{version}"
        rows = self.client.select(
            "flows",
            columns=FLOW_COLUMNS,
            filters=filters,
            limit=1,
        )
        if not rows:
            version_label = f" {version}" if version else ""
            raise TiangongAPIError(f"flow dataset not found: {flow_id}{version_label}")
        return rows[0]

    def resolve_dataset(self, dataset_id: str, version: str) -> dict[str, Any]:
        """Identify a task dataset and return its platform payload."""
        model_rows = self.client.select(
            "lifecyclemodels",
            columns=MODEL_COLUMNS,
            filters={"id": f"eq.{dataset_id}", "version": f"eq.{version}"},
            limit=1,
        )
        if model_rows:
            return {"dataset_type": DatasetType.MODEL.value, "data": model_rows[0]}
        return {
            "dataset_type": DatasetType.PROCESS.value,
            "data": self.get_process(dataset_id, version),
        }
