from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class ContractStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    EXPIRED = "expired"


class ContractType(str, enum.Enum):
    SALES = "sales"
    PURCHASE = "purchase"
    SERVICE = "service"
    EMPLOYMENT = "employment"
    NDA = "nda"
    OTHER = "other"


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    contract_number = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    contract_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default='draft')

    # 关联客户
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)
    customer_name = Column(String(200), nullable=True)

    # 合同金额
    amount = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(10), default='CNY')

    # 合同日期
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    signing_date = Column(DateTime(timezone=True), nullable=True)

    # 合同内容
    content = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)

    # 创建人
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    customer = relationship("Customer", backref="contracts")
    creator = relationship("User", backref="created_contracts")
    workflow_runs = relationship("ContractWorkflowRun", back_populates="contract", cascade="all, delete-orphan")
    workflow_reports = relationship("WorkflowReport", back_populates="contract", cascade="all, delete-orphan")
    approval_workflows = relationship("ApprovalWorkflow", back_populates="contract", cascade="all, delete-orphan")
    approval_steps = relationship("ApprovalStep", back_populates="contract", cascade="all, delete-orphan")
    archive_records = relationship("ContractArchiveRecord", back_populates="contract", cascade="all, delete-orphan")
    review_records = relationship("ReviewRecord", back_populates="contract", cascade="all, delete-orphan")

    @property
    def created_by_name(self):
        return self.creator.full_name if self.creator else None

    @property
    def owner_lawyer_id(self):
        return self.created_by

    @property
    def owner_lawyer_name(self):
        return self.created_by_name

    @property
    def status_label(self):
        labels = {
            "draft": "草稿",
            "drafting": "起草中",
            "pending": "待审核",
            "reviewing": "审核中",
            "approved": "已通过",
            "final": "已通过",
            "active": "已通过",
            "rejected": "已驳回",
            "archived": "已归档",
            "expired": "已归档",
        }
        return labels.get(self.status, self.status or "草稿")

    @property
    def is_completed(self):
        return self.status in {"approved", "final", "active", "archived", "expired"}

    def to_dict(self):
        return {
            "id": self.id,
            "contract_number": self.contract_number,
            "title": self.title,
            "contract_type": self.contract_type,
            "status": self.status,
            "status_label": self.status_label,
            "is_completed": self.is_completed,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "amount": float(self.amount) if self.amount else None,
            "currency": self.currency,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "signing_date": self.signing_date.isoformat() if self.signing_date else None,
            "content": self.content,
            "file_path": self.file_path,
            "created_by": self.created_by,
            "created_by_name": self.created_by_name,
            "owner_lawyer_id": self.owner_lawyer_id,
            "owner_lawyer_name": self.owner_lawyer_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
