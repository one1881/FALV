"""将现有数据库账号收敛为一个起草用户和一个审核员。"""

import sys

sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.contract import Contract
from app.models.user import User
from app.models.workflow import (
    ApprovalStep,
    ApprovalWorkflow,
    ContractArchiveRecord,
    ContractWorkflowRun,
)
from sqlalchemy import inspect


def main() -> None:
    with SessionLocal() as db:
        tables = set(inspect(db.bind).get_table_names())
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                password_hash=get_password_hash("password123"),
                full_name="业务用户",
                email="admin@example.com",
                role="user",
            )
            db.add(admin)
            db.flush()
        else:
            admin.role = "user"
            admin.full_name = "业务用户"

        reviewer = db.query(User).filter(User.username == "reviewer").first()
        legacy_legal = db.query(User).filter(User.username == "legal").first()
        if not reviewer and legacy_legal:
            legacy_legal.username = "reviewer"
            reviewer = legacy_legal
        if not reviewer:
            reviewer = User(
                username="reviewer",
                password_hash=get_password_hash("password123"),
                full_name="审核员",
                email="reviewer@example.com",
                role="reviewer",
            )
            db.add(reviewer)
            db.flush()
        else:
            reviewer.role = "reviewer"
            reviewer.full_name = "审核员"

        keep_ids = {admin.id, reviewer.id}
        legacy_users = db.query(User).filter(~User.id.in_(keep_ids)).all()
        for legacy in legacy_users:
            db.query(Contract).filter(Contract.created_by == legacy.id).update(
                {Contract.created_by: admin.id}, synchronize_session=False
            )
            if "contract_workflow_runs" in tables:
                db.query(ContractWorkflowRun).filter(
                    ContractWorkflowRun.initiated_by == legacy.id
                ).update({ContractWorkflowRun.initiated_by: admin.id}, synchronize_session=False)
            if "approval_workflows" in tables:
                db.query(ApprovalWorkflow).filter(
                    ApprovalWorkflow.submitted_by == legacy.id
                ).update({ApprovalWorkflow.submitted_by: admin.id}, synchronize_session=False)
            if "approval_steps" in tables:
                db.query(ApprovalStep).filter(ApprovalStep.approver_id == legacy.id).update(
                    {ApprovalStep.approver_id: reviewer.id, ApprovalStep.approver_name: reviewer.full_name},
                    synchronize_session=False,
                )
            if "contract_archive_records" in tables:
                db.query(ContractArchiveRecord).filter(
                    ContractArchiveRecord.archived_by == legacy.id
                ).update({ContractArchiveRecord.archived_by: reviewer.id}, synchronize_session=False)
            db.delete(legacy)

        db.commit()
        print("账号已收敛为：admin/password123 与 reviewer/password123")


if __name__ == "__main__":
    main()
