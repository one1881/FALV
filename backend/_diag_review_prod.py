# -*- coding: utf-8 -*-
"""诊断：直打 :8002 生产 JSON-RPC，复现审核超时。"""
import asyncio
import json
import sys
import time

import httpx
import psycopg2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    conn = psycopg2.connect(host="localhost", port=5432, dbname="contractsystem",
                            user="postgres", password="123456")
    cur = conn.cursor()
    cur.execute("select content from contracts where id=36")
    content = cur.fetchone()[0]
    conn.close()

    payload = {
        "jsonrpc": "2.0",
        "id": "diag-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": json.dumps({
                    "task_type": "review",
                    "action": "review_document",
                    "context": {"content": content, "title": "劳动合同", "document_type": "contract"},
                }, ensure_ascii=False)}],
                "messageId": "diag-msg-1",
                "contextId": "diag-ctx-1",
                "kind": "message",
            }
        },
    }
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1500, connect=10)) as client:
            resp = await client.post("http://127.0.0.1:8002/", json=payload)
            dt = time.time() - t0
            body = resp.json()
            if body.get("error"):
                print(f"[{dt:.0f}s] JSON-RPC ERROR code={body['error'].get('code')}")
                print("message:", str(body["error"].get("message"))[:200])
                print("data:", str(body["error"].get("data"))[:500])
            else:
                task = body.get("result") or {}
                state = (task.get("status") or {}).get("state")
                print(f"[{dt:.0f}s] task state={state}")
                arts = task.get("artifacts") or []
                if arts:
                    txt = arts[0]["parts"][0].get("text", "")
                    data = json.loads(txt)
                    print("review_status:", data.get("review_status"), "| issues:", len(data.get("issues") or []))
    except Exception as exc:
        dt = time.time() - t0
        print(f"[FAIL after {dt:.0f}s] {type(exc).__name__}: {exc}")


asyncio.run(main())
