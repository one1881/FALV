# -*- coding: utf-8 -*-
"""诊断：完整复现审核子代理链路，逐轮计时定位超时点。"""
import asyncio
import json
import sys
import time

import psycopg2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_contract():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="contractsystem",
                            user="postgres", password="123456")
    cur = conn.cursor()
    cur.execute("select content from contracts where id=36")
    content = cur.fetchone()[0]
    conn.close()
    return content


async def main():
    from app.a2a_servers.agent_runtime import run_sub_agent_task

    content = get_contract()
    request = {
        "task_type": "review",
        "action": "review_document",
        "context": {
            "content": content,
            "title": "劳动合同",
            "document_type": "contract",
        },
    }
    t0 = time.time()
    try:
        result = await run_sub_agent_task("review", request, transport="in-process")
        dt = time.time() - t0
        print(f"\n[OK] total {dt:.0f}s")
        issues = result.get("issues") or []
        print("review_status:", result.get("review_status"), "| issues:", len(issues))
        trace = result.get("execution_trace") or []
        for step in trace[-6:]:
            print("trace:", json.dumps(step, ensure_ascii=False)[:200])
    except Exception as exc:
        dt = time.time() - t0
        print(f"\n[FAIL] after {dt:.0f}s -> {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
