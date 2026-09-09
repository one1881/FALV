"""review-agent 独立 A2A 服务（:8002）。

启动: cd backend && python -m app.a2a_servers.review_agent_server
端点:
  GET /.well-known/agent-card.json   Agent Card（A2A 发现）
  GET /health                        探活
  POST /                             JSON-RPC 2.0（message/send / tasks/get）
"""
from __future__ import annotations

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
