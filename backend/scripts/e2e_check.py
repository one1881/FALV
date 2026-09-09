# -*- coding: utf-8 -*-
"""三大板块端到端结果验证脚本

用法:
    python scripts/e2e_check.py            # 全跑
    python scripts/e2e_check.py draft      # 只跑起草
    python scripts/e2e_check.py review     # 只跑审核
    python scripts/e2e_check.py litigation # 只跑诉讼
"""
import sys
import time
import json

import httpx

BASE = "http://127.0.0.1:8000/api"
USER = {"username": "admin", "password": "password123"}


def login(client: httpx.Client) -> str:
    r = client.post(f"{BASE}/auth/login", json=USER, timeout=30)
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token") or data.get("data", {}).get("access_token")
    if not token:
        raise RuntimeError(f"登录未返回 token: {data}")
    return token


def show(title: str, body: str, limit: int = 1500) -> None:
    print(f"\n----- {title} (总长 {len(body)} 字) -----")
    print(body[:limit])
    if len(body) > limit:
        print(f"... [截断，共 {len(body)} 字]")


def test_draft(client: httpx.Client, headers: dict) -> bool:
    payload = {
        "contract_type": "采购合同",
        "customer_name": "云起科技有限公司",
        "amount": 4800000,
        "jurisdiction": "中国",
        "industry": "信息技术",
        "description": "云起科技有限公司向华信物流股份有限公司采购 200 台工业服务器，用于自建数据中心。",
        "requirements": (
            "采购 200 台工业服务器，单价 24000 元，总价 480 万元；分三期付款（预付 30%、"
            "到货验收 60%、质保金 10%）；交付期 60 天；质保两年；逾期交付违约金按日万分之五计算；"
            "争议提交深圳国际仲裁院仲裁；乙方需提供履约保函；甲方有权在验收不合格时单方解除合同。"
        ),
    }
    t0 = time.time()
    r = client.post(f"{BASE}/contracts/generate", json=payload, headers=headers, timeout=900)
    dt = time.time() - t0
    print(f"[起草] POST /contracts/generate -> {r.status_code}  耗时 {dt:.1f}s")
    if r.status_code != 200:
        print("响应:", r.text[:800])
        return False
    data = r.json()
    content = data.get("content") or data.get("contract_content") or ""
    if not content and isinstance(data.get("data"), dict):
        content = data["data"].get("content", "")
    print(f"合同编号: {data.get('contract_number')} | 风险等级: {data.get('risk_level')}")
    show("合同正文", content)
    ok = len(content) > 800 and "待 deepagents" not in content and "待补充" not in content[:200]
    print(f"[起草] 判定: {'✅ 产出真实内容' if ok else '❌ 仍是骨架/占位'}")
    return ok


def test_review(client: httpx.Client, headers: dict) -> bool:
    doc = """
买卖合同

甲方：云起科技有限公司
乙方：华信物流股份有限公司

第一条 甲方向乙方采购工业服务器 200 台，单价人民币 24000 元。
第二条 乙方应在合同签订后交付货物。
第三条 甲方在收到货物后付款。
第四条 如乙方逾期交付，应承担违约责任。
第五条 本合同争议由甲方所在地法院管辖。
第六条 本合同自双方签字之日起生效。
"""
    payload = {"document_content": doc, "document_type": "contract", "review_focus": "付款条款、违约责任、争议解决"}
    t0 = time.time()
    r = client.post(f"{BASE}/review/review-document", json=payload, headers=headers, timeout=900)
    dt = time.time() - t0
    print(f"[审核] POST /review/review-document -> {r.status_code}  耗时 {dt:.1f}s")
    if r.status_code != 200:
        print("响应:", r.text[:800])
        return False
    data = r.json()
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    show("审核结果", txt, 2000)
    ok = len(txt) > 500 and "待 deepagents" not in txt
    print(f"[审核] 判定: {'✅ 产出真实内容' if ok else '❌ 仍是骨架/占位'}")
    return ok


def test_litigation(client: httpx.Client, headers: dict) -> bool:
    intake = {
        "source": "manual",
        "case_type": "买卖合同纠纷",
        "customer_name": "深圳市恒通电子有限公司",
        "opposite_party": "宏达机械制造有限公司",
    }
    r = client.post(f"{BASE}/litigation/intake", json=intake, headers=headers, timeout=120)
    print(f"[诉讼] POST /litigation/intake -> {r.status_code}")
    if r.status_code != 200:
        print("响应:", r.text[:800])
        return False
    data = r.json()
    intake_id = data.get("intake_id") or data.get("id")
    print(f"受理单: intake_id={intake_id} | status={data.get('status')}")

    # 模拟前端提交完整案情后再评估
    case_info = {
        "case_title": "恒通电子诉宏达机械买卖合同纠纷",
        "case_summary": (
            "2025年11月，恒通电子与宏达机械签订《设备采购合同》，约定采购数控机床 6 台，"
            "总价 320 万元，交付期 2026年2月28日。恒通电子已于合同签订后支付预付款 120 万元。"
            "宏达机械至今逾期 5 个月未交付任何设备，恒通电子先后三次发送书面催告函，对方均未回复。"
        ),
        "dispute_amount": "1,200,000 元（预付款）+ 违约金",
        "claims": [
            "判令解除双方于2025年11月签订的《设备采购合同》",
            "判令被告返还预付款 1,200,000 元",
            "判令被告支付逾期交付违约金及资金占用利息",
            "判令被告承担本案全部诉讼费用",
        ],
    }
    t0 = time.time()
    r2 = client.post(
        f"{BASE}/litigation/intake/{intake_id}/assess",
        json=case_info, headers=headers, timeout=600,
    )
    dt = time.time() - t0
    print(f"[诉讼] POST /litigation/intake/{intake_id}/assess -> {r2.status_code}  耗时 {dt:.1f}s")
    if r2.status_code != 200:
        print("响应:", r2.text[:800])
        return False
    txt = json.dumps(r2.json(), ensure_ascii=False, indent=2)
    show("受理评估结果", txt, 2000)
    ok = len(txt) > 400
    print(f"[诉讼] 判定: {'✅ 产出真实内容' if ok else '❌ 内容异常'}")
    return ok


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    with httpx.Client() as client:
        token = login(client)
        print(f"登录成功, token 长度 {len(token)}")
        headers = {"Authorization": f"Bearer {token}"}
        results = {}
        if which in ("all", "draft"):
            results["起草"] = test_draft(client, headers)
        if which in ("all", "review"):
            results["审核"] = test_review(client, headers)
        if which in ("all", "litigation"):
            results["诉讼"] = test_litigation(client, headers)
        print("\n================ 汇总 ================")
        for k, v in results.items():
            print(f"{k}: {'✅ 可跑通并产出结果' if v else '❌ 未产出有效结果'}")


if __name__ == "__main__":
    main()
