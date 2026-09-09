"""Create the workflow, report, and archive tables in the configured PostgreSQL database."""

import sys

sys.path.insert(0, ".")

from app.core.database import Base, engine
from app.models import (  # noqa: F401
    ApprovalStep,
    ApprovalWorkflow,
    CaseIntakeDraft,
    CaseParty,
    CauseOpinion,
    Contract,
    ContractArchiveRecord,
    ContractWorkflowRun,
    Customer,
    Document,
    DocumentTemplate,
    EvidenceExtract,
    EvidenceItem,
    FactEvidenceLink,
    FactIssue,
    JurisdictionOpinion,
    LitigationCase,
    LitigationIntake,
    LitigationMaterial,
    LitigationWorkflowResult,
    MaterialAnalysisResult,
    MaterialConfirmationBlock,
    ReviewRecord,
    User,
    WorkflowReport,
)


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Database tables are ready.")
