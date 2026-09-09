from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    # documents 表已随死代码清理移除，这里只保留列值（历史数据兼容），不再建外键
    document_id = Column(Integer, nullable=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True, index=True)
    review_public_id = Column(String(50), unique=True, nullable=False, index=True)
    document_type = Column(String(50), nullable=True)
    review_status = Column(String(20), nullable=False, default="warning", index=True)
    overall_score = Column(Float, nullable=True)
    legal_compliance_score = Column(Float, nullable=True)
    logic_consistency_score = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    dimensions = Column(JSON, nullable=True)
    issues = Column(JSON, nullable=True)
    suggestions = Column(JSON, nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now())

    contract = relationship("Contract", back_populates="review_records")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
