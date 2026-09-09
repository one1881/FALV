from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from typing import Optional


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """验证用户凭据"""
        user = self.db.query(User).filter(User.username == username).first()
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def login(self, username: str, password: str) -> Optional[dict]:
        """用户登录"""
        user = self.authenticate_user(username, password)
        if not user:
            return None

        access_token = create_access_token(data={"sub": user.username, "user_id": user.id})
        refresh_token = create_refresh_token(data={"sub": user.username, "user_id": user.id})

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user.to_dict()
        }

    def refresh_access_token(self, refresh_token: str) -> Optional[dict]:
        """刷新访问令牌"""
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None

        username = payload.get("sub")
        user_id = payload.get("user_id")
        if not username or not user_id:
            return None

        access_token = create_access_token(data={"sub": username, "user_id": user_id})

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
