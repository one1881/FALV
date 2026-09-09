from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.review import ReviewRecord


class ReviewService:
    def __init__(self, db: Session):
        self.db = db

    def generate_review_id(self) -> str:
        prefix = datetime.now().strftime("REV-%Y%m%d-")
        last = (
            self.db.query(ReviewRecord)
            .filter(ReviewRecord.review_public_id.like(f"{prefix}%"))
            .order_by(ReviewRecord.review_public_id.desc())
            .first()
        )
        next_number = int(last.review_public_id[-4:]) + 1 if last else 1
        return f"{prefix}{next_number:04d}"

    def create_review_record(
        self,
        reviewer_id: Optional[int],
        result: Dict[str, Any],
        contract_id: Optional[int] = None,
        document_type: Optional[str] = None,
    ) -> ReviewRecord:
        dimensions = dict(result.get("dimensions", {}) or {})
        dimensions["_parsed_document"] = result.get("parsed_document", {})
        dimensions["_trace"] = {
            "agents_executed": result.get("agents_executed", []),
            "skills_used": result.get("skills_used", []),
            "mcp_tools_used": result.get("mcp_tools_used", []),
            "execution_trace": result.get("execution_trace", []),
            "warnings": result.get("warnings", []),
        }
        record = ReviewRecord(
            review_public_id=self.generate_review_id(),
            contract_id=contract_id,
            document_type=document_type,
            review_status=result.get("review_status", "warning"),
            overall_score=result.get("overall_score"),
            legal_compliance_score=dimensions.get("legal_compliance", {}).get("score"),
            logic_consistency_score=dimensions.get("logic_consistency", {}).get("score"),
            risk_score=dimensions.get("risk_assessment", {}).get("score"),
            dimensions=dimensions,
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            reviewer_id=reviewer_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_records(
        self,
        limit: int = 50,
        contract_id: Optional[int] = None,
    ) -> List[ReviewRecord]:
        query = self.db.query(ReviewRecord)
        if contract_id is not None:
            query = query.filter(ReviewRecord.contract_id == contract_id)
        return query.order_by(ReviewRecord.reviewed_at.desc()).limit(limit).all()

    @staticmethod
    def to_dict(item: ReviewRecord) -> Dict[str, Any]:
        status_labels = {
            "pending": "待审核",
            "reviewing": "审核中",
            "processing": "审核中",
            "completed": "已完成",
            "warning": "需修改",
            "needs_revision": "需修改",
            "pass": "已通过",
            "approved": "已通过",
        }
        reviewer_name = item.reviewer.full_name if item.reviewer else None
        submitted_by = item.contract.created_by if item.contract else item.reviewer_id
        submitted_by_name = item.contract.created_by_name if item.contract else reviewer_name
        is_completed = item.review_status in {"completed", "pass", "approved", "warning", "needs_revision"}
        return {
            "id": item.id,
            "review_id": item.review_public_id,
            "contract_id": item.contract_id,
            "document_type": item.document_type,
            "review_status": item.review_status,
            "review_status_label": status_labels.get(item.review_status, item.review_status or "待审核"),
            "is_completed": is_completed,
            "submitted_by": submitted_by,
            "submitted_by_name": submitted_by_name,
            "reviewer_id": item.reviewer_id,
            "reviewer_name": reviewer_name,
            "overall_score": item.overall_score,
            "legal_compliance_score": item.legal_compliance_score,
            "logic_consistency_score": item.logic_consistency_score,
            "risk_score": item.risk_score,
            "dimensions": item.dimensions,
            "issues": item.issues,
            "suggestions": item.suggestions,
            "parsed_document": (item.dimensions or {}).get("_parsed_document", {}),
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "agents_executed": (item.dimensions or {}).get("_trace", {}).get("agents_executed", []),
            "skills_used": (item.dimensions or {}).get("_trace", {}).get("skills_used", []),
            "mcp_tools_used": (item.dimensions or {}).get("_trace", {}).get("mcp_tools_used", []),
            "execution_trace": (item.dimensions or {}).get("_trace", {}).get("execution_trace", []),
        }
