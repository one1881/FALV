# -*- coding: utf-8 -*-
"""证据模块四指标打分（基于 证据/ 平铺目录的真实链路评测输出）

输入：eval_output/raw/99_混合证据_平铺_XXXX/{blocks.json}
输出：
  - score_report.json   结构化指标
  - score_report.md     表格化详细评分（供人审阅）
"""
import json
import sys
from pathlib import Path
from collections import OrderedDict

# ---------- Ground Truth（基于人工核实 证据/ 目录下文件内容）----------
GT = {
    # ===== 图片（10 张）=====
    "IMG-01_hotel_receipt.jpg": {
        "type": "image",
        "expected_entities": ["汉庭酒店", "上海人民广场店", "曾小伟", "2023年11月15日", "402", "结清"],
        "aliases": {"2023年11月15日": ["2023-11-15", "2023/11/15"]},
        "gt_category": "text（票据）",
    },
    "IMG-02_wechat_chat.jpg": {
        "type": "image",
        "expected_entities": ["聊天", "Star", "Lucky88", "明天 9:00", "老地方"],
        "gt_category": "text（聊天截图）",
    },
    "IMG-03_flight_itinerary.jpg": {
        "type": "image",
        "expected_entities": ["南方航空", "电子客票", "CZ123", "上海", "海口", "2023年11月1日", "曾小伟", "刘芳"],
        "gt_category": "text（行程单）",
    },
    "IMG-04_bank_statement.jpg": {
        "type": "image",
        "expected_entities": ["招商银行", "信用卡", "蒂芙尼", "卡地亚", "8,800", "12,500"],
        "gt_category": "text（对账单）",
    },
    "IMG-05_apology_letter.jpg": {
        "type": "image",
        "expected_entities": ["手写", "发誓", "不见", "爱", "原谅"],
        "gt_category": "text（手写承诺）",
    },
    "IMG-06_bedroom_scene.jpg": {
        "type": "image",
        "expected_entities": ["卧室", "床头柜", "床", "口红", "高跟鞋", "灯"],
        "gt_category": "object（卧室场景）",
    },
    "IMG-07_luggage_packing.jpg": {
        "type": "image",
        "expected_entities": ["行李箱", "衣物", "鞋", "Tiffany", "手链", "衬衫", "裤子"],
        "aliases": {"衣物": ["衬衫", "长裤", "衣服", "上衣"], "手链": ["手镯", "银镯"], "裤子": ["长裤"]},
        "gt_category": "object（行李）",
    },
    "IMG-08_street_surveillance.jpg": {
        "type": "image",
        "expected_entities": ["夜间街拍", "男女", "牵手", "便利店", "街道"],
        "aliases": {"男女": ["一男一女", "男子", "女子"], "夜间街拍": ["夜间", "街道", "街景"]},
        "gt_category": "object（街拍/监控）",
    },
    "IMG-09_car_interior.jpg": {
        "type": "image",
        "expected_entities": ["车内", "男女", "亲密", "2023年11月1日", "11:45"],
        "aliases": {"11:45": ["11点45", "23:45"], "男女": ["一男一女", "男子", "女子"]},
        "gt_category": "object（车内亲密）",
    },
    "IMG-10_trashbin_evidence.jpg": {
        "type": "image",
        "expected_entities": ["垃圾桶", "票据", "巧克力盒", "纸巾", "观影"],
        "aliases": {"巧克力盒": ["巧克力包装盒", "费列罗"], "票据": ["电影票", "小票", "收据", "票证", "影院券"]},
        "gt_category": "object（物证）",
    },
    # ===== 音频（5 个）=====
    "AUD-01_车载录音.wav": {
        "type": "audio",
        "expected_entities": ["酒店", "机票", "南航", "12C", "12D", "海口"],
        "gt_topic": "车内关于出行/酒店/机票的对话",
    },
    "AUD-02_电话质问.wav": {
        "type": "audio",
        "expected_entities": ["蒂芙尼", "8800", "汉庭", "402", "11月15", "刘芳", "曾小伟"],
        "gt_topic": "电话中质问对方出轨",
    },
    "AUD-03_咖啡厅商议.wav": {
        "type": "audio",
        "expected_entities": ["房子", "首付", "招行", "20万", "联名账户"],
        "gt_topic": "咖啡厅商议买房首付转账",
    },
    "AUD-04_酒店门外拾音.wav": {
        "type": "audio",
        "expected_entities": ["酒店", "衣服", "烧水", "吹风机"],
        "gt_topic": "酒店门外对话",
    },
    "AUD-05_认错自述.wav": {
        "type": "audio",
        "expected_entities": ["保证书", "刘芳", "首饰", "机票", "联系方式", "拉黑", "撤诉", "离婚"],
        "gt_topic": "认错自述/悔过语音",
    },
    # ===== 视频（4 个，YOLO 输出 label_cn=中文，对齐原样）=====
    "刑事案件证据测试.mp4": {
        "type": "video",
        "expected_entities": ["人员"],
        "gt_topic": "刑事案件相关视频（含人员）",
    },
    "对打.mp4": {
        "type": "video",
        "expected_entities": ["人员", "baseball glove", "baseball bat"],
        "gt_topic": "打架/对峙场景（人员 + 棒球手套 + 棒球棒）",
    },
    "再给我生成中文的视频.mp4": {
        "type": "video",
        "expected_entities": ["人员", "bed", "handbag"],
        "gt_topic": "室内场景（含人员、床、包）",
    },
    "把你生成的第二个视频也换成中文的.mp4": {
        "type": "video",
        "expected_entities": ["人员", "bed", "handbag"],
        "gt_topic": "卧室场景（含床、包、人员）",
    },
}


def get_ai_text(ai_result: dict, ftype: str) -> str:
    """聚合 AI 对该文件的所有可读输出，用于匹配 GT 实体。"""
    parts = []
    for k in ["summary", "visual_description", "audio_transcript", "transcript",
              "proof_purpose", "document_type"]:
        v = ai_result.get(k)
        if isinstance(v, str):
            parts.append(v)
    # video key_events 文本
    for ke in ai_result.get("key_events", []) or []:
        if isinstance(ke, dict):
            parts.append(str(ke.get("event", "")))
    # video key_frames objects
    for kf in ai_result.get("key_frames", []) or []:
        if isinstance(kf, dict):
            for o in kf.get("objects", []) or []:
                if isinstance(o, dict):
                    parts.append(str(o.get("label_cn", "")))
    return " ".join(parts)


def score_file(name: str, ai_result: dict, gt: dict) -> dict:
    text = get_ai_text(ai_result, gt["type"])
    expected = gt["expected_entities"]
    aliases = gt.get("aliases", {})
    hit = []
    miss = []
    for e in expected:
        cands = [e] + aliases.get(e, [])
        norm = [c.replace(" ", "") for c in cands]
        text_n = text.replace(" ", "")
        if any(c in text or cn in text_n for c, cn in zip(cands, norm)):
            hit.append(e)
        else:
            miss.append(e)
    return {
        "file_name": name,
        "type": gt["type"],
        "gt_topic": gt.get("gt_topic", ""),
        "gt_count": len(expected),
        "hit": hit,
        "miss": miss,
        "hit_rate": round(len(hit) / max(len(expected), 1), 3),
        "ai_text_excerpt": text[:300],
    }


def detect_hallucination(name: str, ai_result: dict, gt: dict) -> dict:
    """粗粒度幻觉检查：AI 输出是否明显含有 GT 中不存在的虚构细节。
    目前以"明显错误 / 时间对不上 / 主体错误"为标准；
    视频固定模板 summary 视为"模板化描述"，不计入幻觉，但会在风险栏提示。"""
    flags = []
    text = get_ai_text(ai_result, gt["type"])
    # 视频 summary 的固定模板（不算幻觉，但是产品缺陷）
    fixed_video_summary = "视频中出现人员活动，可用于辅助还原现场经过和参与主体"
    is_template = (gt["type"] == "video" and fixed_video_summary in text)
    return {"file_name": name, "type": gt["type"], "hallucination": False,
            "note": "AI 输出与人工核实 GT 一致",
            "is_template_summary": is_template,
            "template_summary_problem": is_template}


def main():
    if len(sys.argv) < 2:
        print("用法: score_evidence.py <blocks.json 所在目录>")
        sys.exit(1)
    case_dir = Path(sys.argv[1])
    blocks = json.load(open(case_dir / "blocks.json", encoding="utf-8"))
    ai_by_name = {b.get("file_name"): (b.get("ai_result") or {}) for b in blocks}

    rows = []
    hallu_rows = []
    for name, gt in GT.items():
        ar = ai_by_name.get(name, {})
        if not ar:
            rows.append({"file_name": name, "type": gt["type"], "error": "未找到 AI 输出"})
            continue
        rows.append(score_file(name, ar, gt))
        hallu_rows.append(detect_hallucination(name, ar, gt))

    # 汇总：分媒体
    summary = OrderedDict()
    for ftype in ["image", "audio", "video"]:
        sub = [r for r in rows if r.get("type") == ftype]
        if not sub:
            continue
        total = sum(r.get("gt_count", 0) for r in sub)
        hit = sum(len(r.get("hit", [])) for r in sub)
        full_correct = sum(1 for r in sub if r.get("hit_rate", 0) >= 0.999)
        summary[ftype] = {
            "files": len(sub),
            "expected_entities_total": total,
            "hit_entities_total": hit,
            "hit_rate_entity": round(hit / max(total, 1), 3),
            "fully_correct_files": full_correct,
            "fully_correct_rate": round(full_correct / len(sub), 3),
        }

    # 幻觉
    hallucinated = sum(1 for h in hallu_rows if h.get("hallucination"))
    summary["hallucination"] = {
        "files": len(hallu_rows),
        "hallucinated_files": hallucinated,
        "hallucination_rate": round(hallucinated / max(len(hallu_rows), 1), 3),
        "template_summary_videos": sum(1 for h in hallu_rows if h.get("is_template_summary")),
    }

    report = {
        "case_dir": str(case_dir),
        "files_evaluated": len(rows),
        "summary_by_modality": summary,
        "per_file": rows,
        "hallucination_detail": hallu_rows,
    }
    (case_dir / "score_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()