from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.workflow import ApprovalStep, ApprovalWorkflow
from app.services.workflow_service import step_to_dict, workflow_to_dict

router = APIRouter(prefix="/approvals", tags=["Approvals"])


def _can_manage_all(user: User) -> bool:
    return user.role == "reviewer"


@router.get("")
async def list_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    scope: str = Query("all", pattern="^(all|my_pending|my_submitted)$"),
    approver_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ApprovalStep)
        .options(joinedload(ApprovalStep.contract), joinedload(ApprovalStep.workflow))
        .join(ApprovalWorkflow, ApprovalWorkflow.id == ApprovalStep.workflow_id)
    )
    if status_filter:
        query = query.filter(ApprovalStep.status == status_filter)
    if approver_id:
        query = query.filter(ApprovalStep.approver_id == approver_id)
    elif scope == "my_pending":
        query = query.filter(
            ApprovalStep.status == "pending",
            ApprovalStep.approver_id == current_user.id,
        )
    elif scope == "my_submitted":
        query = query.filter(ApprovalWorkflow.submitted_by == current_user.id)
    elif not _can_manage_all(current_user):
        query = query.filter(
            (ApprovalStep.approver_id == current_user.id)
            | (ApprovalWorkflow.submitted_by == current_user.id)
        )

    items = query.order_by(ApprovalStep.created_at.desc(), ApprovalStep.step_number.asc()).all()
    return {"total": len(items), "items": [step_to_dict(item) for item in items]}


@router.get("/{workflow_id}")
async def get_approval_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflow = (
        db.query(ApprovalWorkflow)
        .options(joinedload(ApprovalWorkflow.steps).joinedload(ApprovalStep.contract))
        .filter(ApprovalWorkflow.workflow_id == workflow_id)
        .first()
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="审批流程不存在")
    if (
        not _can_manage_all(current_user)
        and workflow.submitted_by != current_user.id
        and not any(step.approver_id == current_user.id for step in workflow.steps)
    ):
        raise HTTPException(status_code=403, detail="无权查看该审批流程")
    return workflow_to_dict(workflow)


def _load_actionable_step(db: Session, step_id: int, user: User) -> ApprovalStep:
    step = (
        db.query(ApprovalStep)
        .options(joinedload(ApprovalStep.workflow), joinedload(ApprovalStep.contract))
        .filter(ApprovalStep.id == step_id)
        .first()
    )
    if not step:
        raise HTTPException(status_code=404, detail="审批节点不存在")
    if step.status != "pending":
        raise HTTPException(status_code=409, detail="该节点当前不可处理")
    if step.approver_id != user.id and not _can_manage_all(user):
        raise HTTPException(status_code=403, detail="当前用户不是该节点审批人")
    return step


@router.post("/{step_id}/approve")
async def approve_step(
    step_id: int,
    payload: Optional[dict] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    step = _load_actionable_step(db, step_id, current_user)
    payload = payload or {}
    step.status = "approved"
    step.comments = payload.get("comments")
    step.approved_at = datetime.now(timezone.utc)

    next_step = (
        db.query(ApprovalStep)
        .filter(
            ApprovalStep.workflow_id == step.workflow_id,
            ApprovalStep.step_number == step.step_number + 1,
        )
        .first()
    )
    if next_step:
        next_step.status = "pending"
        step.workflow.status = "pending"
        message = "当前节点已通过，已流转到下一审批节点"
    else:
        step.workflow.status = "approved"
        step.workflow.completed_at = datetime.now(timezone.utc)
        step.contract.status = "approved"
        message = "审批流程已全部通过，合同已进入待归档状态"

    db.commit()
    db.refresh(step.workflow)
    return {"status": "success", "message": message, "workflow": workflow_to_dict(step.workflow)}


@router.post("/{step_id}/reject")
async def reject_step(
    step_id: int,
    payload: Optional[dict] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    step = _load_actionable_step(db, step_id, current_user)
    payload = payload or {}
    comments = (payload.get("comments") or "").strip()
    if not comments:
        raise HTTPException(status_code=422, detail="驳回时必须填写意见")

    step.status = "rejected"
    step.comments = comments
    step.approved_at = datetime.now(timezone.utc)
    step.workflow.status = "rejected"
    step.workflow.completed_at = datetime.now(timezone.utc)
    step.contract.status = "rejected"
    db.commit()
    db.refresh(step.workflow)
    return {
        "status": "success",
        "message": "合同已驳回并退回律师修改",
        "workflow": workflow_to_dict(step.workflow),
    }


@router.post("/{workflow_id}/withdraw")
async def withdraw_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workflow = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.workflow_id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="审批流程不存在")
    if workflow.submitted_by != current_user.id and not _can_manage_all(current_user):
        raise HTTPException(status_code=403, detail="只有提交律师可以撤回审批")
    if workflow.status != "pending":
        raise HTTPException(status_code=409, detail="当前流程不可撤回")

    workflow.status = "withdrawn"
    workflow.completed_at = datetime.now(timezone.utc)
    workflow.contract.status = "draft"
    for step in workflow.steps:
        if step.status in {"waiting", "pending"}:
            step.status = "withdrawn"
    db.commit()
    db.refresh(workflow)
    return {"status": "success", "workflow": workflow_to_dict(workflow)}
