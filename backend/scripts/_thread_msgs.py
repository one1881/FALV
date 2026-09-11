"""只读诊断：还原 agent 线程的消息序列，回答"长文被生成了几次、每次多长"。

用途：判定耗时是否来自"重复生成长文"——一次任务里若出现多条长 AI 消息
（正文/审查报告被反复产出），说明系统层存在放大器效应。

数据源：Redis 中各 checkpoint 的 checkpoint.channel_values.messages（RedisJSON）。
langgraph 的 messages 是累积数组，取最新检查点即为当前完整会话。

用法：
  cd backend && D:\\an\\python.exe scripts/_thread_msgs.py drafting
  cd backend && D:\\an\\python.exe scripts/_thread_msgs.py 45e84c92a458
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis  # noqa: E402

from app.core.config import get_settings  # noqa: E402

settings = get_settings()
r = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD or None,
    db=settings.REDIS_DB,
    decode_responses=True,
)

kw = sys.argv[1] if len(sys.argv) > 1 else ""

threads = {}
for k in r.scan_iter("checkpoint:*", count=3000):
    if "write" in k:
        continue
    try:
        raw = r.execute_command("JSON.GET", k)
        if not raw:
            continue
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        continue
    tid = d.get("thread_id") or ""
    if kw and kw not in tid:
        continue
    threads.setdefault(tid, []).append((float(d.get("checkpoint_ts") or 0), k, d.get("step")))

if not threads:
    print(f"未找到匹配 '{kw}' 的线程。")
    raise SystemExit(0)


def ts_str(ms: float) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


for tid, items in sorted(threads.items(), key=lambda kv: -max(x[0] for x in kv[1]))[:3]:
    items.sort()
    last_ts, last_key, last_step = items[-1]
    d = json.loads(r.execute_command("JSON.GET", last_key))
    cv = (d.get("checkpoint") or {}).get("channel_values") or {}
    msgs = cv.get("messages") or []

    print("=" * 78)
    print(f"线程 {tid}")
    print(f"  检查点 {len(items)} 个，最新 step={last_step}，最新活动 {ts_str(last_ts)}"
          f"（{int((datetime.datetime.now().timestamp() - last_ts / 1000))} 秒前）")
    print(f"  消息数 {len(msgs)}")
    print("=" * 78)
    print(f"{'#':>3}  {'类型':<7} {'内容字数':>9}  {'工具调用/备注'}")
    print("-" * 78)

    long_ai = 0
    for i, raw_m in enumerate(msgs):
        # langgraph 用 lc 序列化：{"lc":1,"type":"constructor","id":[...,"AIMessage"],"kwargs":{...}}
        m = raw_m
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:  # noqa: BLE001
                continue
        if not isinstance(m, dict):
            continue
        mtype = str(m.get("type") or m.get("role") or "?").lower()
        content = m.get("content")
        tcs = m.get("tool_calls")
        if mtype == "constructor":
            ids = m.get("id") or []
            mtype = str(ids[-1] if ids else "?").lower()
            kw = m.get("kwargs") or {}
            content = kw.get("content", content)
            tcs = kw.get("tool_calls", tcs)
            if kw.get("name"):
                mname = kw.get("name")
                mtype = mtype  # 保持类名判定
                tool_name = mname
            else:
                tool_name = ""
        else:
            tool_name = ""

        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content
                              if isinstance(b, dict) and b.get("type") == "text")
        clen = len(content) if isinstance(content, str) else 0

        note = ""
        if isinstance(tcs, list) and tcs:
            names = []
            for t in tcs:
                if isinstance(t, dict):
                    fn = t.get("function") or {}
                    names.append(fn.get("name") or t.get("name") or "?")
                elif isinstance(t, str):
                    names.append(t)
            note = "发起调用: " + ", ".join(names)
        if "aimessage" in mtype:
            if clen > 800:
                long_ai += 1
                note = (note + "  " if note else "") + "★ 长文输出"
            elif clen:
                note = (note + "  " if note else "") + f"短文本"
            else:
                note = (note + "  " if note else "") + "(仅工具调用，无正文)"
        elif "toolmessage" in mtype or mtype == "tool":
            note = (note + "  " if note else "") + f"工具返回 {clen} 字"
        elif "humanmessage" in mtype or mtype == "human":
            note = (note + "  " if note else "") + "任务 prompt"
        label = mtype.replace("message", "").upper()
        print(f"{i:>3}  {label:<7} {clen:>9}  {note}")

    print("-" * 78)
    print(f"AI 长文输出（content > 800 字）次数：{long_ai}")
