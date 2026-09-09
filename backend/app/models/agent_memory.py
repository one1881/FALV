"""Agent 长期记忆表（轻量版）。

PG 为长期记忆的唯一可信源：装配时物化成 markdown 文件挂进 Agent（可读），
Agent 运行结束后检测文件变更回写 PG（可写）。宪法类系统级规矩保留在
项目根 AGENTS.md（文件即宪法，不重复入库）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # system=系统级规矩 | runtime=运行期沉淀 | user=用户级个性化（预留）
    scope = Column(String(32), nullable=False, default="runtime", index=True)
    user_id = Column(Integer, nullable=True, index=True)  # NULL=全体共享
    mem_key = Column(String(128), nullable=False, default="main")  # 同 scope 内唯一
    title = Column(String(255), nullable=False, default="")  # 记忆条目标题
    content = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
