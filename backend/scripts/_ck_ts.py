"""诊断工具：按 langgraph checkpoint 的 `checkpoint_ts` 还原 agent 线程推进时间线。

用途：排查"审核/起草任务卡在哪一步、每步耗时多久、是否发生过 A2A 超时回退重跑"。
输出中的"距上步"列即相邻 checkpoint 的间隔，间隔越大说明该步越耗时。

线程命名约定：
  主代理   thread_id = task_key，形如 review:review_document:<user_id>:<rand8>
  子代理   thread_id = review-<12hex> / drafting-<12hex>（见 app/a2a_servers/agent_runtime.py）

用法：
  cd backend && D:\\an\\python.exe scripts/_ck_ts.py                # 全部线程，最近 25 条
  cd backend && D:\\an\\python.exe scripts/_ck_ts.py 83b9d8ea       # 只看含关键字的线程
  cd backend && D:\\an\\python.exe scripts/_ck_ts.py drafting       # 只看起草线程
"""
import datetime
import json
import os
import sys
from collections import defaultdict

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

keyword = sys.argv[1] if len(sys.argv) > 1 else ""

by_thread = defaultdict(list)
for k in r.scan_iter("checkpoint:*", count=3000):
    if keyword and keyword not in k:
        continue
    try:
        raw = r.execute_command("JSON.GET", k)
        if not raw:
            continue
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        continue
    ts = float(d.get("checkpoint_ts") or 0)
    if ts <= 0:
        continue
    by_thread[d.get("thread_id") or "?"].append((ts, d.get("step")))


def hhmmss(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")


def gap(sec: float) -> str:
    if sec < 1:
        return "-"
    m, s = divmod(int(round(sec)), 60)
    return f"{m}分{s:02d}秒" if m else f"{s}秒"


# 只展示最近活跃的若干个线程，避免历史噪音
recent = sorted(by_thread.items(), key=lambda kv: max(t for t, _ in kv[1]), reverse=True)[:4]
print(f"命中 {len(by_thread)} 个线程" + (f"（关键字 {keyword}）" if keyword else "") + "，展示最近活跃的 4 个：")
for tid, items in recent:
    items.sort()
    span = (items[-1][0] - items[0][0]) / 1000
    print(f"\n[{tid}]  共 {len(items)} 个检查点，跨度 {gap(span)}")
    prev = None
    for ts, step in items:
        delta = gap((ts - prev) / 1000) if prev is not None else "-"
        print(f"   {hhmmss(ts)}  step={str(step):>3}   距上步 {delta}")
        prev = ts
