from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class LitigationCase(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String(50), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    case_title = Column(String(200), nullable=True)
    case_summary = Column(Text, nullable=True)
    claims = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="draft", index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    customer = relationship("Customer", backref="litigation_cases")
    creator = relationship("User", backref="created_litigation_cases")
    parties = relationship("CaseParty", back_populates="case", cascade="all, delete-orphan")
    evidence_items = relationship("EvidenceItem", back_populates="case", cascade="all, delete-orphan")
    facts = relationship("FactIssue", back_populates="case", cascade="all, delete-orphan")
    cause_opinions = relationship("CauseOpinion", back_populates="case", cascade="all, delete-orphan")
    jurisdiction_opinions = relationship("JurisdictionOpinion", back_populates="case", cascade="all, delete-orphan")
    workflow_results = relationship("LitigationWorkflowResult", back_populates="case", cascade="all, delete-orphan", order_by="LitigationWorkflowResult.created_at.desc()")


class LitigationWorkflowResult(Base):
    __tablename__ = "litigation_workflow_results"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False, default="full_litigation")
    status = Column(String(30), nullable=False, default="success")
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("LitigationCase", back_populates="workflow_results")


class CaseParty(Base):
    __tablename__ = "case_parties"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    party_type = Column(String(20), nullable=True)
    entity_type = Column(String(20), nullable=True)
    name = Column(String(200), nullable=True)
    id_number = Column(String(30), nullable=True)
    credit_code = Column(String(30), nullable=True)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    enterprise_info = Column(JSON, nullable=True)

    case = relationship("LitigationCase", back_populates="parties")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(String(50), unique=True, nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type = Column(String(50), nullable=True)
    evidence_name = Column(String(200), nullable=True)
    file_path = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    ocr_text = Column(Text, nullable=True)
    entities = Column(JSON, nullable=True)
    proof_purpose = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("LitigationCase", back_populates="evidence_items")
    extracts = relationship("EvidenceExtract", back_populates="evidence", cascade="all, delete-orphan")
    fact_links = relationship("FactEvidenceLink", back_populates="evidence", cascade="all, delete-orphan")


class EvidenceExtract(Base):
    __tablename__ = "evidence_extracts"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    ocr_text = Column(Text, nullable=True)
    entities = Column(JSON, nullable=True)
    embedding = Column(JSON, nullable=True)
    extracted_at = Column(DateTime(timezone=True), server_default=func.now())

    evidence = relationship("EvidenceItem", back_populates="extracts")


class FactIssue(Base):
    __tablename__ = "fact_issues"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    fact_description = Column(Text, nullable=True)
    sufficiency = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=True)

    case = relationship("LitigationCase", back_populates="facts")
    evidence_links = relationship("FactEvidenceLink", back_populates="fact", cascade="all, delete-orphan")


class FactEvidenceLink(Base):
    __tablename__ = "fact_evidence_links"
    __table_args__ = (UniqueConstraint("fact_id", "evidence_id", name="uq_fact_evidence_link"),)

    id = Column(Integer, primary_key=True, index=True)
    fact_id = Column(Integer, ForeignKey("fact_issues.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True)
    link_strength = Column(Float, nullable=True)

    fact = relationship("FactIssue", back_populates="evidence_links")
    evidence = relationship("EvidenceItem", back_populates="fact_links")


class CauseOpinion(Base):
    __tablename__ = "cause_opinions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    cause_name = Column(String(100), nullable=True)
    cause_code = Column(String(20), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    legal_basis = Column(Text, nullable=True)

    case = relationship("LitigationCase", back_populates="cause_opinions")


class JurisdictionOpinion(Base):
    __tablename__ = "jurisdiction_opinions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    court_name = Column(String(100), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=True)
    legal_basis = Column(Text, nullable=True)

    case = relationship("LitigationCase", back_populates="jurisdiction_opinions")


class LitigationIntake(Base):
    __tablename__ = "litigation_intakes"

    id = Column(Integer, primary_key=True, index=True)
    intake_id = Column(String(50), unique=True, nullable=False, index=True)
    source = Column(String(50), nullable=True)
    case_type = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default="draft", index=True)
    customer_name = Column(String(200), nullable=True)
    opposite_party = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    archived_case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    creator = relationship("User", backref="litigation_intakes")
    archived_case = relationship("LitigationCase", backref="source_intakes")
    materials = relationship("LitigationMaterial", back_populates="intake", cascade="all, delete-orphan")
    drafts = relationship("CaseIntakeDraft", back_populates="intake", cascade="all, delete-orphan")


class LitigationMaterial(Base):
    __tablename__ = "litigation_materials"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(String(50), unique=True, nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("litigation_intakes.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(30), nullable=False, index=True)
    mime_type = Column(String(120), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_path = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    analysis_status = Column(String(30), nullable=False, default="uploaded", index=True)
    confirm_status = Column(String(30), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    intake = relationship("LitigationIntake", back_populates="materials")
    case = relationship("LitigationCase", backref="source_materials")
    analysis_results = relationship("MaterialAnalysisResult", back_populates="material", cascade="all, delete-orphan")
    confirmation_blocks = relationship("MaterialConfirmationBlock", back_populates="material", cascade="all, delete-orphan")


class MaterialAnalysisResult(Base):
    __tablename__ = "material_analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(String(50), unique=True, nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("litigation_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name = Column(String(100), nullable=True)
    analysis_type = Column(String(50), nullable=False, index=True)
    raw_text = Column(Text, nullable=True)
    structured_result = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(30), nullable=False, default="success", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    material = relationship("LitigationMaterial", back_populates="analysis_results")


class MaterialConfirmationBlock(Base):
    __tablename__ = "material_confirmation_blocks"

    id = Column(Integer, primary_key=True, index=True)
    block_id = Column(String(50), unique=True, nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("litigation_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    block_type = Column(String(50), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    ai_result = Column(JSON, nullable=True)
    confirmed_result = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    material = relationship("LitigationMaterial", back_populates="confirmation_blocks")
    confirmer = relationship("User", backref="material_confirmations")


class CaseIntakeDraft(Base):
    __tablename__ = "case_intake_drafts"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(String(50), unique=True, nullable=False, index=True)
    intake_id = Column(Integer, ForeignKey("litigation_intakes.id", ondelete="CASCADE"), nullable=False, index=True)
    case_title = Column(String(200), nullable=True)
    plaintiff = Column(JSON, nullable=True)
    defendant = Column(JSON, nullable=True)
    case_summary = Column(Text, nullable=True)
    claims = Column(JSON, nullable=True)
    timeline = Column(JSON, nullable=True)
    evidence_catalog = Column(JSON, nullable=True)
    assessment = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False, default="draft", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    intake = relationship("LitigationIntake", back_populates="drafts")
