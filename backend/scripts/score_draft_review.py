# -*- coding: utf-8 -*-
"""起草/审核评测打分器：读取 eval_output/draft_review 落盘结果，自动初判 + 输出比对明细
用法: python score_draft_review.py
"""
import json
import re
from pathlib import Path

OUT = Path(r"C:\Users\gdy\Desktop\最终版\backend\eval_output\draft_review")

DRAFT_STRUCT = {
    "S_A_软件开发服务合同": {
        "合同编号": ["合同编号"], "甲方": ["甲方"], "乙方": ["乙方"], "鉴于": ["鉴于"],
        "定义": ["定义"], "开发内容": ["开发内容", "功能要求"], "开发周期": ["周期", "工期"],
        "金额": ["金额"], "付款": ["付款"], "交付": ["交付"], "验收": ["验收"],
        "知识产权": ["知识产权", "著作权"], "保密": ["保密", "商业秘密"],
        "违约责任": ["违约"], "争议解决": ["争议解决", "仲裁", "诉讼"],
        "不可抗力": ["不可抗力"], "生效": ["生效"], "签署": ["签署", "盖章"],
    },
    "S_B_离婚起诉状_涉家暴": {
        "当事人信息": ["原告", "被告"], "诉讼请求": ["诉讼请求", "请求"], "事实与理由": ["事实与理由", "事实"],
        "证据": ["证据"], "法律依据": ["法律依据", "依据"], "此致": ["此致"],
        "落款": ["具状人", "起诉人", "年月日", "日期"],
    },
}


def check_draft(name):
    d = OUT / "drafting" / name
    if not (d / "response.json").exists():
        return None
    res = json.load(open(d / "response.json", encoding="utf-8"))
    gt = json.load(open(d / "gt.json", encoding="utf-8"))
    text = ""
    fp = d / "final_text.txt"
    if fp.exists():
        text = fp.read_text(encoding="utf-8")
    if not text:
        return {"name": name, "status": res.get("status"), "error": res.get("error"), "note": "无正文"}
    # D-02 结构
    structure_map = DRAFT_STRUCT.get(name, {})
    hit = {}
    for k, kws in structure_map.items():
        hit[k] = any(kw in text for kw in kws)
    # D-01 / D-04 事实
    facts = gt.get("facts", [])
    fact_hit = {f: (f in text) for f in facts}
    report = {
        "name": name,
        "text_len": len(text),
        "structure": {k: "✓" if v else "✗" for k, v in hit.items()},
        "structure_rate": round(sum(hit.values()) / len(hit) * 100, 1) if hit else 0,
        "facts": fact_hit,
        "fact_rate": round(sum(fact_hit.values()) / len(fact_hit) * 100, 1) if fact_hit else 0,
    }
    return report


def check_review(name):
    d = OUT / "review" / name
    if not (d / "response.json").exists():
        return None
    res = json.load(open(d / "response.json", encoding="utf-8"))
    gt = json.load(open(d / "gt.json", encoding="utf-8"))
    issues = res.get("issues") or []
    if not issues:
        dims = res.get("dimensions") or {}
        for v in dims.values():
            if isinstance(v, dict):
                issues.extend(v.get("issues") or [])
    sev_map = {"高": "high", "中": "medium", "低": "low"}
    # 匹配：issue 文本(description+clause) 包含 GT keyword 视为命中
    gt_hit = [False] * len(gt)
    issue_gt_idx = []
    issue_ok = []
    matched_gt = set()
    for iss in issues:
        blob = " ".join(str(iss.get(k, "")) for k in ("clause", "description", "reason", "suggestion"))
        best = -1
        for i, g in enumerate(gt):
            if g["keyword"] in blob and i not in matched_gt:
                best = i
                break
        issue_gt_idx.append(best)
        issue_ok.append(best >= 0)
        if best >= 0:
            matched_gt.add(best)
            gt_hit[best] = True
    tp = sum(1 for i, iss in enumerate(issues) if issue_ok[i])
    fn = len(gt) - sum(gt_hit)
    precision = tp / len(issues) if issues else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    # A-03 分级：命中 GT 的 issue 中 severity 是否与 GT 一致
    grade_correct = 0
    grade_total = 0
    grade_detail = []
    for i, iss in enumerate(issues):
        if issue_ok[i]:
            gt_sev = gt[issue_gt_idx[i]]["severity"]
            sys_sev = iss.get("severity", "")
            sys_sev_en = sev_map.get(sys_sev, sys_sev)
            gt_sev_en = sev_map.get(gt_sev, gt_sev)
            ok = sys_sev_en == gt_sev_en or sys_sev == gt_sev
            if ok:
                grade_correct += 1
            grade_total += 1
            grade_detail.append({"issue": str(iss.get("description"))[:40],
                                 "sys": sys_sev, "gt": gt_sev, "ok": ok})
    return {
        "name": name,
        "review_status": res.get("review_status"),
        "overall_score": res.get("overall_score"),
        "issues_total": len(issues),
        "TP": tp, "FP": len(issues) - tp, "FN": len(gt) - tp,
        "GT_total": len(gt),
        "precision": round(precision * 100, 1),
        "recall": round(recall * 100, 1),
        "grade_acc": round(grade_correct / grade_total * 100, 1) if grade_total else 0,
        "grade_detail": grade_detail,
        "gt_hit": gt_hit,
    }


def main():
    out = []
    for name in ["S_A_软件开发服务合同", "S_B_离婚起诉状_涉家暴"]:
        r = check_draft(name)
        if r:
            out.append(r)
            print("=" * 30, "起草", name)
            print("正文长度:", r["text_len"], "| 结构:", r["structure_rate"], "% | 事实命中:", r["fact_rate"], "%")
            print("  结构缺:", [k for k, v in r["structure"].items() if v == "✗"] or "无")
            print("  事实未命中:", [f for f, v in r["facts"].items() if not v] or "无")
    for name in ["R1_软件开发服务合同_10缺陷", "R2_房屋租赁合同_6缺陷"]:
        r = check_review(name)
        if r:
            out.append(r)
            print("=" * 30, "审核", name)
            print(f"review_status={r['review_status']} overall={r['overall_score']} "
                  f"issues={r['issues_total']} (GT={r['GT_total']}) "
                  f"TP={r['TP']} FP={r['FP']} FN={r['FN']}")
            print(f"Precision={r['precision']}% Recall={r['recall']}% 分级准确率={r['grade_acc']}%")
            print("  分级明细:", r["grade_detail"])
    (OUT / "score_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
