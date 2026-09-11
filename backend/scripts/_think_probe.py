"""一次性实验：验证 glm-5.2 是否支持关闭思考模式，以及思考 token 对耗时的影响。"""
import json
import sys
import time

import httpx

MODEL = sys.argv[1] if len(sys.argv) > 1 else "glm-5.2"

API_KEY = ""
for line in open(".env", encoding="utf-8"):
    if line.startswith("QWEN_API_KEY="):
        API_KEY = line.split("=", 1)[1].strip()
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

PROMPT = "请判断这句话的风险点：甲方应在收到货物后30日内付款。用一句话回答。"

cases = [
    ("默认", {}),
    ("enable_thinking=false", {"enable_thinking": False}),
    ("thinking=disabled", {"thinking": {"type": "disabled"}}),
    ("thinking=off", {"thinking": {"type": "off"}}),
]

for label, extra in cases:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 800,
        **extra,
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=180.0, trust_env=False) as c:
            r = c.post(URL, json=body, headers={"Authorization": f"Bearer {API_KEY}"})
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"{label:<24} HTTP {r.status_code}  {str(r.text)[:120]}")
            continue
        d = r.json()
        u = d.get("usage", {})
        det = u.get("completion_tokens_details", {}) or {}
        msg = d["choices"][0]["message"]
        print(f"{label:<24} {dt:>6.2f}s  completion={u.get('completion_tokens')} "
              f"reasoning={det.get('reasoning_tokens', 0)} "
              f"content_len={len(msg.get('content') or '')}")
    except Exception as e:  # noqa: BLE001
        print(f"{label:<24} 失败 {type(e).__name__}: {e}")

print("\n原始响应样例：")
print(json.dumps(d.get("choices", [{}])[0].get("message", {}), ensure_ascii=False)[:300])
