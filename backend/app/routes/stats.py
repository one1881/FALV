from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.stats_service import StatsService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["统计"])


@router.get("/dashboard")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取 Dashboard 统计数据"""
    try:
        service = StatsService(db)
        return service.get_dashboard_stats()
    except Exception as e:
        logger.exception(f"Get dashboard stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="获取统计数据失败"
        )
