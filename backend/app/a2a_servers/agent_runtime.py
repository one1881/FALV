"""A2A 子代理运行时：独立 A2A 服务与主控进程内回退共用同一套执行逻辑。

- run_sub_agent_task("drafting"|"review", request, transport)：
  构建 prompt（沿用 OUTPUT_CONTRACTS 契约）→ 独立 deep agent 执行 →
  结果归一化 → 结构化加工 → 补写真实执行轨迹（A2A 传输信息）。
- DRAFTING_CARD / REVIEW_CARD：两个子代理服务的 Agent Card。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict

from app.a2a.protocol import AgentCard
from app.core.config import get_settings
from app.services.agent_core import DRAFTING_SPEC, REVIEW_SPEC, AgentCore

logger = logging.getLogger(__name__)

settings = get_settings()

DRAFTING_AGENT_PORT = settings.DRAFTING_AGENT_PORT
REVIEW_AGENT_PORT = settings.REVIEW_AGENT_PORT
DRAFTING_AGENT_URL = f"http://127.0.0.1:{DRAFTING_AGENT_PORT}"
REVIEW_AGENT_URL = f"http://127.0.0.1:{REVIEW_AGENT_PORT}"

SPECS = {"drafting": DRAFTING_SPEC, "review": REVIEW_SPEC}

DRAFTING_CARD = AgentCard(
    name="drafting-agent",
    description="合同起草子代理：模板匹配、正文起草、相似检索、质量检查与风险评估。",
    url=f"{DRAFTING_AGENT_URL}/",
    skills=[{
        "id": "contract_drafting",
        "name": "合同起草",
        "description": "根据当事人、类型与业务要求起草完整合同正文，附摘要与质量检查。",
        "tags": ["drafting", "contract", "legal"],
    }],
)

REVIEW_CARD = AgentCard(
    name="review-agent",
    description="合同审查子代理：穷尽式逐条款扫描，识别法律风险、逻辑问题与合规问题并生成审查报告。",
    url=f"{REVIEW_AGENT_URL}/",
    skills=[{
        "id": "contract_review",
        "name": "合同审查",
        "description": "金额一致性/日期逻辑/法条引用/违约金/管辖/缺失条款等八项清单式审查。",
        "tags": ["review", "risk", "legal"],
    }],
)

_core = AgentCore()
_agents: Dict[str, Any] = {}


def _get_agent(kind: str):
    if kind not in _agents:
        _agents[kind] = _core.build_sub_agent(SPECS[kind])
    return _agents[kind]


def parse_agent_request(message_text: str, kind: str) -> Dict[str, Any]:
    """把 A2A message text 解析成统一 request；兼容纯文本需求描述。"""
    import json
    request: Dict[str, Any]
    text = (message_text or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                request = {
                    "task_type": data.get("task_type") or kind,
                    "action": data.get("action") or ("draft" if kind == "drafting" else "review"),
                    "context": data.get("context") or {},
                }
                return request
        except Exception:
            pass
    # 纯文本：当作需求描述
    action = "draft" if kind == "drafting" else "review"
    return {"task_type": kind, "action": action, "context": {"requirements": text}}


# 交付兜底指令：附加在**完整原始任务**之后用于重生成。
# 2026-09-10 改造：重生成改为新开线程，故措辞不能出现"你上一条回复"（新线程无上一条）。
_FINAL_NUDGE = (
    "\n\n【强制交付】请直接输出完整的最终 JSON 交付物（严格按上文约定的 JSON 契约），"
    "不要输出计划、解释、过渡句、进度汇报或 markdown 围栏；"
    "禁止以「我将…」「我已…」这类说明开头，一步到位给出全量内容。"
)

# 起草结果必须一次生成完成；重复完整生成会把单次耗时和费用翻倍。
# 审核保留一次重生成，用于处理模型偶发的非结构化输出。
_DRAFTING_MAX_DELIVERABLE_ATTEMPTS = 1
_DEFAULT_MAX_DELIVERABLE_ATTEMPTS = 2


def _looks_deliverable(text: str) -> bool:
    """判断最终回复是否像交付物：要么是 JSON 信封，要么是足够长的成文内容。

    glm 系模型偶发'只说不做'——输出'让我先整理上下文'这类计划文字就结束回合，
    需要识别出来追问续跑，否则下游会把计划文字/兜底模板当成正文存库。
    """
    if not text:
        return False
    if '"content"' in text or text.strip().startswith("{"):
        return True
    return len(text.strip()) > 500  # 纯文本交付至少是成文长度的内容


async def run_sub_agent_task(kind: str, request: Dict[str, Any], transport: str = "a2a-server") -> Dict[str, Any]:
    """执行一个子代理任务，返回结构化结果（含真实 A2A 执行轨迹）。

    transport:
      a2a-server  —— 本函数在 A2A 子代理服务进程内执行（正常链路）
      in-process  —— 主控进程内回退执行（A2A 服务不可达时）
    """
    spec = SPECS[kind]
    request = dict(request)
    request.setdefault("task_type", kind)
    request.setdefault("action", "draft" if kind == "drafting" else "review")

    agent = _get_agent(kind)
    prompt = _core._build_prompt(request, as_root=False)
    thread_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    raw_result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
    )

    # 交付物校验 + 兜底重生成。
    # 2026-09-10 改造：原实现为「同一线程追加追问」，实测上下文雪球严重 ——
    # 单轮耗时随追问次数单调递增（3'12" → 2'42" → 4'19" → 9'44"，末轮几乎顶到
    # 600s 超时线），把一次 3 分钟的任务拖成 20 分钟。现改为：不合格时**新开线程 +
    # 完整原始任务**重生成，让每一轮都跑在干净上下文里；并设硬上限
    # _MAX_DELIVERABLE_ATTEMPTS 次，超限即如实返回，不再无限续跑空烧算力。
    attempts = 0
    max_attempts = (
        _DRAFTING_MAX_DELIVERABLE_ATTEMPTS
        if kind == "drafting"
        else _DEFAULT_MAX_DELIVERABLE_ATTEMPTS
    )
    for attempt in range(max_attempts):
        attempts = attempt + 1
        state = raw_result.model_dump() if hasattr(raw_result, "model_dump") else raw_result
        messages = state.get("messages") if isinstance(state, dict) else None
        final_text = AgentCore._extract_final_text(messages)
        if _looks_deliverable(final_text):
            break
        if attempts >= max_attempts:
            logger.error(
                "[agent_runtime] %s 子代理连续 %d 次输出非交付物（%s...），已达上限，放弃重试并如实返回",
                kind, attempts, final_text[:60],
            )
            break
        logger.warning(
            "[agent_runtime] %s 子代理输出非交付物（%s...），新线程重生成（放弃同线程追问，避免上下文雪球）",
            kind, final_text[:60],
        )
        thread_id = f"{kind}-{uuid.uuid4().hex[:12]}"
        config = {"configurable": {"thread_id": thread_id}}
        raw_result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt + _FINAL_NUDGE}]},
            config=config,
        )

    normalized = _core._normalize_result(raw_result)
    structured = _core._build_structured_result(request, normalized)

    # 长期记忆回写：子代理任务结束后检测运行期记忆文件变更（轻量版 PG 同步）
    try:
        from app.services.agent_memory_service import sync_runtime_memory
        sync_runtime_memory()
    except Exception:  # noqa: BLE001 — 记忆回写失败不影响任务交付
        pass

    action = request.get("action", "")
    if transport == "a2a-server":
        structured["execution_trace"] = [
            {"step": f"{kind}-agent(A2A server :{DRAFTING_AGENT_PORT if kind == 'drafting' else REVIEW_AGENT_PORT})",
             "status": "success", "action": action},
        ]
        structured["agents_executed"] = [spec["name"], "a2a-protocol:0.3.0"]
    else:  # in-process fallback
        structured["execution_trace"] = [
            {"step": "deepagents_root", "status": "success",
             "note": "A2A 子代理服务不可达，已回退进程内执行"},
            {"step": f"{kind}-agent", "status": "success", "action": action, "transport": "in-process"},
        ]
        structured["agents_executed"] = ["DeepAgentsService", f"{kind}-agent(in-process-fallback)"]
    structured["a2a_transport"] = transport
    structured["a2a_task_id"] = thread_id
    structured["a2a_attempts"] = attempts  # >1 表示发生过兜底重生成，可供返工率观测
    structured["a2a_completed_at"] = datetime.now().isoformat()
    return structured
