from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class AgentExecuteRequest(BaseModel):
    task_type: Literal["drafting", "review", "litigation"]
    action: str
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentExecuteResponse(BaseModel):
    status: str
    task_type: str
    action: str
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    task_id: Optional[str] = None
    deepagents: Optional[Dict[str, Any]] = None
