"""一次性统计：聚合各 langgraph 线程的存活时长，用于回答"起草/审核到底多慢"。"""
import datetime
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis  # noqa: E402

from app.core.config import get_settings  # noqa: E402

s = get_settings()
r = redis.Redis(host=s.REDIS_HOST, port=s.REDIS_PORT, password=s.REDIS_PASSWORD or None,
                db=s.REDIS_DB, decode_responses=True)

buckets = defaultdict(list)
steps = defaultdict(list)
for k in r.scan_iter("checkpoint:*", count=3000):
    try:
        raw = r.execute_command("JSON.GET", k)
        if not raw:
            continue
        d = json.loads(raw)
        ts = float(d.get("checkpoint_ts") or 0)
        if ts <= 0:
            continue
        tid = d.get("thread_id") or "?"
        buckets[tid].append(ts)
        steps[tid].append(d.get("step"))
    except Exception:  # noqa: BLE001
        continue


def fmt(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M:%S")


rows = []
for tid, tss in buckets.items():
    span = (max(tss) - min(tss)) / 1000
    rows.append((max(tss), tid, min(tss), max(tss), span, len(tss)))

rows.sort(reverse=True)
print(f"{'结束时刻':<16}{'时长':>9}{'点数':>6}  线程")
for _, tid, t0, t1, span, n in rows[:25]:
    mm, ss = divmod(int(span), 60)
    print(f"{fmt(t1):<16}{mm:>4}分{ss:>2}秒{n:>6}  {tid}")

print("\n=== 按类型汇总（分钟）===")
for kind, pred in (("起草子代理 drafting-*", lambda t: t.startswith("drafting-")),
                   ("审核子代理 review-*", lambda t: t.startswith("review-")),
                   ("主代理 task_key", lambda t: ":" in t)):
    spans = [(max(v) - min(v)) / 1000 for k, v in buckets.items() if pred(k)]
    if spans:
        spans.sort()
        mid = spans[len(spans) // 2]
        print(f"{kind}: n={len(spans)} 最短 {spans[0]/60:.1f} 中位 {mid/60:.1f} 最长 {spans[-1]/60:.1f}")
