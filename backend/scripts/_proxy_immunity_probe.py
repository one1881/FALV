"""代理绝缘验证探针（2026-09-10 根因修复）。

故意把 HTTP_PROXY/HTTPS_PROXY 指向死地址，再走 build_chat_model() 发一次真实请求：
- 绝缘层生效 → 请求直连 DashScope，秒级返回
- 绝缘层失效 → 请求被绕进死代理，挂起 / 超时

用法:
    cd backend && python scripts/_proxy_immunity_probe.py
"""
import os
import sys
import time
from pathlib import Path

# 必须在导入 app 之前污染环境变量
os.environ["HTTP_PROXY"] = "http://127.0.0.1:1"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1"
os.environ["http_proxy"] = "http://127.0.0.1:1"
os.environ["https_proxy"] = "http://127.0.0.1:1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_core import build_chat_model  # noqa: E402

print("=" * 60)
print("污染环境变量: HTTP_PROXY/HTTPS_PROXY = http://127.0.0.1:1 (死地址)")
print("=" * 60)

m = build_chat_model()
hc = getattr(m, "http_client", None)
print(f"ChatOpenAI.http_client          = {type(hc).__name__}")
print(f"  └ trust_env                   = {getattr(hc, '_trust_env', 'N/A')}")
ac = getattr(m, "http_async_client", None)
print(f"ChatOpenAI.http_async_client     = {type(ac).__name__}")
print(f"  └ trust_env                   = {getattr(ac, '_trust_env', 'N/A')}")
print(f"model                            = {m.model_name}")
print("-" * 60)

t0 = time.time()
try:
    resp = m.invoke("只回复两个字：收到")
    dt = time.time() - t0
    print(f"[OK] 同步调用成功 {dt:.1f}s")
    print(f"     回复 = {(resp.content or '').strip()[:40]!r}")
except Exception as exc:  # noqa: BLE001
    dt = time.time() - t0
    print(f"[FAIL] 同步调用失败 {dt:.1f}s -> {type(exc).__name__}: {exc}")
    sys.exit(1)

print("=" * 60)
print("结论：代理绝缘层生效，模型请求未被环境代理劫持。")
