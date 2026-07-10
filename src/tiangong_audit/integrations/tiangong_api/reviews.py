"""Review queue operations for the Tiangong platform."""

from __future__ import annotations

from typing import Any, Literal

from .client import TiangongAPIClient, TiangongAPIError
from .models import AuditResult, PlatformAction

AdminQueueStatus = Literal["unassigned", "assigned", "admin-rejected"]
MemberQueueStatus = Literal["pending", "reviewed", "reviewer-rejected"]
ReviewActionOperation = Literal["save-draft", "submit"]


def _queue_result(rows: Any, page: int, page_size: int) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise TiangongAPIError("Platform review queue response must be a list")
    total = int(rows[0].get("total_count", 0)) if rows else 0
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


class ReviewAPI:
    """Read review queues and explicitly invoke confirmed review writes."""

    def __init__(self, client: TiangongAPIClient):
        self.client = client

    def get_admin_tasks(
        self,
        status: AdminQueueStatus = "unassigned",
        *,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "modified_at",
        sort_order: str = "descend",
    ) -> dict[str, Any]:
        rows = self.client.rpc(
            "qry_review_get_admin_queue_items",
            {
                "p_status": status,
                "p_page": page,
                "p_page_size": page_size,
                "p_sort_by": sort_by,
                "p_sort_order": sort_order,
            },
        )
        return _queue_result(rows, page, page_size)

    def get_member_tasks(
        self,
        status: MemberQueueStatus = "pending",
        *,
        page: int = 1,
        page_size: int = 10,
        sort_by: str = "modified_at",
        sort_order: str = "descend",
    ) -> dict[str, Any]:
        rows = self.client.rpc(
            "qry_review_get_member_queue_items",
            {
                "p_status": status,
                "p_page": page,
                "p_page_size": page_size,
                "p_sort_by": sort_by,
                "p_sort_order": sort_order,
            },
        )
        return _queue_result(rows, page, page_size)

    def get_task(self, task_id: str) -> dict[str, Any]:
        rows = self.client.rpc(
            "qry_review_get_items",
            {
                "p_review_ids": [task_id],
                "p_data_id": None,
                "p_data_version": None,
                "p_state_codes": None,
            },
        )
        if not isinstance(rows, list) or not rows:
            raise TiangongAPIError(f"Review task not found: {task_id}")
        return rows[0]

    def assign_reviewers(
        self,
        task_id: str,
        reviewer_ids: list[str],
        *,
        deadline: str | None = None,
        audit: dict[str, Any] | None = None,
    ) -> Any:
        if not reviewer_ids:
            raise ValueError("At least one reviewer ID is required")
        return self.client.command(
            "cmd_review_assign_reviewers",
            {
                "p_audit": audit,
                "p_deadline": deadline,
                "p_review_id": task_id,
                "p_reviewer_ids": reviewer_ids,
            },
        )

    def save_comment_draft(self, task_id: str, comment: dict[str, Any]) -> Any:
        return self.client.invoke_function(
            "app_review_save_comment_draft",
            {"reviewId": task_id, "json": comment},
        )

    def submit_result(self, task_id: str, result: AuditResult) -> Any:
        comment = {
            "conclusion": result.conclusion,
            "summary": result.summary,
            "findings": [
                {
                    "id": finding.id,
                    "severity": finding.severity.value,
                    "title": finding.title,
                    "description": finding.description,
                    "evidence": finding.evidence,
                    "suggested_fix": finding.suggested_fix,
                    "related_field": finding.related_field,
                    "tags": finding.tags,
                }
                for finding in result.findings
            ],
            "auditor_notes": result.auditor_notes,
        }
        return self.client.invoke_function(
            "app_review_submit_comment",
            {"reviewId": task_id, "json": comment},
        )

    @staticmethod
    def generate_platform_actions(
        result: AuditResult,
        *,
        operation: ReviewActionOperation = "save-draft",
    ) -> list[PlatformAction]:
        """Generate a reviewable action plan without executing platform writes."""
        if operation == "save-draft":
            return [
                PlatformAction(
                    action_type="save_comment_draft",
                    target_id=result.review_task_id,
                    parameters={
                        "conclusion": result.conclusion,
                        "summary": result.summary,
                        "finding_count": len(result.findings),
                    },
                    description=(
                        "Save the audit comment draft to Tiangong without submitting "
                        "the review"
                    ),
                )
            ]
        if operation == "submit":
            return [
                PlatformAction(
                    action_type="submit_review_comment",
                    target_id=result.review_task_id,
                    parameters={"conclusion": result.conclusion, "summary": result.summary},
                    description="Submit the confirmed audit comment to Tiangong",
                )
            ]
        raise ValueError(f"Unsupported platform action operation: {operation}")
