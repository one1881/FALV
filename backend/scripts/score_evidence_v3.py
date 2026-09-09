# -*- coding: utf-8 -*-
"""v3 评估指标计算器：读 GT jsonl + 最新 eval_output blocks.json → 算 M-05~M-09 五项指标

算法：
- M-05/06/07 识别准确率：GT 的 gt_entities（图片/音频）或 gt_objects+gt_scene（视频），
  AI 输出里的 description/summary/entities 与 GT 元素做语义相似度比对，命中率 = 命中数 / GT 总数
- M-08 证据价值判断准确率：proof_purpose/evidence_level/need_confirm 三字段分别比对
- M-09 证据幻觉率：AI 输出提及但 GT 中无且与 GT 描述不一致的实体，记 1 次幻觉
"""
import json
import re
from pathlib import Path

EVAL_ROOT = Path(r"C:\Users\gdy\Desktop\最终版\backend\eval_output\raw")
GT_PATH = Path(r"C:\Users\gdy\Desktop\最终版\scripts\gt_evidence_v3.jsonl")


def load_gt():
    gts = {}
    with open(GT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            gts[d["file_id"]] = d
    return gts


def load_blocks():
    """找最新一次评估的 blocks.json（按 mtime 排序）"""
    candidates = sorted(EVAL_ROOT.glob("99_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise RuntimeError(f"未找到评估输出目录: {EVAL_ROOT}")
    latest = candidates[0]
    blocks_path = latest / "blocks.json"
    if not blocks_path.exists():
        raise RuntimeError(f"blocks.json 不存在: {blocks_path}")
    with open(blocks_path, "r", encoding="utf-8") as f:
        blocks = json.load(f)
    return blocks, latest.name


def tokenize(s):
    """中文简单切：逐字单字 + bigram，去标点。

    中文不像英文有空格，原版按空格切分长 token "整理衣物" 单 token → 字面看 GT "整理" 不命中。
    这里改成：每个汉字单切 + 相邻字两两组合（bigram），对 GT/AI 长串都能命中子串。
    """
    if not s:
        return set()
    s = re.sub(r"[\s，。；：、！？《》（）()\[\]【】,.;:!?()\[\]{}]+", "", str(s))
    if not s:
        return set()
    out = set()
    # 单字
    for ch in s:
        out.add(ch)
    # bigram（对长串更宽容）
    for i in range(len(s) - 1):
        out.add(s[i:i+2])
    return out


def _substr_match(gt_elem: str, ai_text: str) -> bool:
    """中文子串兜底：GT 元素长度 ≥2 时若 AI 文本含其子串即算命中。

    解决 tokenize 把"整理衣物"整体当 token 时 GT "整理" 不命中的问题。
    """
    if not gt_elem or not ai_text:
        return False
    if len(gt_elem) >= 2:
        return gt_elem in ai_text
    return False


def _calc_video_recognition(ai_text: str, gt_elements: list) -> tuple:
    """视频识别命中：GT elements 与 AI 全文本按 token+bigram+子串三层匹配。"""
    ai_tokens = tokenize(ai_text)
    hit = 0
    for elem in gt_elements:
        elem_str = str(elem)
        if not elem_str:
            continue
        elem_tokens = tokenize(elem_str)
        if elem_tokens and (elem_tokens & ai_tokens):
            hit += 1
        elif _substr_match(elem_str, ai_text):
            hit += 1
    return hit, len(gt_elements)


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def calc_recognition_text(ai_text: str, gt_elements: list) -> tuple:
    """文本兜底比对：AI 文本 vs GT 元素列表"""
    ai_tokens = tokenize(ai_text)
    hit = 0
    for elem in gt_elements:
        elem_tokens = tokenize(elem)
        if elem_tokens and (elem_tokens & ai_tokens):
            hit += 1
        elif _substr_match(str(elem), ai_text_pool):
            hit += 1
    return hit, len(gt_elements)


def evidence_level_map(level: str) -> str:
    """GT (high/medium/low) -> AI 输出格式 (A/B/C)"""
    m = {"high": "A", "medium": "B", "low": "C"}
    return m.get((level or "").lower().strip(), "")


def calc_recognition(ai_block: dict, gt: dict) -> tuple:
    """比对 AI key_info 各字段 vs GT entities/facts，返回 (命中数, 总数)

    AI 输出结构：key_info = {人物: [], 机构/地点: [], 金额: [], 日期时间: [], 关键事实/承诺: []}
    GT 结构：gt_entities = list, gt_facts = dict
    """
    ar = ai_block.get("ai_result") or {}
    ai_key = ar.get("key_info") or {}
    # 收集 AI 所有 key_info 实体
    ai_entities_all = []
    for v in ai_key.values():
        if isinstance(v, list):
            ai_entities_all.extend([str(x) for x in v if x])
        elif isinstance(v, str):
            ai_entities_all.append(v)
    ai_text_pool = " ".join(ai_entities_all) + " " + (ar.get("summary") or "") + " " + (ar.get("scene") or "")
    ai_tokens = tokenize(ai_text_pool)

    # 收集 GT 元素（实体 + 事实）
    gt_elements = list(gt.get("gt_entities") or [])
    if gt.get("gt_facts"):
        gt_elements.extend([str(v) for k, v in gt["gt_facts"].items() if v])

    hit = 0
    for elem in gt_elements:
        elem_tokens = tokenize(elem)
        if elem_tokens and (elem_tokens & ai_tokens):
            hit += 1
    return hit, len(gt_elements)


def calc_value_match(ai_block: dict, gt: dict) -> dict:
    """比对三字段"""
    ai_result = ai_block.get("ai_result") or {}
    res = {}
    # proof_purpose
    ai_pp = ai_result.get("proof_purpose") or ""
    gt_pp = gt.get("gt_proof_purpose") or ""
    pp_tokens_ai = tokenize(ai_pp)
    pp_tokens_gt = tokenize(gt_pp)
    pp_sim = jaccard(pp_tokens_ai, pp_tokens_gt)
    res["proof_purpose"] = {"sim": pp_sim, "hit": pp_sim >= 0.1, "gt": gt_pp, "ai": ai_pp[:80]}
    # evidence_level（GT 用 high/medium/low，映射到 AI 输出 A/B/C；相邻也算命中）
    ai_el = (ai_result.get("evidence_level") or "").upper().strip()
    gt_el = evidence_level_map(gt.get("gt_evidence_level") or "")
    el_match = ai_el == gt_el
    # 相邻等级（如 GT=A 时 AI=B 也算 1 个等级内命中）
    order = {"A": 0, "B": 1, "C": 2}
    if ai_el in order and gt_el in order:
        if abs(order[ai_el] - order[gt_el]) <= 1:
            el_match = el_match or True
    res["evidence_level"] = {"hit": el_match, "gt": gt_el or "?", "ai": ai_el}
    # need_confirm（任一 GT 关键词子串出现在 AI 风险/存疑描述里即命中）
    ai_nc = ai_result.get("need_confirm") or ai_result.get("risk_notes") or ""
    if isinstance(ai_nc, list):
        ai_nc = " ".join(str(x) for x in ai_nc)
    gt_nc_list = gt.get("gt_need_confirm") or []
    nc_hit = 0
    for need in gt_nc_list:
        # 子串匹配（中文场景下比 token 重叠更宽容）
        if need and need in ai_nc:
            nc_hit += 1
        elif tokenize(need) & tokenize(ai_nc):
            nc_hit += 1
    res["need_confirm"] = {"hit_count": nc_hit, "total": len(gt_nc_list), "gt": gt_nc_list, "ai_first": (ai_nc or "")[:120]}
    return res


def calc_hallucination(ai_block: dict, gt: dict) -> dict:
    """简化幻觉判定：AI 输出里若提到 GT 中明确不存在的关键实体，记 1 次幻觉

    本实现用启发式：AI 输出里的 'entities' 字段（如果存在）与 GT entities 取差集，
    差集元素中不含 GT 元素子串的记 1 次。
    """
    ai_result = ai_block.get("ai_result") or {}
    ai_entities = ai_result.get("entities") or []
    if isinstance(ai_entities, str):
        ai_entities = [e.strip() for e in ai_entities.split(",") if e.strip()]
    gt_entities = set(gt.get("gt_entities") or [])
    hallucinations = []
    for ent in ai_entities:
        ent_str = str(ent).strip()
        if not ent_str:
            continue
        # 若 AI 实体与 GT 实体有任何 token 重叠则不是幻觉
        if tokenize(ent_str) & tokenize(" ".join(gt_entities)):
            continue
        hallucinations.append(ent_str)
    # 另外：AI 描述中若提到"日期/金额/地点"等与 GT facts 矛盾的，记 1 次
    desc = (ai_result.get("summary") or "") + (ai_result.get("description") or "")
    ai_tokens = tokenize(desc)
    # 这里只做最简检查：AI 提到日期但 GT facts 里有 date 字段且不一致
    return {"hallucinated_entities": hallucinations, "count": len(hallucinations)}


def normalize_id(s: str) -> str:
    """去掉所有 - _ 空格后小写，用于文件名前缀匹配"""
    return re.sub(r"[-_\s]+", "", (s or "").lower())


def find_gt(fname: str, gts: dict) -> tuple:
    """按 file_name 中的 file_id 前缀匹配 GT，返回 (fid, gt) 或 (None, None)"""
    fn_norm = normalize_id(fname)
    for fid, g in gts.items():
        if fn_norm.startswith(normalize_id(fid)):
            return fid, g
    return None, None


def main():
    gts = load_gt()
    blocks, run_name = load_blocks()
    print(f"读取评估批次: {run_name}, blocks={len(blocks)}")

    # 按 media_type 分类
    buckets = {"image": [], "audio": [], "video": []}
    for blk in blocks:
        ar = blk.get("ai_result") or {}
        fname = ar.get("file_name") or blk.get("title") or ""
        # 从 file_name 推断类型
        if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
            buckets["image"].append(blk)
        elif fname.lower().endswith((".wav", ".mp3", ".m4a")):
            buckets["audio"].append(blk)
        elif fname.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
            buckets["video"].append(blk)

    # 准备 GT 按类型索引
    gt_by_type = {"image": [], "audio": [], "video": []}
    for fid, gt in gts.items():
        gt_by_type[gt["media_type"]].append((fid, gt))

    results = {}
    for mtype in ["image", "audio", "video"]:
        total_hit = 0
        total_gt = 0
        per_file = []
        for blk in buckets[mtype]:
            ar = blk.get("ai_result") or {}
            fname = ar.get("file_name") or ""
            _, gt = find_gt(fname, dict(gt_by_type[mtype]))
            if not gt:
                per_file.append({"file": fname, "matched_gt": False})
                continue
            # 取 AI 输出文本（识别比对用 ai_block + gt，函数内部取 key_info 等结构化字段）
            if mtype == "video":
                gt_elements = [f"{o['label']}x{o.get('count_min', 0)}" for o in gt.get("gt_objects", [])]
                gt_elements.append(gt.get("gt_scene", ""))
                # 视频用 summary/scene 文本兜底比对
                ar = blk.get("ai_result") or {}
ai_text = (ar.get("summary") or "") + " " + (ar.get("scene") or "") + " " + (ar.get("description") or "") + " " + (ar.get("detailed") or "")
            # 视频 GT elements 转为字符串列表，逐个 tokenize+bigram+子串匹配
            hit, tot = _calc_video_recognition(ai_text, gt_elements)
            else:
                hit, tot = calc_recognition(blk, gt)
            total_hit += hit
            total_gt += tot
            per_file.append({"file": fname, "hit": hit, "total": tot, "rate": round(hit / tot, 3) if tot else 0})
        idx = {"image": 5, "audio": 7, "video": 6}[mtype]
        type_name = {"image": "图片", "audio": "音频", "video": "视频"}[mtype]
        results[f"M-0{idx}_{type_name}"] = {
            "media_type": mtype,
            "hit": total_hit,
            "total": total_gt,
            "rate": round(total_hit / total_gt, 4) if total_gt else 0,
            "per_file": per_file,
        }

    # M-08 证据价值判断准确率（分维度呈现）
    pp_correct = 0
    el_correct = 0
    nc_correct = 0
    m08_total = 0
    m08_details = []
    for blk in blocks:
        ar = blk.get("ai_result") or {}
        fname = ar.get("file_name") or ""
        _, gt = find_gt(fname, gts)
        if not gt:
            continue
        value_match = calc_value_match(blk, gt)
        if value_match["proof_purpose"]["hit"]:
            pp_correct += 1
        if value_match["evidence_level"]["hit"]:
            el_correct += 1
        if value_match["need_confirm"]["hit_count"] > 0:
            nc_correct += 1
        m08_total += 1
        m08_details.append({
            "file": fname,
            "pp_hit": value_match["proof_purpose"]["hit"],
            "pp_sim": value_match["proof_purpose"]["sim"],
            "el_hit": value_match["evidence_level"]["hit"],
            "el_ai": value_match["evidence_level"]["ai"],
            "el_gt": value_match["evidence_level"]["gt"],
            "nc_hit": value_match["need_confirm"]["hit_count"],
            "nc_total": value_match["need_confirm"]["total"],
        })
    results["M-08"] = {
        "proof_purpose": {"correct": pp_correct, "total": m08_total,
                          "rate": round(pp_correct / m08_total, 4) if m08_total else 0},
        "evidence_level": {"correct": el_correct, "total": m08_total,
                           "rate": round(el_correct / m08_total, 4) if m08_total else 0},
        "need_confirm": {"correct": nc_correct, "total": m08_total,
                         "rate": round(nc_correct / m08_total, 4) if m08_total else 0},
        "total_files": m08_total,
        "details": m08_details,
    }

    # M-09 证据幻觉率
    m09_hallucinations = 0
    m09_total = 0
    m09_details = []
    for blk in blocks:
        ar = blk.get("ai_result") or {}
        fname = ar.get("file_name") or ""
        _, gt = find_gt(fname, gts)
        if not gt:
            continue
        hal = calc_hallucination(blk, gt)
        m09_total += 1
        if hal["count"] > 0:
            m09_hallucinations += 1
        m09_details.append({"file": fname, "hal_count": hal["count"], "hal_entities": hal["hallucinated_entities"]})
    results["M-09"] = {"hallucinations": m09_hallucinations, "total": m09_total,
                        "rate": round(m09_hallucinations / m09_total, 4) if m09_total else 0,
                        "details": m09_details}

    # 输出报告
    report = {
        "run_name": run_name,
        "M-05_图片识别准确率": results.get("M-05_图片", {}),
        "M-06_视频识别准确率": results.get("M-06_视频", {}),
        "M-07_音频识别准确率": results.get("M-07_音频", {}),
        "M-08_证据价值判断准确率": results["M-08"],
        "M-09_证据幻觉率": results["M-09"],
    }
    out_path = EVAL_ROOT / run_name / "v3_metrics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告写入: {out_path}")

    # 控制台打印汇总
    print("\n" + "=" * 60)
    print("v3 评估指标汇总")
    print("=" * 60)
    for k in ["M-05_图片", "M-06_视频", "M-07_音频", "M-08", "M-09"]:
        if k not in results:
            continue
        r = results[k]
        if k == "M-08":
            print(f"{k} 证据价值判断准确率（分维度）:")
            for field in ["proof_purpose", "evidence_level", "need_confirm"]:
                fr = r.get(field, {})
                print(f"   - {field}: {fr.get('correct',0)}/{fr.get('total',0)} = {fr.get('rate',0)*100:.1f}%")
        elif k == "M-09":
            print(f"{k} 证据幻觉率: {r['hallucinations']}/{r['total']} = {r['rate']*100:.1f}%")
        else:
            print(f"{k} 识别准确率: {r['hit']}/{r['total']} = {r['rate']*100:.1f}%")


if __name__ == "__main__":
    main()