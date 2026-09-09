from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest, RefreshResponse
from app.services.auth_service import AuthService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    try:
        logger.info(f"Login attempt for user: {request.username}")

        auth_service = AuthService(db)
        result = auth_service.login(request.username, request.password)

        if not result:
            logger.warning(f"Login failed for user: {request.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info(f"Login successful for user: {request.username}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录失败，请稍后重试"
        )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest, db: Session = Depends(get_db)):
    """刷新访问令牌"""
    try:
        auth_service = AuthService(db)
        result = auth_service.refresh_access_token(request.refresh_token)

        if not result:
            logger.warning("Refresh token invalid or expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="刷新令牌无效或已过期",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info("Token refreshed successfully")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Refresh token error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="令牌刷新失败，请重新登录"
        )


@router.get("/me")
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user.to_dict()


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """用户登出"""
    return {"status": "success", "message": f"用户 {current_user.username} 已登出"}
