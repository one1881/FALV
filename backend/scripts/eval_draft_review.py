# -*- coding: utf-8 -*-
"""起草/审核模块真链路评测（注入式基准）v2 — 支持 HTTP 与 service 双模式

模式：
  python eval_draft_review.py all               # HTTP 模式（走 :8000 路由）
  python eval_draft_review.py all --service     # service 模式（直连 deepagents，绕过路由层）

评测集（标准答案内嵌）：
- 起草 S_A 软件开发服务合同 / S_B 离婚起诉状（gt_facts / gt_structure）
- 审核 R1 10 缺陷合同 / R2 6 缺陷租赁合同（GT: clause/keyword/severity）
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

# service 模式需要能 import app（backend 根目录）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

BASE = "http://localhost:8000"
OUT = Path(r"C:\Users\gdy\Desktop\最终版\backend\eval_output\draft_review")
SERVICE_MODE = "--service" in sys.argv


def login():
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": "admin", "password": "password123"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


# ---------------------------------------------------------------- service 层
if SERVICE_MODE:
    from app.services.deepagents_service import get_deepagents_service

    _seq = [0]

    async def svc_execute(task_type: str, action: str, context: dict):
        _seq[0] += 1
        svc = get_deepagents_service()
        resp = await svc.execute(
            f"eval:{task_type}:{action}:{int(time.time()*1000)}:{_seq[0]}",
            {"task_type": task_type, "action": action, "context": context},
        )
        return resp

    def svc_run(task_type, action, context):
        return asyncio.run(svc_execute(task_type, action, context))


def strip_fenced_json(text: str) -> str:
    """剥掉 deepagents 回复中可能残留的 ```json ... ``` 围栏，取内嵌正文。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            inner = obj.get("content")
            if isinstance(inner, dict):
                inner2 = inner.get("content")
                if isinstance(inner2, str) and len(inner2) > 20:
                    return inner2 if not inner2.strip().startswith("{") else strip_fenced_json(inner2)
            inner_s = inner if isinstance(inner, str) else ""
            if inner_s and len(inner_s) > 20:
                return inner_s
    except Exception:
        pass
    return t


# --------------------------------------------------------------------------- #
# 起草评测样本
# --------------------------------------------------------------------------- #
DRAFT_SAMPLES = {
    "S_A_软件开发服务合同": {
        "document_type": "软件开发服务合同",
        "customer_name": "广州云启科技有限公司",
        "contract_type": "软件开发服务合同",
        "contract_amount": 100000,
        "jurisdiction": "中国",
        "industry": "软件服务",
        "description": "甲方委托乙方开发一套进销存管理系统，交付后可稳定运行，甲方按里程碑付款。",
        "requirements": ("1.功能范围：商品管理、库存管理、订单管理、报表管理四大模块；"
                         "2.工期：90个日历日；3.验收：系统功能测试通过后书面验收；"
                         "4.质保：验收合格后提供12个月质保。"),
        "materials_text": ("双方于2026年8月1日洽谈。合同总金额为人民币100,000元（含税）。"
                           "付款：合同签订后3日内支付30%首付款；功能验收合格后支付60%；"
                           "12个月质保期满且无未决问题后支付剩余10%。"),
        "materials": [],
        "gt_facts": ["100,000", "含税", "30%", "60%", "10%", "90个日历日",
                     "商品管理", "库存管理", "订单管理", "报表管理", "广州云启",
                     "2026年8月1日", "12个月质保"],
        "gt_structure": ["合同编号", "甲方", "乙方", "鉴于", "定义", "开发内容",
                         "开发周期", "金额", "付款", "交付", "验收", "知识产权",
                         "保密", "违约责任", "争议解决", "不可抗力", "生效", "签署"],
    },
    "S_B_离婚起诉状_涉家暴": {
        "document_type": "民事起诉状",
        "case_type": "离婚纠纷（涉家庭暴力）",
        "customer_name": "林××",
        "description": "为原告林××起草一份民事起诉状：离婚并申请人身安全保护令。",
        "requirements": ("起诉状应包含：当事人信息、诉讼请求、事实与理由、证据与来源、法律依据、"
                         "此致法院与落款。诉讼请求：1.判决离婚；2.婚生女抚养权归原告；"
                         "3.依法分割夫妻共同财产；4.被告支付损害赔偿；5.申请人身安全保护令。"),
        "materials_text": ("原告林××与被告李××于2018年登记结婚，婚后育有一女（2019年出生）。"
                           "被告长期酗酒，酒后多次实施家庭暴力。2026年3月12日22时许，被告再次酒后施暴，"
                           "拳击原告致其左前臂软组织挫伤、多处表皮擦伤。原告当日23时报警（110），"
                           "并于次日就医，取得诊断证明。有微信聊天记录（被告威胁言语、承认动手）、伤情照片、"
                           "诊断证明书、报警回执、威胁通话录音等证据。原告现起诉离婚并要求人身安全保护令。"),
        "materials": [],
        "gt_facts": ["2018年", "2019年出生", "2026年3月12日", "左前臂", "报警", "就医",
                     "李××", "离婚", "人身安全保护令", "损害赔偿", "抚养权", "2018",
                     "林××", "软组织挫伤"],
        "gt_structure": ["当事人信息", "诉讼请求", "事实与理由", "证据", "法律依据", "此致", "落款"],
    },
    "S_C_民间借贷起诉状": {
        "document_type": "民事起诉状",
        "case_type": "民间借贷纠纷",
        "customer_name": "赵德海",
        "description": "为原告赵德海起草一份民间借贷纠纷民事起诉状，请求判令被告偿还借款本金及利息。",
        "requirements": ("起诉状应包含：当事人信息、诉讼请求、事实与理由、证据与来源、法律依据、此致法院与落款。"
                         "诉讼请求：1.判令被告偿还借款本金人民币80,000元；"
                         "2.判令被告支付自2026年1月1日起按年利率6%计算至实际清偿之日止的利息；"
                         "3.本案诉讼费用由被告承担。"),
        "materials_text": ("原告赵德海与被告孙立军系朋友关系。被告孙立军于2025年6月15日以资金周转为由向原告借款"
                           "人民币80,000元（大写：捌万元整），约定于2025年12月31日前归还，口头约定按年利率6%计息。"
                           "原告于当日通过银行转账向被告名下账户（尾号6688，开户行：中国工商银行）转入80,000元，"
                           "被告出具借条一张，载明借款金额、还款日期，未载明利息。"
                           "还款期限届满后，原告多次通过微信催收（2026年1月、2月、3月共三次），"
                           "被告仅于2026年2月20日微信转账归还5,000元，其余本金80,000元（扣除已还5,000元后尚欠75,000元）"
                           "及利息至今未还。现依法起诉。"),
        "materials": [],
        "gt_facts": ["赵德海", "孙立军", "2025年6月15日", "80,000", "捌万元整", "2025年12月31日",
                     "年利率6%", "尾号6688", "中国工商银行", "借条", "2026年2月20日", "5,000",
                     "75,000", "微信催收", "资金周转"],
        "gt_structure": ["当事人信息", "诉讼请求", "事实与理由", "证据", "法律依据", "此致", "落款"],
    },
}

# --------------------------------------------------------------------------- #
# 审核评测样本（注入式 GT）
# --------------------------------------------------------------------------- #
R1_TEXT = """软件开发服务合同

合同编号：SD-2026-0901
签订地点：广东省深圳市
甲方（委托方）：广州云启科技有限公司
法定代表人：陈志远
乙方（开发方）：深圳数睿软件有限公司
法定代表人：刘思成

鉴于甲方拟委托乙方开发进销存管理系统，双方依据《中华人民共和国民法典》订立本合同。

第一条 开发内容
1.1 乙方为甲方开发进销存管理系统，功能包括：商品管理、库存管理、订单管理、报表管理。
1.2 具体需求以双方确认的《需求规格说明书》为准。

第二条 开发周期
2.1 本合同项下开发工期为90个日历日，自合同生效之日起计算。
2.2 里程碑安排：需求确认后15个工作日内提交需求规格说明书；需求确认后70个工作日内完成编码与内部测试；开发完成后5个工作日内提交交付物并申请验收。

第三条 合同金额与付款
3.1 本合同总金额为人民币100,000元（含税）。
3.2 付款方式：本合同生效后3日内，甲方支付合同总额的90%即人民币90,000元；系统交付后，甲方支付剩余10%即人民币10,000元。

第四条 交付与验收
4.1 乙方完成开发后，将系统部署至甲方指定服务器并通知甲方验收。
4.2 甲方应在收到乙方验收通知后7日内组织验收；甲方未在7日内提出书面异议的，视为验收合格。
4.3 验收标准以乙方内部测试报告为准。

第五条 知识产权
5.1 本项目开发成果（含源代码、文档）的知识产权归甲乙双方共同所有。
5.2 双方均有权在各自经营范围内自由使用上述成果并对外提供商业化服务，无需另行征得对方同意。

第六条 保密与数据安全
6.1 双方应对履行本合同过程中知悉的对方商业秘密予以保密。

第七条 违约责任
7.1 甲方逾期付款的，每逾期一日，按未付款项的0.05%支付违约金。
7.2 乙方逾期交付的，每逾期一日，按合同总额的5%向甲方支付违约金。
7.3 任何一方违约给对方造成损失的，违约方应承担赔偿责任。

第八条 责任限制与免责
8.1 无论何种原因，乙方对甲方任何间接损失、数据丢失或利润损失不承担任何责任。
8.2 乙方在本合同项下的累计赔偿责任总额，以甲方已支付的合同款项为限。
8.3 因乙方原因造成甲方数据丢失的，乙方不承担赔偿责任。

第九条 合同解除
9.1 本合同未尽事宜由双方协商解决。

第十条 争议解决
10.1 因本合同引起的争议，双方应友好协商；协商不成的，任何一方均可向乙方所在地人民法院提起诉讼。
10.2 任何一方亦可选择将争议提交中国国际经济贸易仲裁委员会按其仲裁规则仲裁。

第十一条 其他
11.1 本合同一式两份，双方各执一份，自双方签字盖章之日起生效。
甲方（盖章）：________    乙方（盖章）：________
日期：____年__月__日      日期：____年__月__日
"""
R1_GT = [
    {"clause": "付款", "severity": "高", "keyword": "90%", "desc": "首付即付 90%，尾款仅 10%，甲方资金风险极高且失去履约杠杆"},
    {"clause": "验收", "severity": "高", "keyword": "视为验收合格", "desc": "7 日未异议视为验收合格+以乙方内部测试为准，架空甲方验收权"},
    {"clause": "违约金", "severity": "高", "keyword": "5%", "desc": "逾期每日按总额 5% 违约金畸高，远超法定可支持上限"},
    {"clause": "责任限制", "severity": "高", "keyword": "数据丢失", "desc": "免除因乙方原因致数据丢失的责任，排除重大过失责任、显失公平"},
    {"clause": "保密", "severity": "中", "keyword": "保密", "desc": "保密条款仅有原则性一句话，无范围/期限/违约责任/数据安全措施"},
    {"clause": "知识产权", "severity": "中", "keyword": "共同所有", "desc": "成果共同所有且双方可各自商用，权属与商用边界冲突、易生纠纷"},
    {"clause": "争议解决", "severity": "中", "keyword": "仲裁", "desc": "诉讼与仲裁并存且指向不同机构，管辖约定矛盾无效风险"},
    {"clause": "解除", "severity": "中", "keyword": "解除", "desc": "无任何一方单方解除权与中途退出机制，项目僵局无法破解"},
    {"clause": "不可抗力", "severity": "低", "keyword": "不可抗力", "desc": "缺少不可抗力条款"},
    {"clause": "工期", "severity": "高", "keyword": "90", "desc": "总工期 90 日历日与里程碑 15+70+5=90 工作日口径矛盾"},
]

R2_TEXT = """房屋租赁合同

出租方（甲方）：李国强
承租方（乙方）：王芳
房屋坐落：上海市浦东新区锦绣路 1288 弄 6 号 302 室

第一条 租赁期限
1.1 租赁期限自 2026 年 10 月 1 日至 2027 年 9 月 30 日。
1.2 租赁期满，乙方应于期满当日内将房屋恢复原状交还甲方。

第二条 租金与押金
2.1 月租金人民币 6,000 元，乙方应于每月 5 日前支付当月租金。
2.2 租赁期内，甲方可根据市场行情随时上调租金，仅需提前 3 日书面通知乙方。
2.3 乙方于签约时支付押金人民币 12,000 元。租赁期满后，乙方欠缴任何费用或房屋存在除自然损耗外任何损坏的，押金不予退还，不再另行结算。

第三条 费用与维修
3.1 租赁期间房屋及其附属设施（含门窗、水管、电路、家电）的维修费用一律由乙方承担。
3.2 物业管理费、水电燃气费由乙方承担。

第四条 转租与解除
4.1 未经甲方书面同意，乙方不得转租。
4.2 乙方提前解除合同的，应向甲方支付剩余租期内全部租金的 50% 作为违约金。

第五条 违约责任
5.1 乙方逾期支付租金的，每逾期一日按日租金的 0.5% 支付违约金。
5.2 甲方未按期交房的，每逾期一日按日租金的 0.5% 支付违约金。

第六条 争议解决
6.1 因本合同引起的争议，双方协商不成的，任何一方均可向甲方所在地人民法院提起诉讼。

第七条 其他
7.1 本合同自双方签字之日起生效。
甲方：李国强    乙方：王芳
日期：2026 年 9 月 1 日
"""
R2_GT = [
    {"clause": "租金", "severity": "高", "keyword": "随时上调", "desc": "甲方可随时单方上调租金且仅提前 3 日通知，显失公平且易被认定无效"},
    {"clause": "押金", "severity": "中", "keyword": "押金不予退还", "desc": "押金退还条件过于宽泛，任何损坏即全额没收，未约定结算与举证程序"},
    {"clause": "维修", "severity": "高", "keyword": "一律由乙方承担", "desc": "房屋及设施维修责任一律归承租方，与法定出租人维修义务相悖"},
    {"clause": "违约金", "severity": "中", "keyword": "50%", "desc": "提前解约违约金=剩余租金 50%，比例畸高"},
    {"clause": "管辖", "severity": "高", "keyword": "甲方所在地", "desc": "房屋租赁纠纷属不动产纠纷应由房屋所在地法院专属管辖，约定甲方所在地无效"},
    {"clause": "交还", "severity": "低", "keyword": "交还", "desc": "无房屋交验清单与交接程序约定，损坏界定与自然损耗认定易生争议"},
]
R3_TEXT = """借款合同

合同编号：JK-2026-0305
签订地点：浙江省杭州市
出借人（甲方）：钱建国
身份证号：3301**********1234
借款人（乙方）：吴晓峰
身份证号：3301**********5678

甲乙双方系朋友关系，乙方因经营资金周转需要向甲方借款，双方经协商一致，依据《中华人民共和国合同法》第一百九十六条订立本合同，以资共同遵守。

第一条 借款金额与交付
1.1 借款本金为人民币200,000元（大写：贰拾万元整）。
1.2 甲方应于2025年3月5日前将借款一次性转入乙方指定的银行账户。

第二条 借款期限
2.1 借款期限为壹年，自2026年3月10日起至2027年3月9日止。

第三条 利息
3.1 本合同项下借款按年利率12%计息，自借款实际交付之日起计算。
3.2 利息随本金到期一次性支付。

第四条 还款
4.1 乙方应于借款期限届满之日一次性归还借款本金为人民币20,000元及全部利息。

第五条 违约责任
5.1 乙方逾期归还借款本息的，每逾期一日，应按借款总额的1%向甲方支付违约金。
5.2 逾期超过三十日的，甲方有权宣布借款提前到期。

第六条 管辖
6.1 因本合同引起的争议，双方协商不成的，由黑龙江省哈尔滨市道外区人民法院管辖。

第七条 其他
7.1 本合同一式两份，甲乙双方各执一份，自双方签字之日起生效。

甲方（签字）：钱建国
乙方（签字）：吴晓峰
签订日期：2026年3月1日
"""
R3_GT = [
    {"clause": "法条引用", "severity": "高", "keyword": "合同法", "desc": "引用《合同法》第196条，合同法已于2021年1月1日废止，应引用《民法典》借款合同章"},
    {"clause": "金额一致性", "severity": "高", "keyword": "20,000", "desc": "第一条借款本金200,000元与第四条还款金额20,000元前后矛盾，金额严重不一致"},
    {"clause": "时间错误", "severity": "高", "keyword": "2025年3月5日", "desc": "合同签订日期为2026年3月1日，交付日期却写2025年3月5日，早于签订日，时间逻辑错误"},
    {"clause": "违约金", "severity": "高", "keyword": "1%", "desc": "逾期违约金每日按借款总额1%（年化365%），远超司法保护上限，显著过高"},
    {"clause": "管辖", "severity": "中", "keyword": "哈尔滨", "desc": "双方均住杭州、合同签订与履行均在杭州，约定哈尔滨道外区法院管辖与争议无实际联系，协议管辖无效"},
]
REVIEW_SAMPLES = {
    "R1_软件开发服务合同_10缺陷": {"title": "软件开发服务合同", "document_type": "合同", "content": R1_TEXT, "gt": R1_GT},
    "R2_房屋租赁合同_6缺陷": {"title": "房屋租赁合同", "document_type": "合同", "content": R2_TEXT, "gt": R2_GT},
    "R3_借款合同_5缺陷": {"title": "借款合同", "document_type": "合同", "content": R3_TEXT, "gt": R3_GT},
}


def _flatten_issues(res: dict) -> list:
    issues = res.get("issues") or []
    if not issues:
        dims = res.get("dimensions") or {}
        for v in dims.values():
            if isinstance(v, dict):
                issues.extend(v.get("issues") or [])
    return issues


def run_draft(name, sample):
    body = {k: v for k, v in sample.items() if k not in ("gt_facts", "gt_structure")}
    body["payment_terms"] = {}
    body["delivery_schedule"] = {}
    if "contract_amount" in body and body["contract_amount"] is None:
        del body["contract_amount"]
    t0 = time.time()
    if SERVICE_MODE:
        resp = svc_run("drafting", "generate_document_from_case", body)
        res = resp.get("result") or {"status": resp.get("status"), "error": resp.get("error")}
        # 兼容 task 未结构化失败：若 result 无内容键则回退整包
        if not any(k in res for k in ("content", "document_type")):
            res = dict(resp)
    else:
        r = requests.post(BASE + "/api/drafting/generate", json=body,
                          headers={"Authorization": f"Bearer {login()}"}, timeout=1800)
        res = r.json() if r.status_code == 200 else {"http_status": r.status_code, "text": r.text[:400]}
    cost = round(time.time() - t0, 1)
    out_dir = OUT / "drafting" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "response.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "gt.json").write_text(json.dumps(
        {"facts": sample["gt_facts"], "structure": sample["gt_structure"]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    content_obj = res.get("content") or {}
    raw_content = ""
    if isinstance(content_obj, dict):
        raw_content = content_obj.get("content") or content_obj.get("html_content") or ""
    final_text = strip_fenced_json(str(raw_content))
    (out_dir / "final_text.txt").write_text(final_text, encoding="utf-8")
    print(f"[draft:{name}] {cost}s status={res.get('status')} 正文长度={len(final_text)}", flush=True)
    return {"name": name, "cost_s": cost, "status": res.get("status"), "text_len": len(final_text)}


def run_review(name, sample):
    body = {"document_type": sample["document_type"], "title": sample["title"], "content": sample["content"]}
    t0 = time.time()
    if SERVICE_MODE:
        resp = svc_run("review", "review_document", body)
        # 偶发失败自动重试一次
        if isinstance(resp, dict) and not resp.get("result") and resp.get("status") == "failed":
            print(f"[review:{name}] 首次执行失败({str(resp.get('error'))[:120]})，重试一次...", flush=True)
            resp = svc_run("review", "review_document", body)
        res = resp.get("result") or {}
        if not res:
            res = {"task_status": resp.get("status"), "task_error": str(resp.get("error") or "")[:500]}
    else:
        r = requests.post(BASE + "/api/review/review-document", json=body,
                          headers={"Authorization": f"Bearer {login()}"}, timeout=1800)
        res = r.json() if r.status_code == 200 else {"http_status": r.status_code, "text": r.text[:400]}
    cost = round(time.time() - t0, 1)
    out_dir = OUT / "review" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "response.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "gt.json").write_text(json.dumps(sample["gt"], ensure_ascii=False, indent=2), encoding="utf-8")
    issues = _flatten_issues(res) if isinstance(res, dict) else []
    print(f"[review:{name}] {cost}s review_status={res.get('review_status') if isinstance(res, dict) else '?'} issues数={len(issues)}", flush=True)
    return {"name": name, "cost_s": cost, "issues": len(issues)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = args[0] if args else "all"
    targets = [a for a in sys.argv[2:] if not a.startswith("--")]
    if SERVICE_MODE:
        print("运行模式: service 直连（绕过 HTTP 路由层）")
    token = login() if not SERVICE_MODE else None
    print("登录成功" if token else "service 模式无需登录")
    OUT.mkdir(parents=True, exist_ok=True)
    if mode in ("all", "smoke_draft", "draft"):
        names = [n for n in DRAFT_SAMPLES if (not targets or n in targets)] or list(DRAFT_SAMPLES)
        if mode == "smoke_draft":
            names = names[:1]
        for n in names:
            try:
                run_draft(n, DRAFT_SAMPLES[n])
            except Exception as exc:
                print(f"[draft:{n}] 失败: {exc}", flush=True)
    if mode in ("all", "smoke_review", "review"):
        names = [n for n in REVIEW_SAMPLES if (not targets or n in targets)] or list(REVIEW_SAMPLES)
        if mode == "smoke_review":
            names = names[:1]
        for n in names:
            try:
                run_review(n, REVIEW_SAMPLES[n])
            except Exception as exc:
                print(f"[review:{n}] 失败: {exc}", flush=True)
    print("评测请求全部结束")


if __name__ == "__main__":
    main()
