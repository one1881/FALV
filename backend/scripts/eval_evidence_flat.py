# -*- coding: utf-8 -*-
"""评测 Runner：把 证据/ 目录里所有材料按真实链路跑一遍。

适用：根目录直接平铺的文件（无案件子目录）。
流程：login -> create intake -> upload files -> analyze each -> dump ai_result JSON
输出：backend/eval_output/raw/99_混合证据_平铺_<ts>/{meta.json, blocks.json, per_mat/<file>.json}

用法：
  D:/an/python.exe scripts/eval_evidence_flat.py
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8000"
ROOT = Path(r"C:\Users\gdy\Desktop\数据")
GT_JSONL = Path(r"C:\Users\gdy\Desktop\最终版\scripts\gt_evidence_v3.jsonl")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp",
             ".mp3", ".wav", ".m4a",
             ".mp4", ".mov", ".avi", ".mkv", ".webm"}


def api(token, method, path, **kw):
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        r = requests.get(BASE + path, headers=headers, timeout=180, **kw)
    else:
        headers.setdefault("Content-Type", "application/json")
        r = requests.request(method, BASE + path, headers=headers, timeout=1800, **kw)
    return r


def login():
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": "admin", "password": "password123"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def create_intake(token, meta):
    r = api(token, "POST", "/api/litigation/intake",
            json={"source": "评测-证据模块-平铺目录",
                  "case_type": meta.get("case_type", "综合"),
                  "customer_name": meta.get("customer_name", "当事人"),
                  "opposite_party": meta.get("opposite_party", "相对方")})
    r.raise_for_status()
    return r.json()["intake_id"]


def upload_files(token, intake_id, files):
    with requests.Session() as s:
        s.headers["Authorization"] = f"Bearer {token}"
        payload = [("files", (f.name, open(f, "rb"), "application/octet-stream")) for f in files]
        r = s.post(BASE + f"/api/litigation/intake/{intake_id}/files",
                   files=payload, timeout=600)
        for _, handle in payload:
            handle[1].close()
        r.raise_for_status()
        return r.json()


def analyze_one(token, intake_id, material_id):
    r = api(token, "POST",
            f"/api/litigation/intake/{intake_id}/materials/{material_id}/analyze")
    if r.status_code >= 400:
        return {"http_error": r.status_code, "body": r.text[:500]}
    return r.json()


def get_detail(token, intake_id):
    r = api(token, "GET", f"/api/litigation/intake/{intake_id}")
    r.raise_for_status()
    return r.json()


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    files = sorted([f for f in ROOT.iterdir() if f.suffix.lower() in MEDIA_EXT])
    print(f"[Root] 待处理文件 {len(files)} 个")
    for f in files:
        print(f"  - {f.name}  ({f.stat().st_size/1024:.1f} KB)")

    if only == "smoke":
        files = files[:1]
        print(f"[Smoke] 仅跑 {len(files)} 个")
    elif only == "video":
        files = [f for f in files if f.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}]
        print(f"[Video] 仅跑 {len(files)} 个视频")
    elif only == "audio":
        files = [f for f in files if f.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".ogg"}]
        print(f"[Audio] 仅跑 {len(files)} 个音频")
    elif only == "audiovideo":
        files = [f for f in files if f.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".ogg"}]
        print(f"[AudioVideo] 仅跑 {len(files)} 个音视频")

    token = login()
    print("登录成功")
    intake_id = create_intake(token, {})
    print(f"intake_id={intake_id}")

    up = upload_files(token, intake_id, files)
    saved = up.get("saved", [])
    print(f"已保存 {len(saved)} 个材料")

    case_out = ROOT.parent / "backend" / "eval_output" / "raw" / f"99_混合证据_平铺_{intake_id[-6:]}"
    case_out.mkdir(parents=True, exist_ok=True)
    (case_out / "meta.json").write_text(
        json.dumps({"intake_id": intake_id,
                    "case_type": "综合（IMG/AUD/VIDEO 平铺）",
                    "uploaded": [{m["material_id"]: m["file_name"]} for m in saved]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    per_dir = case_out / "per_mat"
    per_dir.mkdir(exist_ok=True)

    summary = []
    for m in saved:
        mid = m["material_id"]
        t0 = time.time()
        print(f"\n[{m['file_name']}] 分析中...", flush=True)
        try:
            res = analyze_one(token, intake_id, mid)
        except Exception as exc:
            res = {"status": "exception", "error": repr(exc)}
        cost = round(time.time() - t0, 1)
        status = res.get("status") or res.get("http_error") or "unknown"
        err = res.get("error")
        print(f"  完成 耗时{cost}s  status={status}  err={err}", flush=True)
        (per_dir / f"{m['file_name']}.json").write_text(
            json.dumps({"material_id": mid, "file_name": m["file_name"],
                        "cost_s": cost, "raw_response": res},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        summary.append({"file_name": m["file_name"], "material_id": mid,
                        "cost_s": cost, "status": status, "error": err})

    detail = get_detail(token, intake_id)
    blocks = []
    for blk in detail.get("confirmation_blocks") or []:
        ar = blk.get("ai_result") or {}
        blocks.append({
            "material_id": blk.get("material_id"),
            "block_id": blk.get("block_id"),
            "title": blk.get("title"),
            "file_name": ar.get("file_name") or blk.get("title"),
            "status": blk.get("status"),
            "ai_result": ar,
        })
    (case_out / "blocks.json").write_text(
        json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n确认块 {len(blocks)} 个、summary {len(summary)} 条 → {case_out}")
    print("全部完成")


if __name__ == "__main__":
    main()