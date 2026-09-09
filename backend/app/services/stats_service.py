"""统计数据服务 - Dashboard 统计"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Any, Dict, List
from app.models.contract import Contract
from app.models.customer import Customer


class StatsService:
    """统计服务"""

    def __init__(self, db: Session):
        self.db = db

    def _month_range(self, offset_months: int):
        """返回 offset_months 个月前所在月的 [起, 止) 区间"""
        now = datetime.now()
        first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # 目标月的第一天
        y, m = first_this_month.year, first_this_month.month
        m += offset_months
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        target_first = first_this_month.replace(year=y, month=m)
        if offset_months < 0:
            # 目标月下个月的第一天
            ny, nm = y, m + 1
            if nm > 12:
                nm = 1
                ny += 1
            target_end = first_this_month.replace(year=ny, month=nm)
            return target_first, target_end
        return target_first, first_this_month

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """获取 Dashboard 统计数据"""
        now = datetime.now()
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start, last_month_end = self._month_range(-1)

        # ---- 合同统计 ----
        total_contracts = self.db.query(func.count(Contract.id)).scalar() or 0
        this_month = (
            self.db.query(func.count(Contract.id))
            .filter(Contract.created_at >= this_month_start)
            .scalar() or 0
        )
        last_month = (
            self.db.query(func.count(Contract.id))
            .filter(Contract.created_at >= last_month_start, Contract.created_at < last_month_end)
            .scalar() or 0
        )
        growth_rate = 0.0
        if last_month > 0:
            growth_rate = round((this_month - last_month) / last_month * 100, 1)

        by_status: Dict[str, int] = {}
        status_rows = (
            self.db.query(Contract.status, func.count(Contract.id))
            .group_by(Contract.status)
            .all()
        )
        for status, cnt in status_rows:
            by_status[status] = cnt

        this_month_amount = (
            self.db.query(func.coalesce(func.sum(Contract.amount), 0))
            .filter(Contract.created_at >= this_month_start)
            .scalar() or 0
        )

        # ---- 审批统计（用合同 status 近似，无独立审批表） ----
        pending = (
            self.db.query(func.count(Contract.id))
            .filter(Contract.status == "pending")
            .scalar() or 0
        )
        approved_this_month = (
            self.db.query(func.count(Contract.id))
            .filter(Contract.status == "approved", Contract.created_at >= this_month_start)
            .scalar() or 0
        )
        rejected_this_month = (
            self.db.query(func.count(Contract.id))
            .filter(Contract.status == "rejected", Contract.created_at >= this_month_start)
            .scalar() or 0
        )

        # ---- 客户统计 ----
        total_customers = self.db.query(func.count(Customer.id)).scalar() or 0
        new_customers = (
            self.db.query(func.count(Customer.id))
            .filter(Customer.created_at >= this_month_start)
            .scalar() or 0
        )

        # ---- 最近合同 ----
        recent_contracts: List[Dict[str, Any]] = []
        recent_rows = (
            self.db.query(Contract)
            .order_by(Contract.created_at.desc())
            .limit(5)
            .all()
        )
        for c in recent_rows:
            recent_contracts.append({
                "id": c.id,
                "contract_number": c.contract_number,
                "title": c.title,
                "contract_type": c.contract_type,
                "status": c.status,
                "customer_name": c.customer_name,
                "amount": float(c.amount) if c.amount else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

        # ---- 待办 ----
        pending_items = {
            "drafts": (
                self.db.query(func.count(Contract.id))
                .filter(Contract.status == "draft")
                .scalar() or 0
            ),
            "pending_approvals": pending,
            "reviewing_contracts": (
                self.db.query(func.count(Contract.id))
                .filter(Contract.status == "pending")
                .scalar() or 0
            ),
        }

        return {
            "contracts": {
                "total": total_contracts,
                "this_month": this_month,
                "last_month": last_month,
                "growth_rate": growth_rate,
                "by_status": by_status,
                "this_month_amount": float(this_month_amount),
            },
            "approvals": {
                "pending": pending,
                "approved_this_month": approved_this_month,
                "rejected_this_month": rejected_this_month,
                "overdue": 0,
            },
            "customers": {
                "total": total_customers,
                "new_this_month": new_customers,
                "risky_customers": 0,
            },
            "recent_contracts": recent_contracts,
            "pending_items": pending_items,
            "generated_at": now.isoformat(),
        }
