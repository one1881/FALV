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
    ensure_mcp_servers_registered,
    list_skill_documents,
    list_mcp_servers,
    list_mcp_tools,
    call_mcp_tool,
)

settings = get_settings()

# 进程内回退前要求的最小剩余预算（秒）：低于此值就不再重跑——
# A2A 超时并不意味着 :8001 已停止，它很可能还在跑；此时盲目回退会把同一份
# 起草跑两遍，耗时与费用直接翻倍（2026-09-11 实测"一次任务 4 个 drafting 线程"的主因）。
_MIN_FALLBACK_BUDGET_SECONDS = 150.0

# 根代理层同一 (thread, 任务类型) 允许真实派发子代理的最大次数。
# 根代理是 ReAct 循环：一旦它认为派发结果不理想（或工具抛错），会自己再调一次
# 同一个派发工具——这是「一次任务里 drafting 子代理被调用 4 次」的真正触发器
# （子代理内部的 _MAX_DELIVERABLE_ATTEMPTS 管不到根代理层）。
# 超过此上限后直接失败，不再重复消耗；成功过的派发一律复用首次交付物。
_MAX_ROOT_DISPATCH_ATTEMPTS = 2


def _task_label(task_type: str) -> str:
    """任务类型的中文标签，用于日志与用户可见的报错文案。"""
    return {"drafting": "起草", "review": "审核"}.get(task_type or "", "任务")


def _total_budget_seconds(task_type: str) -> float:
    """按任务类型返回端到端预算（秒）。

    2026-09-11 修复：此前 execute() 与 _remaining_budget() 一律读
    DRAFTING_TOTAL_BUDGET_SECONDS，对审核也套用起草的 360s。审核是穷尽式扫描
    + 4 个 skill，且允许重生成一次（最坏 2 倍耗时）——实测 3751 字文档单次 205s，
    首轮不合格即 410s > 360s，会被误掐且报错文案写成「起草」。
    """
    if (task_type or "") == "review":
        return float(getattr(settings, "REVIEW_TOTAL_BUDGET_SECONDS", 1500.0) or 1500.0)
    return float(getattr(settings, "DRAFTING_TOTAL_BUDGET_SECONDS", 360.0) or 360.0)


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
        # thread_id -> 任务开始时刻：回退重跑前据此判断剩余预算，防止双跑
        self._task_started: Dict[str, float] = {}
        # thread_id -> 任务类型：预算按起草/审核分别取（见 _total_budget_seconds）
        self._task_types: Dict[str, str] = {}
        # 根代理层派活幂等（key = f"{thread_id}:{kind}"）：
        # _dispatch_done     已成功的派发结果，重复调用直接复用（不再打子代理）
        # _dispatch_attempts 已真实派发次数，达到 _MAX_ROOT_DISPATCH_ATTEMPTS 即拒绝
        # _dispatch_locks    同一 key 串行化，防并发重复派发
        self._dispatch_done: Dict[str, str] = {}
        self._dispatch_attempts: Dict[str, int] = {}
        self._dispatch_locks: Dict[str, asyncio.Lock] = {}
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
        # 与 agent_core.build_tools 保持一致：本进程若未经过 app.main（如 CLI/探针），
        # MCP 会未注册，根代理的 list_mcp_servers 会返回空（2026-09-11 修复）。
        ensure_mcp_servers_registered()
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

        def _current_thread_id() -> str:
            """取当前 LangGraph 线程号；取不到时返回空串，由调用方兜底。"""
            try:
                from langchain_core.runnables import ensure_config

                cfg = ensure_config() or {}
                return str((cfg.get("configurable") or {}).get("thread_id") or "")
            except Exception:  # noqa: BLE001
                return ""

        async def _dispatch_uncached(thread_id: str) -> str:
            """真正发起一次 A2A 派发；不含幂等判断，仅由 _dispatch 调用。"""
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
            except Exception as exc:  # noqa: BLE001 — 网络/协议/超时统一走回退判断
                # 2) 回退：A2A 服务不可达（连不上/超时/协议错）时，进程内执行同一套子代理逻辑。
                # 但必须先看预算：A2A 超时 ≠ :8001 已停止，它很可能还在跑同一份活；
                # 此时再在本地跑一遍 = 双跑，耗时与费用翻倍（实测 21 分钟的主因）。
                remaining = service._remaining_budget(thread_id)
                if remaining is not None and remaining < _MIN_FALLBACK_BUDGET_SECONDS:
                    raise A2AError(
                        "A2A 未在预算内返回"
                        f"（{type(exc).__name__}: {exc}），剩余预算仅 {remaining:.0f}s，"
                        f"不足以在进程内重跑一次{_task_label(kind)}；已放弃回退以避免双倍耗时。"
                    ) from exc
                result = await run_sub_agent_task(kind, request, transport="in-process")
                result.setdefault("execution_trace", [])
                result["a2a_fallback_error"] = f"{type(exc).__name__}: {exc}"
                transport = "in-process"

            # 主控记录子代理产物：execute() 用它构建最终 task.result（不经 LLM 转手）
            if thread_id:
                service._a2a_results[thread_id] = result
            return json.dumps(result, ensure_ascii=False, default=str)

        async def _dispatch() -> str:
            """幂等派发：同一 (thread, 任务类型) 只真正调用一次子代理。

            根代理是 ReAct 循环，只要它认为派发结果不理想（或工具抛错），就会自己
            再调一次同一个工具——这是「一次任务里 drafting 子代理被调用 4 次」的触发器。
            三层护栏：
              1) 已成功过 → 直接复用首次交付物，不再打子代理（治「重复成功」）
              2) 真实派发次数达上限 → 抛错停止，不再消耗（治「反复失败重试」）
              3) 同 key 加锁串行 → 防并发下的重复派发
            """
            thread_id = _current_thread_id()
            key = f"{thread_id or '__anon__'}:{kind}"
            lock = service._dispatch_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                service._dispatch_locks[key] = lock

            async with lock:
                cached = service._dispatch_done.get(key)
                if cached is not None:
                    logger.warning(
                        "[deepagents] 拦截重复派活 key=%s：复用首次交付物，"
                        "不再重复调用子代理（本任务已真实执行 %d 次）",
                        key,
                        service._dispatch_attempts.get(key, 0),
                    )
                    return cached

                attempts = service._dispatch_attempts.get(key, 0)
                if attempts >= _MAX_ROOT_DISPATCH_ATTEMPTS:
                    raise A2AError(
                        f"同一{_task_label(kind)}任务已派发 {attempts} 次仍未成功，"
                        "已停止重试以避免重复消耗（双跑）。"
                    )

                service._dispatch_attempts[key] = attempts + 1
                result_json = await _dispatch_uncached(thread_id)
                service._dispatch_done[key] = result_json
                return result_json

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
        self._task_started[task_key] = orchestrator_start
        _task_type = request.get("task_type", "")
        self._task_types[task_key] = _task_type
        budget = _total_budget_seconds(_task_type)
        try:
            prompt = self._build_prompt(request, as_root=True)
            # 总预算看门狗：不论链路内部如何超时/重试/回退，用户等待不超过 budget 秒
            raw_result = await asyncio.wait_for(
                self._agent.ainvoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config={"configurable": {"thread_id": task_key}},
                ),
                timeout=budget,
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
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - orchestrator_start
            label = _task_label(_task_type)
            logger.error(
                "[deepagents] %s超出总预算 task=%s 已用 %.1fs（预算 %.0fs）",
                label, task_key, elapsed, budget,
            )
            task.status = "failed"
            if _task_type == "review":
                task.error = (
                    f"审核超过 {budget:.0f} 秒预算已中止（已用 {elapsed:.0f}s）。"
                    "建议拆分为多个章节分别送审，或缩短待审文档。"
                )
            else:
                task.error = (
                    f"起草超过 {budget:.0f} 秒预算已中止（已用 {elapsed:.0f}s）。"
                    "建议精简需求描述，或拆分为多份合同分别生成。"
                )
            task.events.append({
                "type": "event",
                "message": f"{label}超出 {budget:.0f} 秒预算，已中止",
                "level": "error",
                "timestamp": datetime.now().isoformat(),
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
            self._task_started.pop(task_key, None)
            self._task_types.pop(task_key, None)
            # 派活幂等状态随任务生命周期释放（key 形如 f"{task_key}:{kind}"）
            prefix = f"{task_key}:"
            for store in (self._dispatch_done, self._dispatch_attempts, self._dispatch_locks):
                for stale_key in [k for k in store if k.startswith(prefix)]:
                    store.pop(stale_key, None)

    def _remaining_budget(self, thread_id: str) -> float | None:
        """返回当前任务剩余的预算秒数（按起草/审核分别取）；无记录时返回 None。"""
        started = self._task_started.get(thread_id)
        if started is None:
            return None
        budget = _total_budget_seconds(self._task_types.get(thread_id, ""))
        return budget - (time.perf_counter() - started)

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
