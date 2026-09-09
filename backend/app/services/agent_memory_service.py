"""长期记忆服务（轻量版）：PG 为唯一可信源，文件为 Agent 挂载视图。

- 装配期：materialize_runtime_memory() 把 agent_memories 表渲染成
  backend/runtime/AGENT_MEMORY.md，随 build_memory_paths 挂进 Agent（可读）。
- 运行期：Agent 在沙箱里对该文件的修改，在每次任务结束后由
  sync_runtime_memory() 与 PG 比对，有变更即回写入库（可写）。
- 宪法类系统级规矩不进本表，保留在项目根 AGENTS.md（文件即宪法）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import Base, SessionLocal, engine
from app.models.agent_memory import AgentMemory

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
RUNTIME_MEMORY_PATH = BACKEND_ROOT / "runtime" / "AGENT_MEMORY.md"
_TABLE_READY = False


def _ensure_table() -> None:
    """幂等建表（服务启动首次调用时执行一次）。"""
    global _TABLE_READY
    if _TABLE_READY:
        return
    AgentMemory.__table__.create(bind=engine, checkfirst=True)
    _TABLE_READY = True


def _render_memory_markdown(rows: list[AgentMemory]) -> str:
    """把 PG 记忆行渲染成 Agent 可读的 markdown。"""
    lines = ["# Agent 运行期长期记忆（PG 同步）", ""]
    if not rows:
        lines.append("（当前无运行期沉淀。若发现值得长期记住的业务规则或用户偏好，"
                     "可在本文件末尾按「## [标题]」格式追加。）")
        return "\n".join(lines)

    for row in rows:
        updated = row.updated_at.strftime("%Y-%m-%d %H:%M") if row.updated_at else "-"
        lines.append(f"## [{row.title or row.mem_key}] scope={row.scope} 更新于 {updated}")
        lines.append("")
        lines.append(row.content.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def materialize_runtime_memory() -> Path | None:
    """PG → 文件：渲染长期记忆并写入挂载文件，返回文件路径（无内容也写骨架）。"""
    try:
        _ensure_table()
        db = SessionLocal()
        try:
            rows = db.query(AgentMemory).order_by(AgentMemory.updated_at.asc()).all()
        finally:
            db.close()
        RUNTIME_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_MEMORY_PATH.write_text(_render_memory_markdown(rows), encoding="utf-8")
        return RUNTIME_MEMORY_PATH
    except SQLAlchemyError as exc:
        # PG 不可用不应阻断 Agent 装配——返回已有文件或 None
        logger.warning("[agent-memory] 读取长期记忆失败: %s", exc)
        return RUNTIME_MEMORY_PATH if RUNTIME_MEMORY_PATH.exists() else None


def get_runtime_memory_path() -> Path | None:
    """供 build_memory_paths 调用：返回可挂载的长期记忆文件路径。"""
    return materialize_runtime_memory()


def sync_runtime_memory() -> bool:
    """文件 → PG：任务结束后调用。检测挂载文件是否被 Agent 修改，有变更即回写。

    以 (scope='runtime', mem_key='main', user_id IS NULL) 这一行作为运行期
    记忆的落点；文件内容与库不一致即整行更新。
    """
    if not RUNTIME_MEMORY_PATH.exists():
        return False
    try:
        content = RUNTIME_MEMORY_PATH.read_text(encoding="utf-8")
        if not content.strip():
            return False
        _ensure_table()
        db = SessionLocal()
        try:
            row = (
                db.query(AgentMemory)
                .filter(
                    AgentMemory.scope == "runtime",
                    AgentMemory.mem_key == "main",
                    AgentMemory.user_id.is_(None),
                )
                .first()
            )
            if row is None:
                db.add(AgentMemory(
                    scope="runtime", user_id=None, mem_key="main",
                    title="运行期沉淀", content=content,
                ))
                changed = True
            elif row.content != content:
                row.content = content
                row.updated_at = datetime.now()
                changed = True
            else:
                changed = False
            if changed:
                db.commit()
                logger.info("[agent-memory] 检测到长期记忆变更，已回写 PG")
        finally:
            db.close()
        return changed
    except SQLAlchemyError as exc:
        logger.warning("[agent-memory] 长期记忆回写失败: %s", exc)
        return False
