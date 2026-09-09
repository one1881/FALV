"""统一缓存层：Redis 可用则用 Redis，否则降级为进程内 dict 缓存。

用途：
- 缓存 LLM 结果（受理分析、材料摘要等），避免重复调用大模型产生费用和延迟
- 缓存热点查询结果（类案检索、企业查询等）

Redis 未安装/未启动时自动降级为进程内缓存，不影响功能，仅丢失跨进程共享能力。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import redis as _redis_lib
except ImportError:  # pragma: no cover
    _redis_lib = None


class CacheService:
    _instance: Optional["CacheService"] = None

    def __init__(self, host: str = "", port: int = 6379, db: int = 0, prefix: str = "zhq:"):
        self.prefix = prefix
        self._local: dict = {}
        self._redis = None
        if _redis_lib is not None:
            try:
                host = host or getattr(settings, "REDIS_HOST", "localhost")
                port = port or getattr(settings, "REDIS_PORT", 6379)
                password = getattr(settings, "REDIS_PASSWORD", "") or None
                db = db or getattr(settings, "REDIS_DB", 0)
                self._redis = _redis_lib.Redis(
                    host=host, port=port, db=db, password=password,
                    decode_responses=True, socket_connect_timeout=3,
                )
                self._redis.ping()
                logger.info("Redis 缓存已连接：%s:%s", host, port)
            except Exception as exc:  # pragma: no cover
                self._redis = None
                logger.warning("Redis 不可用，降级为进程内缓存：%s", exc)
        else:  # pragma: no cover
            logger.info("未安装 redis 包，降级为进程内缓存")

    @classmethod
    def instance(cls) -> "CacheService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, key: str) -> Optional[Any]:
        full = self.prefix + key
        if self._redis:
            try:
                val = self._redis.get(full)
                return json.loads(val) if val is not None else None
            except Exception:  # pragma: no cover
                pass
        return self._local.get(full)

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        full = self.prefix + key
        if self._redis:
            try:
                self._redis.setex(full, ttl, json.dumps(value, ensure_ascii=False))
                return
            except Exception:  # pragma: no cover
                pass
        self._local[full] = value

    def enabled(self) -> bool:
        return self._redis is not None


def get_cache() -> CacheService:
    return CacheService.instance()
