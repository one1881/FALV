from pydantic import BaseModel


class AgentResultBase(BaseModel):
    status: str
