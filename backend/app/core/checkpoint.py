"""Agent 检查点（短期记忆）后端统一入口。

优先使用 Redis 检查点（持久化、多实例共享），Redis 不可用时自动回退进程内
MemorySaver——保证单机开发环境零依赖也能跑。Redis 连接读取 settings 的
REDIS_HOST / REDIS_PORT / REDIS_PASSWORD / REDIS_DB。

注意：业务链路全部走 `ainvoke`（异步），因此返回 AsyncRedisSaver；
索引结构由同步端 setup() 幂等创建（已存在则跳过），异步端直接复用。
"""
from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHED_CHECKPOINTER = None  # 进程级单例：主代理与子代理共用同一个后端


def build_checkpointer():
    """构建检查点后端（进程级单例）：Redis 可用用 AsyncRedisSaver，否则回退 MemorySaver。"""
    global _CACHED_CHECKPOINTER
    if _CACHED_CHECKPOINTER is not None:
        return _CACHED_CHECKPOINTER

    try:
        from langgraph.checkpoint.redis import RedisSaver
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        auth = f":{settings.REDIS_PASSWORD}@" if settings.REDIS_PASSWORD else ""
        redis_url = f"redis://{auth}{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
        # 同步端先建索引（幂等），异步端复用同一套索引结构
        sync_saver = RedisSaver(redis_url=redis_url)
        sync_saver.setup()
        saver = AsyncRedisSaver(redis_url=redis_url)  # ainvoke 走 aget_tuple，必须用异步实现
        _CACHED_CHECKPOINTER = saver
        logger.info("[checkpoint] 使用 Redis 检查点后端(async): %s", redis_url)
    except Exception as exc:  # noqa: BLE001 — Redis 未启动/包缺失等一律降级
        logger.warning("[checkpoint] Redis 不可用(%s)，回退进程内 MemorySaver", exc)
        _CACHED_CHECKPOINTER = MemorySaver()
    return _CACHED_CHECKPOINTER
