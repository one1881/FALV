from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ContractWorkflowRun(Base):
    __tablename__ = "contract_workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    initiated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(30), nullable=False, default="completed")
    execution_time = Column(Numeric(10, 3), nullable=True)
    request_payload = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    contract = relationship("Contract", back_populates="workflow_runs")
    reports = relationship(
        "WorkflowReport",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WorkflowReport.created_at",
    )


class WorkflowReport(Base):
    __tablename__ = "workflow_reports"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("contract_workflow_runs.id"), nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    report_type = Column(String(50), nullable=False, index=True)
    agent_name = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default="completed")
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("ContractWorkflowRun", back_populates="reports")
    contract = relationship("Contract", back_populates="workflow_reports")


class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(64), unique=True, nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    risk_score = Column(Numeric(8, 2), nullable=True)
    risk_level = Column(String(20), nullable=True)
    summary = Column(Text, nullable=True)
    routing_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    contract = relationship("Contract", back_populates="approval_workflows")
    submitter = relationship("User", foreign_keys=[submitted_by])
    steps = relationship(
        "ApprovalStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ApprovalStep.step_number",
    )


class ApprovalStep(Base):
    __tablename__ = "approval_steps"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("approval_workflows.id"), nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    approver_role = Column(String(50), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    approver_name = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default="waiting", index=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workflow = relationship("ApprovalWorkflow", back_populates="steps")
    contract = relationship("Contract", back_populates="approval_steps")
    approver = relationship("User", foreign_keys=[approver_id])


class ContractArchiveRecord(Base):
    __tablename__ = "contract_archive_records"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    archived_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    archive_reason = Column(Text, nullable=True)
    content_snapshot = Column(Text, nullable=True)
    metadata_snapshot = Column(JSON, nullable=True)
    archived_at = Column(DateTime(timezone=True), server_default=func.now())

    contract = relationship("Contract", back_populates="archive_records")
    archivist = relationship("User", foreign_keys=[archived_by])
