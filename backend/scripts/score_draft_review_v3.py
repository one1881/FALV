# -*- coding: utf-8 -*-
"""起草/审核 v3 指标评分器（对照《三模块评估指标_v3_20260904.md》M-01~M-04）

M-01 事实依据匹配率 = 被充分支持的事实陈述数 / 事实陈述总数（gt_facts 命中，人工复核未命中项）
M-02 法条幻觉率     = 法条幻觉样本数 / 总样本数（提取引用法条 → 人工核验存在性/版本/内容）
M-03 审核 Precision = TP / (TP + FP)
M-04 审核 Recall    = TP / (TP + FN)

用法: python score_draft_review_v3.py
"""
import json
import re
from pathlib import Path

OUT = Path(r"C:\Users\gdy\Desktop\最终版\backend\eval_output\draft_review")

DRAFT_NAMES = [
    "S_A_软件开发服务合同",
    "S_B_离婚起诉状_涉家暴",
    "S_C_民间借贷起诉状",
]
REVIEW_NAMES = [
    "R1_软件开发服务合同_10缺陷",
    "R2_房屋租赁合同_6缺陷",
    "R3_借款合同_5缺陷",
]

# ---------------------------------------------------------------------------
# M-02 法条引用提取 + 人工核验登记表
# 核验结论按法条原文登记（law, article) -> (valid, note)
# valid=False 即记 1 次法条幻觉（查无此条 / 已废止 / 张冠李戴）
# ---------------------------------------------------------------------------
CITE_RE = re.compile(r"《([^》]{2,30})》\s*第([零一二三四五六七八九十百千\d]+)条")

# 人工核验结果（跑完后按实际引用填写；未登记的引用会打印出来提示核验）
# 2026-09-05 首测核验：24 次引用中 23 次有效，1 次内容拼接错误（民法典847条用于第三方侵权条款）
LAW_VERIFY = {
    "中华人民共和国民法典第八百四十三条": (True, "技术开发合同定义，用于软件开发合同依据，成立"),
    "中华人民共和国民法典第五百零九条": (True, "全面履行原则，正确"),
    "中华人民共和国民法典第八百四十七条": (False, "职务技术成果归属条款，被用于支撑'第三方侵权责任'条款，内容拼接错误→记幻觉"),
    "中华人民共和国民法典第五百零一条": (True, "缔约保密义务，支撑保密条款成立"),
    "中华人民共和国民法典第五百七十七条": (True, "违约责任一般条款，正确"),
    "中华人民共和国民法典第五百八十五条": (True, "违约金调整，正确"),
    "中华人民共和国民法典第五百九十条": (True, "不可抗力，正确"),
    "中华人民共和国民法典第一千零七十九条": (True, "诉讼离婚+家暴准离情形，正确"),
    "中华人民共和国民法典第一千零八十四条": (True, "离婚子女抚养最有利于未成年子女原则，正确"),
    "中华人民共和国民法典第一千零八十七条": (True, "离婚财产分割照顾原则，正确"),
    "中华人民共和国民法典第一千零九十一条": (True, "家暴离婚损害赔偿，正确"),
    "中华人民共和国反家庭暴力法第二十三条": (True, "人身安全保护令，正确"),
    "中华人民共和国反家庭暴力法第二条": (True, "家暴定义，正确"),
    "中华人民共和国民法典第一千零四十二条": (True, "禁止家庭暴力，正确"),
    "中华人民共和国民事诉讼法第一百二十二条": (True, "起诉条件（2021修正后条号），正确"),
    "中华人民共和国民事诉讼法第一百二十四条": (True, "应予登记立案等情形，正确"),
    "中华人民共和国民事诉讼法第二十二条": (True, "被告住所地一般管辖（2021修正后条号），正确"),
    "中华人民共和国民法典第六百六十七条": (True, "借款合同定义，正确"),
    "中华人民共和国民法典第六百七十九条": (True, "自然人借款合同交付时成立，正确"),
    "中华人民共和国民法典第六百七十五条": (True, "按期返还借款，正确"),
    "中华人民共和国民法典第六百七十六条": (True, "逾期利息，正确"),
    "中华人民共和国民法典第一百九十五条": (True, "诉讼时效中断（催收/部分还款），正确"),
    "中华人民共和国民法典第一百八十八条": (True, "三年诉讼时效，正确"),
    "中华人民共和国民法典第五百六十一条": (True, "清偿抵充顺序（费用→利息→主债务），正确"),
}


def extract_citations(text: str):
    return [(m.group(1).strip(), m.group(2).strip()) for m in CITE_RE.finditer(text or "")]


def score_m01(name):
    d = OUT / "drafting" / name
    if not (d / "final_text.txt").exists():
        return None
    text = (d / "final_text.txt").read_text(encoding="utf-8")
    gt = json.load(open(d / "gt.json", encoding="utf-8"))
    facts = gt.get("facts", [])
    misses = [f for f in facts if f not in text]
    hits = len(facts) - len(misses)
    return {
        "name": name,
        "text_len": len(text),
        "facts_total": len(facts),
        "fact_hits": hits,
        "fact_misses_raw": misses,   # 未命中项 → 人工复核（改写/同义不算失败，但需登记）
        "citations": extract_citations(text),
    }


def score_m03_m04(name):
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
    matched_gt = set()
    issue_detail = []
    for iss in issues:
        blob = " ".join(str(iss.get(k, "")) for k in ("clause", "description", "reason", "suggestion", "title", "type"))
        hit_idx = -1
        for i, g in enumerate(gt):
            if g["keyword"] in blob and i not in matched_gt:
                hit_idx = i
                break
        if hit_idx >= 0:
            matched_gt.add(hit_idx)
        issue_detail.append({
            "matched_gt": hit_idx,
            "gt_desc": gt[hit_idx]["desc"] if hit_idx >= 0 else None,
            "ai_desc": str(iss.get("description") or iss.get("reason") or "")[:80],
        })
    tp = len(matched_gt)
    fp = len(issues) - len([d for d in issue_detail if d["matched_gt"] >= 0])
    fn = len(gt) - tp
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0
    return {
        "name": name,
        "issues_total": len(issues),
        "gt_total": len(gt),
        "TP": tp, "FP": fp, "FN": fn,
        "precision": round(precision, 1),
        "recall": round(recall, 1),
        "matched_gt_idx": sorted(matched_gt),
        "unmatched_gt": [gt[i]["desc"] for i in range(len(gt)) if i not in matched_gt],
        "issue_detail": issue_detail,   # FP 人工复核用
    }


def main():
    print("#" * 60)
    print("# M-01 事实依据匹配率（初步字符串命中，未命中项需人工复核）")
    m01_all = []
    for n in DRAFT_NAMES:
        r = score_m01(n)
        if not r:
            print(f"  [跳过] {n}: 无落盘结果")
            continue
        m01_all.append(r)
        print(f"\n== {n} ==")
        print(f"  正文 {r['text_len']} 字 | 事实 {r['fact_hits']}/{r['facts_total']} = "
              f"{round(r['fact_hits']/r['facts_total']*100,1) if r['facts_total'] else 0}%")
        if r["fact_misses_raw"]:
            print(f"  未命中(待人工复核): {r['fact_misses_raw']}")
        print(f"  引用法条: {r['citations'] or '无'}")

    print()
    print("#" * 60)
    print("# M-02 法条幻觉率（引用清单见上，核验结论写入 LAW_VERIFY 后重跑）")
    for r in m01_all:
        for law, art in r["citations"]:
            key = f"{law}第{art}条"
            v = LAW_VERIFY.get(key)
            print(f"  {key}: {'✅ ' + v[1] if v and v[0] else ('❌ 幻觉: ' + v[1] if v else '⚠️ 待核验')}")

    print()
    print("#" * 60)
    print("# M-03/M-04 审核 Precision / Recall")
    for n in REVIEW_NAMES:
        r = score_m03_m04(n)
        if not r:
            print(f"  [跳过] {n}: 无落盘结果")
            continue
        print(f"\n== {n} ==")
        print(f"  issues={r['issues_total']} GT={r['gt_total']} "
              f"TP={r['TP']} FP={r['FP']} FN={r['FN']} "
              f"Precision={r['precision']}% Recall={r['recall']}%")
        if r["unmatched_gt"]:
            print("  未命中GT(FN候选,人工复核):")
            for u in r["unmatched_gt"]:
                print(f"    - {u}")
        fps = [d for d in r["issue_detail"] if d["matched_gt"] < 0]
        if fps:
            print("  FP候选(人工复核):")
            for d in fps:
                print(f"    - {d['ai_desc']}")

    (OUT / "v3_score_detail.json").write_text(
        json.dumps({"draft": m01_all,
                    "review": [score_m03_m04(n) for n in REVIEW_NAMES]},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print("\n明细已写: eval_output/draft_review/v3_score_detail.json")


if __name__ == "__main__":
    main()
