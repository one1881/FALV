"""主代理（A2A 主控）：协调起草、审核、诉讼三个业务模块。

架构（2026-09-07 A2A 改造）：
- 主代理在 :8000 进程内运行（deepagents 官方框架），通过 A2A 协议
  （Agent Card 发现 + JSON-RPC message/send）把起草/审核任务派发给
  独立子代理服务（drafting-agent :8001 / review-agent :8002）；
- A2A 服务不可达时自动回退：在主控进程内直接运行同一套子代理逻辑
  （agent_runtime.run_sub_agent_task），业务不中断；
- 子代理的结构化产物以 A2A 工具实际返回为准（主代理只做转发，
  避免 LLM 转述破坏 JSON 契约导致指标劣化）；
- 诉讼任务仍由主代理本体执行（无独立子代理）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent

logger = logging.getLogger(__name__)

from app.a2a.client import A2AClient, A2AError, A2AAgentExecutionError
from app.a2a_servers.agent_runtime import (
    DRAFTING_AGENT_URL,
    REVIEW_AGENT_URL,
    run_sub_agent_task,
)
from app.core.config import get_settings
from app.services.agent_core import (
    AgentCore,
    build_chat_model,
    build_root_chat_model,
    list_skill_documents,
    list_mcp_servers,
    list_mcp_tools,
    call_mcp_tool,
)

settings = get_settings()


@dataclass
class DeepAgentTask:
    task_id: str
    task_type: str
    action: str
    status: str = "pending"
    context: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    record_created: bool = False  # 审核记录是否已落库（异步任务完成后幂等落一次）
    review_record_id: Optional[int] = None
    timings: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DeepAgentsService(AgentCore):
    def __init__(self):
        self._tasks: Dict[str, DeepAgentTask] = {}
        self._background_tasks: set = set()  # 后台异步任务引用（防 GC）
        from app.core.checkpoint import build_checkpointer
        self._checkpointer = build_checkpointer()
        # A2A 派发所需：thread_id -> 当前请求 / 子代理产物
        self._active_requests: Dict[str, Dict[str, Any]] = {}
        self._a2a_results: Dict[str, Dict[str, Any]] = {}
        self._a2a_client = A2AClient()
        self._agent = self._build_agent()

    # ------------------------------------------------------------------
    # 主代理构建（子代理不再内嵌，改为 A2A 派发工具）
    # ------------------------------------------------------------------
    def _build_agent(self):
        return create_deep_agent(
            model=build_root_chat_model(),
            tools=self._build_root_tools(),
            system_prompt=(
                "你是法律合同系统的主代理（A2A 主控），负责协调起草、审核和诉讼三个业务模块。"
                "起草与审核子代理已独立部署为 A2A 服务（Agent Card 发现 + JSON-RPC message/send 通信）："
                "起草任务调用 dispatch_drafting_task 派发，审核任务调用 dispatch_review_task 派发。"
                "派发工具返回的 JSON 就是子代理的结构化交付物，必须原样、完整地作为最终回复输出，"
                "不得改写、增删或省略字段，不要附加任何解释。"
                "【起草/审核任务的执行纪律】这两个子代理已各自预加载专属技能说明，"
                "你只需直接调用对应派发工具，不要读取、列举或探索任何 skill 文件"
                "（不要用 ls / list_skill_documents / read_file 去看 /skills），以免浪费工具轮。"
                "诉讼任务由你本体执行，此时可按需读取技能、MCP 工具和文件上下文，输出要结构化、可回传。"
            ),
            skills=self.build_skill_documents(),
            memory=self.build_memory_paths(),
            permissions=self.build_permissions(),
            backend=self.build_backend(),
            checkpointer=self._checkpointer,
            interrupt_on={"write_file": True, "delete_file": True},
            name="legal_deepagents_root",
        )

    def _build_root_tools(self) -> list[Any]:
        return [
            list_skill_documents,
            list_mcp_servers,
            list_mcp_tools,
            call_mcp_tool,
            self._make_dispatch_tool(
                name="dispatch_drafting_task",
                description=(
                    "把合同起草任务派发给 A2A 子代理服务 drafting-agent。"
                    "返回子代理的结构化 JSON 交付物，必须原样作为最终回复输出。"
                ),
                agent_url=DRAFTING_AGENT_URL,
                kind="drafting",
            ),
            self._make_dispatch_tool(
                name="dispatch_review_task",
                description=(
                    "把合同审查任务派发给 A2A 子代理服务 review-agent。"
                    "返回子代理的结构化 JSON 交付物，必须原样作为最终回复输出。"
                ),
                agent_url=REVIEW_AGENT_URL,
                kind="review",
            ),
        ]

    def _make_dispatch_tool(self, name: str, description: str, agent_url: str, kind: str):
        """构造 A2A 派发工具。

        上下文不依赖 LLM 转抄：execute() 先把请求按 thread_id 暂存，
        工具执行时通过 ensure_config() 取当前 thread_id 取回完整请求，
        原样打包成 A2A message 发给子代理服务。
        """
        service = self

        async def _dispatch() -> str:
            thread_id = ""
            try:
                from langchain_core.runnables import ensure_config
                cfg = ensure_config() or {}
                thread_id = str((cfg.get("configurable") or {}).get("thread_id") or "")
            except Exception:
                thread_id = ""
            request = service._active_requests.get(thread_id)
            if request is None and service._active_requests:
                # 兜底：ensure_config 偶发取不到 thread_id 时，取最近暂存的请求，
                # 避免拿空上下文去派发（质量劣化且无报警）
                request = list(service._active_requests.values())[-1]
            if request is None:
                request = {"task_type": kind, "action": "draft" if kind == "drafting" else "review", "context": {}}

            payload = {
                "task_type": kind,
                "action": request.get("action", ""),
                "context": request.get("context", {}) or {},
            }
            started_at = time.perf_counter()
            # 1) A2A 标准链路：Agent Card 发现 → message/send → artifact
            try:
                result = await service._a2a_client.call_agent(
                    agent_url,
                    payload,
                    timeout_seconds=(
                        settings.A2A_DRAFTING_TIMEOUT_SECONDS
                        if kind == "drafting"
                        else settings.A2A_TIMEOUT_SECONDS
                    ),
                )
                transport = "a2a"
                elapsed = time.perf_counter() - started_at
                task = service._tasks.get(thread_id)
                if task is not None:
                    task.timings["a2a"] = round(elapsed, 3)
            except A2AAgentExecutionError as exc:
                # 子代理已真实执行并失败（多为模型/上游错误，如 Arrearage）——
                # 进程内重跑大概率同样失败，直接抛出，避免双倍耗时/费用
                raise
            except A2AError as exc:
                # 2) 回退：A2A 服务不可达（连不上/超时/协议错）时，进程内执行同一套子代理逻辑
                result = await run_sub_agent_task(kind, request, transport="in-process")
                result.setdefault("execution_trace", [])
                result["a2a_fallback_error"] = str(exc)
                transport = "in-process"
            except Exception as exc:  # 网络库等异常同样回退
                result = await run_sub_agent_task(kind, request, transport="in-process")
                result.setdefault("execution_trace", [])
                result["a2a_fallback_error"] = f"{type(exc).__name__}: {exc}"
                transport = "in-process"

            # 主控记录子代理产物：execute() 用它构建最终 task.result（不经 LLM 转手）
            if thread_id:
                service._a2a_results[thread_id] = result
            return json.dumps(result, ensure_ascii=False, default=str)

        async def _dispatch_tool() -> str:
            """派发任务给 A2A 子代理并原样返回其 JSON 交付物。"""
            return await _dispatch()

        # 用装饰器生成带名称/描述/签名说明的 LangChain tool
        from langchain_core.tools import tool as lc_tool

        _dispatch_tool.__name__ = name
        _dispatch_tool.__doc__ = description
        return lc_tool(_dispatch_tool)

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------
    def start_execute(self, task_key: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """异步启动任务：后台跑 execute，立即返回任务快照供前端轮询。

        审核等分钟级长任务如果让 HTTP 请求同步等到底，链路上任何一环
        （浏览器/开发代理/网关）都可能掐断连接报"请求超时"；改为提交后
        轮询，前端还能拿 events 展示进度。幂等：同 key 已在跑则直接返回快照。
        """
        existing = self._tasks.get(task_key)
        if existing is not None and existing.status == "running":
            return existing.to_dict()
        bg = asyncio.get_running_loop().create_task(self.execute(task_key, request))
        self._background_tasks.add(bg)
        bg.add_done_callback(self._background_tasks.discard)
        task = self._tasks.get(task_key)
        return task.to_dict() if task else {"task_id": task_key, "status": "running"}

    async def execute(self, task_key: str, request: Dict[str, Any]) -> Dict[str, Any]:
        task = self._tasks.get(task_key)
        if task is None:
            task = DeepAgentTask(
                task_id=task_key,
                task_type=request.get("task_type", ""),
                action=request.get("action", ""),
                context=dict(request.get("context", {})),
            )
            self._tasks[task_key] = task
        else:
            task.status = "running"
            task.context = dict(request.get("context", task.context))
            task.updated_at = datetime.now().isoformat()

        task.status = "running"
        task.events.append({
            "type": "event",
            "message": "任务已创建（主代理将经 A2A 派发子代理）",
            "level": "info",
            "timestamp": datetime.now().isoformat(),
        })

        # 暂存请求供 A2A 派发工具取回（thread_id == task_key）
        self._active_requests[task_key] = request
        self._a2a_results.pop(task_key, None)

        orchestrator_start = time.perf_counter()
        try:
            prompt = self._build_prompt(request, as_root=True)
            raw_result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"configurable": {"thread_id": task_key}},
            )
            orchestrator_elapsed = time.perf_counter() - orchestrator_start
            task.timings["orchestrator"] = round(orchestrator_elapsed, 3)
            # 子代理产物优先：A2A 工具实际返回的结构化结果不经 LLM 转手，
            # 直接作为 task.result（root 回复仅作为对话记录）。
            a2a_payload = self._a2a_results.pop(task_key, None)
            if a2a_payload is not None:
                structured = a2a_payload
            elif request.get("task_type") in ("drafting", "review"):
                # 主代理没走派发工具（LLM 自行作答或工具结果丢失）——
                # 强制在进程内走子代理逻辑，保证穷尽式审查/起草契约一定生效
                try:
                    structured = await run_sub_agent_task(
                        request["task_type"], request, transport="in-process"
                    )
                    structured.setdefault("execution_trace", []).insert(0, {
                        "step": "orchestrator",
                        "status": "warning",
                        "note": "主代理未调用 A2A 派发工具，已强制回退子代理链路",
                    })
                except Exception:
                    # 子代理链路也失败（如 LLM 报错）——按老逻辑加工 root 输出，让上层拿到一致结构
                    normalized = self._normalize_result(raw_result)
                    structured = self._build_structured_result(request, normalized)
            else:
                normalized = self._normalize_result(raw_result)
                structured = self._build_structured_result(request, normalized)
            task.status = "completed"
            task.result = structured
            task.timings["total"] = round(time.perf_counter() - orchestrator_start, 3)
            logger.info(
                "[deepagents] 任务完成 task=%s type=%s timings=%s",
                task_key, request.get("task_type"), task.timings
            )
            # 长期记忆回写：任务结束后检测运行期记忆文件是否被 Agent 修改（轻量版 PG 同步）
            try:
                from app.services.agent_memory_service import sync_runtime_memory
                sync_runtime_memory()
            except Exception as exc:  # noqa: BLE001 — 记忆回写失败不影响任务交付
                logger.warning("[deepagents] 长期记忆回写跳过: %s", exc)
            task.events.append({
                "type": "event",
                "message": "任务执行完成",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
                "agents": structured.get("agents_executed", []),
            })
            task.updated_at = datetime.now().isoformat()
            return task.to_dict()
        except Exception as exc:
            logger.exception("[deepagents] 任务执行失败 task=%s", task_key)
            task.status = "failed"
            task.error = str(exc)
            task.events.append({
                "type": "event",
                "message": "任务执行失败",
                "level": "error",
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
            })
            task.updated_at = datetime.now().isoformat()
            return task.to_dict()
        finally:
            self._active_requests.pop(task_key, None)
            self._a2a_results.pop(task_key, None)

    def get_task(self, task_key: str) -> Dict[str, Any] | None:
        task = self._tasks.get(task_key)
        return task.to_dict() if task else None

    # A2A 拓扑信息（供状态页/日志展示）
    def a2a_topology(self) -> Dict[str, Any]:
        cards = {}
        for url in (DRAFTING_AGENT_URL, REVIEW_AGENT_URL):
            try:
                cards[url] = self._a2a_client._card_cache.get(url)
            except Exception:
                cards[url] = None
        return {
            "enabled": bool(settings.A2A_ENABLED),
            "agents": {
                "drafting-agent": {"url": DRAFTING_AGENT_URL, "card": cards.get(DRAFTING_AGENT_URL)},
                "review-agent": {"url": REVIEW_AGENT_URL, "card": cards.get(REVIEW_AGENT_URL)},
            },
            "fallback": "in-process (agent_runtime.run_sub_agent_task)",
        }


_service: DeepAgentsService | None = None


def get_deepagents_service() -> DeepAgentsService:
    global _service
    if _service is None:
        _service = DeepAgentsService()
    return _service
