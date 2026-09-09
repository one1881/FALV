"""
EnterpriseData MCP Server - 企业数据/合同元数据查询
MCP 工具:
- get_customer:             按客户名查工商信息
- list_customers:           列出/模糊查询客户
- get_contract_metadata:    按 ID 查合同基本元数据
- get_cache_age:            数据缓存年龄(供 agent 判断新鲜度)
"""
from __future__ import annotations
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timezone

from sqlalchemy import or_

from app.mcps.base_server import BaseMCPServer
from app.core.database import SessionLocal
from app.models.customer import Customer
from app.models.contract import Contract

logger = logging.getLogger(__name__)


def _customer_to_dict(c: Customer) -> Dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "code": c.code,
        "contact_person": c.contact_person,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "legal_representative": c.legal_representative,
        "unified_social_credit_code": c.unified_social_credit_code,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _contract_to_meta(c: Contract) -> Dict[str, Any]:
    return {
        "contract_id": c.id,
        "contract_number": c.contract_number,
        "title": c.title,
        "contract_type": c.contract_type.value if hasattr(c.contract_type, "value") else c.contract_type,
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "amount": float(c.amount) if c.amount is not None else 0.0,
        "party_a_name": getattr(c, "party_a_name", None),
        "party_b_name": getattr(c, "party_b_name", None),
        "risk_score": getattr(c, "risk_score", None),
        "risk_level": getattr(c, "risk_level", None),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


class EnterpriseDataServer(BaseMCPServer):
    """企业数据 MCP server"""

    def __init__(self):
        super().__init__(name="enterprise_data_server", description="客户/合同/工商信息数据库查询")

        self.register_tool(
            name="get_customer",
            description="按客户名/编号精确或模糊查询客户工商信息;返回统一信用代码、法人、联系方式、地址等",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "客户名,精确或模糊匹配"},
                },
                "required": ["name"],
            },
            handler=self._get_customer,
        )
        self.register_tool(
            name="list_customers",
            description="列出所有客户(可按关键词模糊过滤,limit 控制返回数量)",
            input_schema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": [],
            },
            handler=self._list_customers,
        )
        self.register_tool(
            name="get_contract_metadata",
            description="按合同 ID 获取合同元数据(类型/金额/状态/风险分数等)",
            input_schema={
                "type": "object",
                "properties": {"contract_id": {"type": "integer"}},
                "required": ["contract_id"],
            },
            handler=self._get_contract_metadata,
        )
        self.register_tool(
            name="get_credit_score",
            description="根据客户基础资料计算可解释的信用评分及风险原因",
            input_schema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "customer_name": {"type": "string"},
                },
                "required": [],
            },
            handler=self._get_credit_score,
        )
        self.register_tool(
            name="get_cache_age",
            description="返回 MCP 客户端请求的企业数据缓存年龄(秒);agent 据此判断是否需要刷新",
            input_schema={
                "type": "object",
                "properties": {"resource_key": {"type": "string"}},
                "required": ["resource_key"],
            },
            handler=self._get_cache_age,
        )

    async def _get_customer(self, name: str) -> Dict[str, Any]:
        if not name:
            return {"ok": False, "error": "name is required", "customers": []}
        db = SessionLocal()
        try:
            q = db.query(Customer).filter(or_(
                Customer.name == name,
                Customer.name.ilike(f"%{name}%"),
                Customer.code == name,
            )).limit(10).all()
            customers = [_customer_to_dict(c) for c in q]
            return {"ok": True, "count": len(customers), "customers": customers}
        except Exception as e:
            logger.exception("get_customer failed")
            return {"ok": False, "error": str(e), "customers": []}
        finally:
            db.close()

    async def _list_customers(self, keyword: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            q = db.query(Customer)
            if keyword:
                q = q.filter(or_(Customer.name.ilike(f"%{keyword}%"), Customer.code.ilike(f"%{keyword}%")))
            rows = q.limit(min(limit, 100)).all()
            customers = [_customer_to_dict(c) for c in rows]
            return {"ok": True, "count": len(customers), "customers": customers}
        except Exception as e:
            logger.exception("list_customers failed")
            return {"ok": False, "error": str(e), "customers": []}
        finally:
            db.close()

    async def _get_contract_metadata(self, contract_id: int) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            c = db.query(Contract).filter(Contract.id == contract_id).first()
            if not c:
                return {"ok": False, "error": f"contract {contract_id} not found", "metadata": None}
            return {"ok": True, "metadata": _contract_to_meta(c)}
        except Exception as e:
            logger.exception("get_contract_metadata failed")
            return {"ok": False, "error": str(e), "metadata": None}
        finally:
            db.close()

    async def _get_credit_score(
        self,
        customer_id: Optional[int] = None,
        customer_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if customer_id is None and not customer_name:
            return {"ok": False, "error": "customer_id or customer_name is required"}

        db = SessionLocal()
        try:
            query = db.query(Customer)
            if customer_id is not None:
                customer = query.filter(Customer.id == customer_id).first()
            else:
                customer = query.filter(
                    or_(
                        Customer.name == customer_name,
                        Customer.name.ilike(f"%{customer_name}%"),
                        Customer.code == customer_name,
                    )
                ).first()

            if not customer:
                return {
                    "ok": True,
                    "score": 50,
                    "level": "medium",
                    "customer": None,
                    "factors": ["未找到客户档案，使用保守默认评分"],
                    "source": "rule_based",
                }

            fields = (
                customer.code,
                customer.contact_person,
                customer.phone,
                customer.email,
                customer.address,
                customer.legal_representative,
                customer.unified_social_credit_code,
            )
            completeness = sum(bool(value) for value in fields)
            score = min(95, 45 + completeness * 7)
            level = "low" if score >= 75 else "medium" if score >= 55 else "high"
            return {
                "ok": True,
                "score": score,
                "level": level,
                "customer": _customer_to_dict(customer),
                "factors": [f"客户档案完整度 {completeness}/{len(fields)}"],
                "source": "rule_based",
            }
        except Exception as e:
            logger.exception("get_credit_score failed")
            return {"ok": False, "error": str(e)}
        finally:
            db.close()

    async def _get_cache_age(self, resource_key: str) -> Dict[str, Any]:
        # 进程内无跨调用缓存(直读数据库,视为实时),返回 0
        return {
            "ok": True,
            "resource_key": resource_key,
            "age_seconds": 0,
            "source": "direct_db",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
