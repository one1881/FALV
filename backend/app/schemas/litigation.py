from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .agent_result import AgentResultBase


class LitigationCaseCreate(BaseModel):
    case_title: Optional[str] = None
    customer_id: Optional[int] = None
    plaintiff: Dict[str, Any] = Field(default_factory=dict)
    defendant: Dict[str, Any] = Field(default_factory=dict)
    case_summary: Optional[str] = None
    claims: List[str] = Field(default_factory=list)
    evidence_files: List[Dict[str, Any]] = Field(default_factory=list)


class LitigationCaseResponse(BaseModel):
    id: int
    case_id: str
    case_title: Optional[str] = None
    customer_id: Optional[int] = None
    case_summary: Optional[str] = None
    claims: Optional[List[str]] = None
    status: str
    created_by: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StagePayloadSaveRequest(BaseModel):
    payload: Any = Field(default_factory=dict)
    status: str = "completed"


class LitigationAgentResult(AgentResultBase):
    case_id: str
    intake: Dict[str, Any]
    evidence: Dict[str, Any]
    cause: Dict[str, Any]
    jurisdiction: Dict[str, Any]
    pleading: Dict[str, Any]
    compliance: Dict[str, Any]
