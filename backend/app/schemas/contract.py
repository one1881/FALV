from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal


class ContractBase(BaseModel):
    title: str
    contract_type: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: str = "CNY"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    signing_date: Optional[datetime] = None
    content: Optional[str] = None


class ContractCreate(ContractBase):
    pass


class ContractUpdate(BaseModel):
    title: Optional[str] = None
    contract_type: Optional[str] = None
    status: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    signing_date: Optional[datetime] = None
    content: Optional[str] = None
    file_path: Optional[str] = None


class ContractResponse(ContractBase):
    id: int
    contract_number: str
    status: str
    file_path: Optional[str] = None
    created_by: int
    created_by_name: Optional[str] = None
    owner_lawyer_id: Optional[int] = None
    owner_lawyer_name: Optional[str] = None
    status_label: Optional[str] = None
    is_completed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContractListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ContractResponse]


class ContractGenerateRequest(BaseModel):
    """合同生成请求"""
    contract_type: str  # 合同类型
    customer_name: Optional[str] = None  # 客户名称
    party_id: Optional[int] = None  # 客户ID
    amount: Optional[Decimal] = None  # 合同金额
    jurisdiction: Optional[str] = None  # 法律管辖区
    industry: Optional[str] = None  # 行业
    description: Optional[str] = None  # 合同描述
    requirements: Optional[str] = None  # 特殊要求
    materials_text: Optional[str] = None  # 用户上传资料中可读取的文本
    materials: Optional[List[Dict[str, Any]]] = None  # 上传资料元数据


class ContractSubmitApprovalRequest(BaseModel):
    """用户确认合同摘要后提交审批。"""
    summary: Optional[str] = None
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None


class ContractGenerateResponse(BaseModel):
    """合同生成响应"""
    contract_id: int  # 合同ID
    contract_number: str  # 合同编号
    content: str  # 合同内容(纯文本)
    html_content: str  # 合同内容(HTML格式)
    status: str  # 合同状态
    risk_score: Optional[float] = None  # 风险分数
    risk_level: Optional[str] = None  # 风险等级
    similar_contracts: Optional[int] = None  # 相似合同数量
    compliance_pass: Optional[bool] = None  # 合规检查是否通过
    # 明细（供前端结果页详情弹窗展示）
    risk_dimensions: Optional[Dict[str, Any]] = None  # 4维度风险明细
    similar_contract_list: Optional[List[Dict[str, Any]]] = None  # 相似合同列表
    compliance_issues: Optional[List[Dict[str, Any]]] = None  # 合规问题列表
    compliance_summary: Optional[Dict[str, Any]] = None  # 合规检查摘要
    contract_summary: Optional[Dict[str, Any]] = None  # 用户确认用摘要
    data_collection: Optional[Dict[str, Any]] = None
    regulation_matches: Optional[Dict[str, Any]] = None
    main_model_compliance: Optional[Dict[str, Any]] = None
    template_selection: Optional[Dict[str, Any]] = None
    workflow_stages: Optional[List[Dict[str, Any]]] = None
    workflow_id: Optional[str] = None  # 审批工作流 ID
    approval_workflow: Optional[Dict[str, Any]] = None  # 审批工作流完整结构(节点/审批人/deadline)
