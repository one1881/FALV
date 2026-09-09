from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IntakeCreateRequest(BaseModel):
    source: Optional[str] = None
    case_type: Optional[str] = None
    customer_name: Optional[str] = None
    opposite_party: Optional[str] = None


class MaterialCreateRequest(BaseModel):
    file_name: str
    file_type: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    analysis_text: Optional[str] = None
    proof_purpose: Optional[str] = None


class MaterialBatchCreateRequest(BaseModel):
    materials: List[MaterialCreateRequest] = Field(default_factory=list)


class ConfirmationUpdateRequest(BaseModel):
    block_id: str
    confirmed_result: Any = None
    status: str = "confirmed"


class CaseDraftUpdateRequest(BaseModel):
    case_title: Optional[str] = None
    plaintiff: Dict[str, Any] = Field(default_factory=dict)
    defendant: Dict[str, Any] = Field(default_factory=dict)
    case_summary: Optional[str] = None
    claims: List[str] = Field(default_factory=list)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_catalog: List[Dict[str, Any]] = Field(default_factory=list)
    assessment: Dict[str, Any] = Field(default_factory=dict)


class IntakeResponse(BaseModel):
    id: int
    intake_id: str
    status: str
    source: Optional[str] = None
    case_type: Optional[str] = None
    customer_name: Optional[str] = None
    opposite_party: Optional[str] = None


class IntakeDetailResponse(BaseModel):
    intake: Dict[str, Any]
    materials: List[Dict[str, Any]]
    confirmation_blocks: List[Dict[str, Any]]
    draft: Optional[Dict[str, Any]] = None
