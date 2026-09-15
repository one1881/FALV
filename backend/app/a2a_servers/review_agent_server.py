"""review-agent 独立 A2A 服务（:8002）。

启动: cd backend && python -m app.a2a_servers.review_agent_server
端点:
  GET /.well-known/agent-card.json   Agent Card（A2A 发现）
  GET /health                        探活
  POST /                             JSON-RPC 2.0（message/send / tasks/get）
"""
from __future__ import annotations

import sys
import os

# Windows 上强制使用 UTF-8 编码，避免 GBK 解码错误
if sys.platform == "win32":
    os.environ["PYTHONUTF8"] = "1"
    # 重新配置标准输入输出编码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

import uvicorn

from app.a2a.server import build_a2a_app
from app.a2a_servers.agent_runtime import (
    REVIEW_AGENT_PORT,
    REVIEW_CARD,
    parse_agent_request,
    run_sub_agent_task,
)


async def _handler(message_text: str, task_id: str) -> dict:
    request = parse_agent_request(message_text, "review")
    return await run_sub_agent_task("review", request, transport="a2a-server")


app = build_a2a_app(REVIEW_CARD, _handler)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=REVIEW_AGENT_PORT)
