from pydantic import BaseModel
from typing import Optional, List


class AIAnalysisRequest(BaseModel):
    """AI分析请求"""
    contract_content: str


class AIAnalysisResponse(BaseModel):
    """AI分析响应"""
    success: bool
    analysis: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[dict] = None


class ClauseExtractionResponse(BaseModel):
    """条款提取响应"""
    success: bool
    clauses: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[dict] = None


class SummaryResponse(BaseModel):
    """摘要响应"""
    success: bool
    summary: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[dict] = None


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """AI对话请求"""
    contract_content: str
    question: str
    chat_history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    """AI对话响应"""
    success: bool
    answer: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[dict] = None
