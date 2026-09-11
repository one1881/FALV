# -*- coding: utf-8 -*-
"""端到端验证异步审核流程：提交 → 轮询 → 拿结果（HTTP 真链路）。"""
import json
import sys
import time

import httpx
import psycopg2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.security import create_access_token

conn = psycopg2.connect(host="localhost", port=5432, dbname="contractsystem",
                        user="postgres", password="123456")
cur = conn.cursor()
cur.execute("select content from contracts where id=36")
content = cur.fetchone()[0]
conn.close()

token = create_access_token({"sub": "admin"})
headers = {"Authorization": f"Bearer {token}"}
base = "http://127.0.0.1:8000/api/review"

with httpx.Client(timeout=60) as client:
    # 1) 异步提交
    r = client.post(f"{base}/review-document-async", headers=headers, json={
        "document_type": "contract",
        "content": content,
        "title": "劳动合同-异步验证",
    })
    print("submit:", r.status_code, r.json())
    task_key = r.json()["task_key"]

    # 2) 轮询
    t0 = time.time()
    last_status = ""
    while time.time() - t0 < 1500:
        time.sleep(5)
        snap = client.get(f"{base}/tasks/{task_key}", headers=headers).json()
        status = snap.get("status")
        elapsed = time.time() - t0
        if status != last_status or (status == "running" and int(elapsed) % 60 < 5):
            last_ev = (snap.get("events") or [{}])[-1].get("message", "")
            print(f"[{elapsed:5.0f}s] status={status} | {last_ev[:50]}")
            last_status = status
        if status == "completed":
            result = snap.get("result") or {}
            print(f"DONE in {elapsed:.0f}s | review_status={result.get('review_status')} | issues={len(result.get('issues') or [])} | record_id={snap.get('review_record_id')}")
            break
        if status == "failed":
            print("FAILED:", snap.get("error"))
            break
