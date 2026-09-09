# -*- coding: utf-8 -*-
"""文字/物体图片评测（qwen3.8-max + 分类修复后）：对照 3-0014（qwen-vl-plus 物体提示词）。

流程：login -> create intake -> upload 10 张 jpg -> 逐张单文件 analyze -> 取 confirmation_blocks ai_result
      -> 复用 score_evidence.GT/score_file 打分 -> 与 3-0014 同口径对比输出 JSON。
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8000"
ROOT = Path(r"C:\Users\gdy\Desktop\最终版\证据")
BACKEND = Path(r"C:\Users\gdy\Desktop\最终版\backend")
OLD_DIR = BACKEND / "eval_output" / "raw" / "99_混合证据_平铺_3-0014"

IMG_FILES = sorted([f for f in ROOT.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png"}])


def load_score_module():
    spec = importlib.util.spec_from_file_location("score_evidence", BACKEND / "scripts" / "score_evidence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def api(token, method, path, **kw):
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        return requests.get(BASE + path, headers=headers, timeout=180, **kw)
    headers.setdefault("Content-Type", "application/json")
    return requests.request(method, BASE + path, headers=headers, timeout=1800, **kw)


def main():
    token = requests.post(BASE + "/api/auth/login",
                          json={"username": "admin", "password": "password123"}, timeout=30).json()["access_token"]
    intake_id = api(token, "POST", "/api/litigation/intake",
                    json={"source": "文字图片评测-分类修复后", "case_type": "综合",
                          "customer_name": "评测"}).json()["intake_id"]
    with requests.Session() as s:
        s.headers["Authorization"] = f"Bearer {token}"
        payload = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in IMG_FILES]
        up = s.post(BASE + f"/api/litigation/intake/{intake_id}/files", files=payload, timeout=600).json()
        for _, h in payload:
            h[1].close()
    saved = up.get("saved", [])
    print(f"intake={intake_id} 上传 {len(saved)} 张")

    per = {}
    for m in saved:
        mid = m["material_id"]
        t0 = time.time()
        r = api(token, "POST", f"/api/litigation/intake/{intake_id}/materials/{mid}/analyze")
        cost = round(time.time() - t0, 1)
        body = r.json() if r.status_code < 400 else {"http_error": r.status_code, "body": r.text[:300]}
        print(f"  {m['file_name']}  {cost}s status={body.get('status')}", flush=True)
        per[m["file_name"]] = body
        time.sleep(0.3)

    detail = api(token, "GET", f"/api/litigation/intake/{intake_id}").json()
    blocks = []
    for blk in (detail.get("confirmation_blocks") or []):
        ai = blk.get("ai_result") or {}
        # 确认块顶层不一定带 file_name，真名在 ai_result 内部（历史踩坑点）
        blocks.append({"file_name": blk.get("file_name") or ai.get("file_name"),
                       "material_id": blk.get("material_id") or ai.get("material_id"),
                       "ai_result": ai})
    # 补充 provider 到 ai_result（单文件接口返回裁剪过）
    for b in blocks:
        ar = b.get("ai_result") or {}
        b["_endpoint"] = per.get(b.get("file_name"), {})

    sc = load_score_module()
    ai_by_name = {b.get("file_name"): (b.get("ai_result") or {}) for b in blocks}

    # —— 旧版 3-0014 同口径 ——
    old_blocks = json.load(open(OLD_DIR / "blocks.json", encoding="utf-8"))
    old_ai = {b.get("file_name"): (b.get("ai_result") or {}) for b in old_blocks}

    def score_all(ai_map):
        rows = []
        for name, gt in sc.GT.items():
            if gt.get("type") != "image":
                continue
            ar = ai_map.get(name, {})
            if not ar:
                rows.append({"file_name": name, "error": "未找到 AI 输出"})
                continue
            rows.append(sc.score_file(name, ar, gt))
        return rows

    old_rows = score_all(old_ai)
    new_rows = score_all(ai_by_name)

    def agg(rows):
        rows = [r for r in rows if "hit_rate" in r]
        total = sum(r["gt_count"] for r in rows)
        hit = sum(len(r["hit"]) for r in rows)
        full = sum(1 for r in rows if r["hit_rate"] >= 0.999)
        return {"files": len(rows), "gt": total, "hit": hit,
                "hit_rate": round(hit / max(total, 1), 4),
                "full_correct": full, "full_rate": round(full / max(len(rows), 1), 4)}

    result = {
        "intake_id": intake_id,
        "old": {"desc": "qwen-vl-plus + 物体提示词(全object分类bug) [3-0014]", "agg": agg(old_rows),
                "rows": [{r["file_name"]: {"hit": r.get("hit"), "miss": r.get("miss"),
                                            "rate": r.get("hit_rate")}} for r in old_rows]},
        "new": {"desc": "qwen3.8-max + 分类修复(text/object提示词)", "agg": agg(new_rows),
                "rows": [{r["file_name"]: {"hit": r.get("hit"), "miss": r.get("miss"),
                                            "rate": r.get("hit_rate"),
                                            "cls": (ai_by_name.get(r["file_name"], {}).get("classification") or {}).get("category"),
                                            "provider": (ai_by_name.get(r["file_name"], {}) or {}).get("provider")}}
                         for r in new_rows]},
        "per_file_endpoint": per,
    }
    out = BACKEND / "eval_output" / "raw" / f"99_混合证据_平铺_{intake_id[-6:]}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "image_compare.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"OLD": result["old"]["agg"], "NEW": result["new"]["agg"]}, ensure_ascii=False, indent=2))
    print("输出:", out)


if __name__ == "__main__":
    main()
