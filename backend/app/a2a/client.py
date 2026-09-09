"""A2A 客户端：主控 agent 用来发现并调用子 agent 服务。

流程（标准 A2A 交互）：
1. GET {base}/.well-known/agent-card.json —— 发现 agent 能力（带 TTL 缓存）
2. POST {base}/  JSON-RPC message/send —— 派发任务
3. 解析 Task.artifacts 里的 text part（JSON）拿结构化结果

异常语义（重要）：
- A2AAgentExecutionError：子代理服务已收到并真实执行了任务、执行中失败
  （多为模型/上游错误）。此时进程内重跑大概率同样失败，调用方不应回退重跑。
- A2AError：网络层失败（连不上、超时、响应非法）。调用方可安全回退进程内执行。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from app.a2a.protocol import A2A_PROTOCOL_VERSION
from app.core.config import get_settings

settings = get_settings()

CARD_CACHE_TTL_SECONDS = 600.0


class A2AError(RuntimeError):
    """A2A 调用失败——网络层错误（可安全回退进程内执行）。"""


class A2AAgentExecutionError(A2AError):
    """子代理服务已真实执行任务但执行失败（多为 LLM/上游错误）——不应回退重跑。"""


class A2AClient:
    def __init__(self, timeout_seconds: float = 900.0):
        # 起草/审核是 LLM 多轮任务，耗时可达数分钟，超时必须放宽
        self._default_timeout = timeout_seconds
        self._card_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def _auth_headers(self) -> Dict[str, str]:
        token = (settings.A2A_TOKEN or "").strip()
        return {"X-A2A-Token": token} if token else {}

    async def fetch_agent_card(self, base_url: str, force: bool = False) -> Dict[str, Any]:
        """Agent Card 发现（TTL 缓存；force=True 强制刷新，防版本漂移）。"""
        url = base_url.rstrip("/")
        cached = self._card_cache.get(url)
        if cached and not force and (time.time() - cached[0]) < CARD_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{url}/.well-known/agent-card.json")
                resp.raise_for_status()
                card = resp.json()
        except Exception as exc:
            raise A2AError(f"Agent Card 获取失败 ({url}): {exc}") from exc
        self._card_cache[url] = (time.time(), card)
        return card

    async def send_message(self, base_url: str, text: str, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """JSON-RPC message/send，返回 A2A Task dict。失败抛 A2AError/A2AAgentExecutionError。"""
        url = base_url.rstrip("/")
        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": uuid.uuid4().hex,
                    "contextId": uuid.uuid4().hex,
                    "kind": "message",
                }
            },
        }
        timeout = httpx.Timeout(timeout_seconds or self._default_timeout, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{url}/", json=payload, headers=self._auth_headers())
        except Exception as exc:
            raise A2AError(f"A2A message/send 网络失败 ({url}): {exc}") from exc

        try:
            body = resp.json()
        except Exception as exc:
            raise A2AError(f"A2A 响应非 JSON (HTTP {resp.status_code}): {exc}") from exc

        if body.get("error"):
            err = body["error"]
            detail = str(err.get("data") or "")
            # -32603 = 服务端已收到任务并执行、执行中失败 → 不该回退重跑
            if err.get("code") == -32603:
                raise A2AAgentExecutionError(
                    f"A2A agent 执行失败 agent={detail or err.get('message')} detail={err.get('data')}"
                )
            raise A2AError(
                f"A2A agent 返回错误 code={err.get('code')} msg={err.get('message')} detail={detail}"
            )
        task = body.get("result")
        if not isinstance(task, dict):
            raise A2AError(f"A2A 响应缺少 result task: {str(body)[:300]}")
        return task

    async def call_agent(self, base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """一步到位：发现（TTL 缓存）→ 派发 → 解析 artifact JSON，返回 agent 的结构化结果。"""
        card = await self.fetch_agent_card(base_url)
        agent_name = card.get("name", "?")
        task = await self.send_message(base_url, json.dumps(payload, ensure_ascii=False, default=str))
        state = (task.get("status") or {}).get("state")
        if state != "completed":
            err = task.get("error") or {}
            raise A2AError(f"A2A task state={state} agent={agent_name} error={err.get('message')}")
        for artifact in task.get("artifacts") or []:
            for part in artifact.get("parts") or []:
                if (part.get("kind") or part.get("type")) == "text" and isinstance(part.get("text"), str):
                    return self._parse_result_text(part["text"])
        raise A2AError(f"A2A task 未返回 artifact（agent={agent_name}）")

    @staticmethod
    def _parse_result_text(text: str) -> Dict[str, Any]:
        """解析 artifact text part；容忍围栏包裹。"""
        candidate = (text or "").strip()
        try:
            data = json.loads(candidate)
        except Exception:
            # 剥 ```json 围栏后重试
            import re
            cleaned = re.sub(r"^```(?:json)?\s*", "", candidate)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
            data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise A2AError(f"A2A artifact 不是 JSON 对象: {str(data)[:200]}")
        return data

    @staticmethod
    def is_reachable(base_url: str) -> bool:
        """同步探活（启动日志用）。"""
        import httpx as _httpx
        try:
            resp = _httpx.get(f"{base_url.rstrip('/')}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False
