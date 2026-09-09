from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.user import User
from app.models.workflow import (
    ApprovalStep,
    ApprovalWorkflow,
    ContractArchiveRecord,
    ContractWorkflowRun,
    WorkflowReport,
)


def json_safe(value: Any) -> Any:
    """Make agent output safe for PostgreSQL JSON columns."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def save_workflow_run(
    db: Session,
    contract: Contract,
    user_id: int,
    request_payload: Dict[str, Any],
    result: Dict[str, Any],
) -> ContractWorkflowRun:
    run = ContractWorkflowRun(
        run_id=f"RUN-{uuid.uuid4().hex[:20].upper()}",
        contract_id=contract.id,
        initiated_by=user_id,
        status="completed" if result.get("workflow_status") == "success" else "failed",
        execution_time=result.get("execution_time"),
        request_payload=json_safe(request_payload),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    reports = [
        ("data_collection", "DataCollectorAgent", result.get("data_collection", {})),
        ("similarity_search", "SimilarityMatcherAgent", result.get("similarity_search", {})),
        ("compliance", "ComplianceCheckerAgent", result.get("compliance_check", {})),
        ("risk", "RiskEvaluatorAgent", result.get("risk_assessment", {})),
        ("template_selection", "TemplateSelectorAgent", result.get("template_selection", {})),
        ("generation", "ContractGeneratorAgent", result.get("contract_generation", {})),
        ("summary", "ContractSummaryAgent", result.get("contract_summary", {})),
    ]
    for report_type, agent_name, payload in reports:
        db.add(
            WorkflowReport(
                run_id=run.id,
                contract_id=contract.id,
                report_type=report_type,
                agent_name=agent_name,
                status="completed",
                payload=json_safe(payload or {}),
            )
        )
    return run


def _risk_bucket(risk_score: Optional[float], risk_level: Optional[str]) -> str:
    if risk_score is not None:
        score = float(risk_score)
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"
    level = (risk_level or "").lower()
    if level in {"high", "高", "high-risk"}:
        return "high"
    if level in {"medium", "中", "middle"}:
        return "medium"
    return "low"


def _required_roles(risk_score: Optional[float], risk_level: Optional[str], amount: Any) -> list[str]:
    # 当前产品只保留一个审核角色，所有用户提交的请求统一进入审核员收件箱。
    return ["reviewer"]


ROLE_CANDIDATES = {
    "reviewer": ("reviewer",),
}


def _resolve_approver(
    db: Session,
    role: str,
    used_ids: set[int],
    submitter_id: int,
) -> Optional[User]:
    candidates = ROLE_CANDIDATES.get(role, ())
    users = db.query(User).order_by(User.id.asc()).all()
    for candidate_role in candidates:
        for user in users:
            if user.id != submitter_id and user.id not in used_ids and user.role == candidate_role:
                return user
    for user in users:
        if user.id != submitter_id and user.id not in used_ids and user.role == "reviewer":
            return user
    return None


def create_approval_workflow(
    db: Session,
    contract: Contract,
    submitted_by: User,
    summary: Optional[str],
    risk_score: Optional[float],
    risk_level: Optional[str],
) -> ApprovalWorkflow:
    existing = (
        db.query(ApprovalWorkflow)
        .filter(
            ApprovalWorkflow.contract_id == contract.id,
            ApprovalWorkflow.status.in_(("pending", "returned")),
        )
        .first()
    )
    if existing:
        return existing

    roles = _required_roles(risk_score, risk_level, contract.amount)
    workflow = ApprovalWorkflow(
        workflow_id=f"WF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
        contract_id=contract.id,
        submitted_by=submitted_by.id,
        status="pending",
        risk_score=risk_score,
        risk_level=risk_level,
        summary=summary,
        routing_reason=f"风险等级 {risk_level or '未提供'}，风险分数 {risk_score if risk_score is not None else '未提供'}，金额 {float(contract.amount or 0):,.2f}",
    )
    db.add(workflow)
    db.flush()

    used_ids: set[int] = set()
    now = datetime.now(timezone.utc)
    for index, role in enumerate(roles, start=1):
        approver = _resolve_approver(db, role, used_ids, submitted_by.id)
        if approver:
            used_ids.add(approver.id)
        db.add(
            ApprovalStep(
                workflow_id=workflow.id,
                contract_id=contract.id,
                step_number=index,
                approver_role=role,
                approver_id=approver.id if approver else None,
                approver_name=approver.full_name if approver else "待配置审批人",
                status="pending" if index == 1 else "waiting",
                deadline=now + timedelta(days=index + 2),
            )
        )

    contract.status = "pending"
    db.flush()
    return workflow


def workflow_to_dict(workflow: ApprovalWorkflow) -> Dict[str, Any]:
    current = next((step for step in workflow.steps if step.status == "pending"), None)
    return {
        "id": workflow.id,
        "workflow_id": workflow.workflow_id,
        "contract_id": workflow.contract_id,
        "status": workflow.status,
        "risk_score": float(workflow.risk_score) if workflow.risk_score is not None else None,
        "risk_level": workflow.risk_level,
        "summary": workflow.summary,
        "routing_reason": workflow.routing_reason,
        "submitted_by": workflow.submitted_by,
        "submitted_at": workflow.submitted_at.isoformat() if workflow.submitted_at else None,
        "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
        "current_step_id": current.id if current else None,
        "steps": [step_to_dict(step) for step in workflow.steps],
    }


def step_to_dict(step: ApprovalStep) -> Dict[str, Any]:
    contract = step.contract
    workflow = step.workflow
    submitter = workflow.submitter if workflow else None
    reviewer = step.approver
    status_labels = {
        "waiting": "待审核",
        "pending": "待审核",
        "reviewing": "审核中",
        "approved": "已通过",
        "completed": "已完成",
        "rejected": "需修改",
        "withdrawn": "已撤回",
    }
    is_completed = bool(step.approved_at or (workflow and workflow.completed_at) or step.status in {"approved", "completed", "rejected"})
    return {
        "id": step.id,
        "workflow_id": step.workflow_id,
        "workflow_public_id": workflow.workflow_id if workflow else None,
        "workflow_status": workflow.status if workflow else None,
        "workflow_submitted_at": workflow.submitted_at.isoformat() if workflow and workflow.submitted_at else None,
        "workflow_completed_at": workflow.completed_at.isoformat() if workflow and workflow.completed_at else None,
        "workflow_summary": workflow.summary if workflow else None,
        "workflow_risk_score": float(workflow.risk_score) if workflow and workflow.risk_score is not None else None,
        "workflow_risk_level": workflow.risk_level if workflow else None,
        "submitted_by": workflow.submitted_by if workflow else None,
        "submitted_by_name": submitter.full_name if submitter else None,
        "reviewer_id": step.approver_id,
        "reviewer_name": reviewer.full_name if reviewer else step.approver_name,
        "review_status_label": status_labels.get(step.status, step.status),
        "is_completed": is_completed,
        "step_number": step.step_number,
        "approver_role": step.approver_role,
        "approver_id": step.approver_id,
        "approver_name": reviewer.full_name if reviewer else step.approver_name,
        "status": step.status,
        "deadline": step.deadline.isoformat() if step.deadline else None,
        "approved_at": step.approved_at.isoformat() if step.approved_at else None,
        "comments": step.comments,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "contract": {
            "id": contract.id,
            "contract_number": contract.contract_number,
            "title": contract.title,
            "customer_name": contract.customer_name,
            "amount": float(contract.amount) if contract.amount is not None else None,
            "contract_type": contract.contract_type,
            "status": contract.status,
            "status_label": contract.status_label,
            "is_completed": contract.is_completed,
            "created_by": contract.created_by,
            "created_by_name": contract.created_by_name,
            "content": contract.content,
        } if contract else None,
    }


def archive_contract(
    db: Session,
    contract: Contract,
    archivist: User,
    reason: Optional[str],
) -> ContractArchiveRecord:
    record = ContractArchiveRecord(
        contract_id=contract.id,
        archived_by=archivist.id,
        archive_reason=reason,
        content_snapshot=contract.content,
        metadata_snapshot=json_safe(
            {
                "contract_number": contract.contract_number,
                "title": contract.title,
                "contract_type": contract.contract_type,
                "customer_id": contract.customer_id,
                "customer_name": contract.customer_name,
                "amount": contract.amount,
                "currency": contract.currency,
                "signing_date": contract.signing_date,
                "status_before_archive": contract.status,
            }
        ),
    )
    contract.status = "archived"
    db.add(record)
    db.flush()
    return record
