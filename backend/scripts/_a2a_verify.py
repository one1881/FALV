"""验证改造后的 A2AClient：超时取值、trust_env 生效、Agent Card 发现可用。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.a2a.client import A2AClient  # noqa: E402


async def main() -> None:
    c = A2AClient()
    print("默认超时(秒) :", c._default_timeout)
    print("trust_env    :", c._trust_env)
    print("环境代理变量 :", {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy")})
    for port in (8001, 8002):
        try:
            card = await c.fetch_agent_card(f"http://127.0.0.1:{port}")
            print(f":{port} 发现成功 -> {card.get('name')} / {card.get('url')}")
        except Exception as e:  # noqa: BLE001
            print(f":{port} 发现失败 -> {type(e).__name__}: {e}")


asyncio.run(main())
