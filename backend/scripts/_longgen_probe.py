"""只读诊断：长文生成的端到端耗时对照。

目的——判定"慢"发生在哪一层：
  直连 DashScope，绕过项目全部编排/工具/A2A/检查点，只留一次 LLM 调用。
  若直连同样要十几分钟 → 慢在模型侧（调用方式/模型特性）；
  若直连很快 → 慢在系统编排层。

四组对照：
  B  qwen3.8-max  开思考  非流式   ← 当前生产配置
  A  glm-5.2      开思考  非流式   ← 历史配置（复现 12 分钟那步）
  C  qwen3.8-max  关思考  非流式
  D  qwen3.8-max  开思考  流式

不修改任何生产代码或配置。
"""
import json
import time

import httpx

API_KEY = ""
for line in open(".env", encoding="utf-8"):
    if line.startswith("QWEN_API_KEY="):
        API_KEY = line.split("=", 1)[1].strip()
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 与起草子代理实际任务规模对齐：一次生成整篇合同正文
PROMPT = (
    "请起草一份《软件开发服务合同》完整正文，必须包含：合同编号、甲乙双方信息、"
    "服务内容与范围、开发周期与交付物、合同金额与付款方式、验收标准、知识产权归属、"
    "保密条款、违约责任、不可抗力、争议解决、签署栏。\n"
    "要求：条款编号完整，每一条都要有实质性内容，正文不少于 3500 字。"
    "直接输出合同正文，不要输出任何解释、说明或 markdown 围栏。"
)

CASES = [
    ("B  qwen3.8-max 开思考 非流式（当前配置）", "qwen3.8-max", True, False),
    ("A  glm-5.2     开思考 非流式（历史配置）", "glm-5.2", True, False),
    ("C  qwen3.8-max 关思考 非流式", "qwen3.8-max", False, False),
    ("D  qwen3.8-max 开思考 流式", "qwen3.8-max", True, True),
]


def run_nonstream(model: str, think: bool) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.2,
    }
    if not think:
        body["enable_thinking"] = False
    t0 = time.time()
    with httpx.Client(timeout=1200.0, trust_env=False) as c:
        r = c.post(URL, json=body, headers={"Authorization": f"Bearer {API_KEY}"})
    dt = time.time() - t0
    if r.status_code != 200:
        return {"ok": False, "dt": dt, "err": f"HTTP {r.status_code} {str(r.text)[:200]}"}
    d = r.json()
    u = d.get("usage", {}) or {}
    det = u.get("completion_tokens_details", {}) or {}
    ch = (d.get("choices") or [{}])[0]
    return {
        "ok": True,
        "dt": dt,
        "ttft": None,
        "completion": u.get("completion_tokens"),
        "reasoning": det.get("reasoning_tokens", 0),
        "content_len": len((ch.get("message") or {}).get("content") or ""),
        "finish": ch.get("finish_reason"),
    }


def run_stream(model: str, think: bool) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if not think:
        body["enable_thinking"] = False
    t0 = time.time()
    ttft = None
    nchars = 0
    usage = {}
    finish = None
    with httpx.Client(timeout=1200.0, trust_env=False) as c:
        with c.stream("POST", URL, json=body,
                      headers={"Authorization": f"Bearer {API_KEY}"}) as r:
            if r.status_code != 200:
                return {"ok": False, "dt": time.time() - t0,
                        "err": f"HTTP {r.status_code}"}
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except Exception:  # noqa: BLE001
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices") or []:
                    delta = ch.get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        if ttft is None:
                            ttft = time.time() - t0
                        nchars += len(piece)
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
    det = (usage.get("completion_tokens_details") or {})
    return {
        "ok": True,
        "dt": time.time() - t0,
        "ttft": ttft,
        "completion": usage.get("completion_tokens"),
        "reasoning": det.get("reasoning_tokens", 0),
        "content_len": nchars,
        "finish": finish,
    }


print("=" * 78)
print("长文生成对照实验（直连 DashScope，绕过项目编排层）")
print("prompt 要求：不少于 3500 字的完整合同正文")
print("=" * 78)

for label, model, think, stream in CASES:
    print(f"\n>>> {label}  running...", flush=True)
    try:
        res = (run_stream if stream else run_nonstream)(model, think)
    except Exception as e:  # noqa: BLE001
        print(f"    FAILED  {type(e).__name__}: {e}", flush=True)
        continue
    if not res["ok"]:
        print(f"    耗时 {res['dt']:.1f}s  FAILED  {res.get('err')}", flush=True)
        continue
    ttft = f"{res['ttft']:.1f}s" if res["ttft"] is not None else "—"
    print(
        f"    总耗时 {res['dt']:>7.1f}s | 首字 {ttft:>7} | "
        f"completion={res['completion']} reasoning={res['reasoning']} | "
        f"正文 {res['content_len']} 字 | finish={res['finish']}",
        flush=True,
    )

print("\n" + "=" * 78)
print("实验结束。")
