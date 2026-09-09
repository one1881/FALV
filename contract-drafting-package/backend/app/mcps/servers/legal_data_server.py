"""
LegalData MCP Server - 法律数据与合规规则引擎
MCP 工具:
- get_required_clauses:    按合同类型返回必填条款清单
- get_prohibited_clauses:  按合同类型返回禁止/高风险条款
- get_industry_regulations:按行业返回相关法规清单
- get_local_regulations:   按地区返回地方法规
- check_compliance:        对合同参数做完整合规扫描(规则引擎)
- check_clause_risks:      对合同正文做条款级风险扫描(关键词/模式)
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
import re
import logging

from app.mcps.base_server import BaseMCPServer

logger = logging.getLogger(__name__)


# ---- 知识库 ----
REQUIRED_CLAUSES: Dict[str, List[Dict[str, str]]] = {
    "采购合同": [
        {"clause": "标的物明细", "law_ref": "民法典第595条"},
        {"clause": "价款与支付方式", "law_ref": "民法典第628条"},
        {"clause": "交付时间与地点", "law_ref": "民法典第600条"},
        {"clause": "质量标准与验收", "law_ref": "民法典第621条"},
        {"clause": "违约责任", "law_ref": "民法典第577条"},
        {"clause": "争议解决方式", "law_ref": "民事诉讼法第35条"},
    ],
    "销售合同": [
        {"clause": "销售标的与数量", "law_ref": "民法典第595条"},
        {"clause": "价款与付款方式", "law_ref": "民法典第628条"},
        {"clause": "交付与转移", "law_ref": "民法典第603条"},
        {"clause": "质量保证", "law_ref": "民法典第621条"},
        {"clause": "违约责任", "law_ref": "民法典第577条"},
    ],
    "服务合同": [
        {"clause": "服务内容与标准", "law_ref": "民法典第509条"},
        {"clause": "服务期限与地点", "law_ref": "民法典第511条"},
        {"clause": "服务费用", "law_ref": "民法典第512条"},
        {"clause": "验收与交付", "law_ref": "民法典第517条"},
        {"clause": "知识产权归属", "law_ref": "民法典第847条"},
        {"clause": "保密条款", "law_ref": "民法典第501条"},
    ],
    "劳动合同": [
        {"clause": "合同期限类型", "law_ref": "劳动合同法第12条"},
        {"clause": "工作内容与地点", "law_ref": "劳动合同法第17条"},
        {"clause": "工时制度", "law_ref": "劳动合同法第36条"},
        {"clause": "劳动报酬", "law_ref": "劳动合同法第30条"},
        {"clause": "社会保险", "law_ref": "劳动合同法第58条"},
        {"clause": "解除与终止", "law_ref": "劳动合同法第39条"},
    ],
    "租赁合同": [
        {"clause": "租赁物与用途", "law_ref": "民法典第703条"},
        {"clause": "租赁期限", "law_ref": "民法典第705条"},
        {"clause": "租金与支付方式", "law_ref": "民法典第726条"},
        {"clause": "维修责任", "law_ref": "民法典第712条"},
        {"clause": "转租限制", "law_ref": "民法典第716条"},
    ],
    "保密协议": [
        {"clause": "保密信息定义", "law_ref": "反不正当竞争法第9条"},
        {"clause": "保密义务范围", "law_ref": "反不正当竞争法第9条"},
        {"clause": "保密期限", "law_ref": "民法典第501条"},
        {"clause": "违约责任", "law_ref": "民法典第577条"},
    ],
}

PROHIBITED_CLAUSES: Dict[str, List[Dict[str, str]]] = {
    "销售合同": [
        {"clause": "排除或限制人身伤害赔偿责任", "law_ref": "民法典第506条(无效)"},
        {"clause": "显失公平的格式条款", "law_ref": "民法典第497条(无效)"},
        {"clause": "违反法律强制性规定的免责条款", "law_ref": "民法典第153条"},
    ],
    "采购合同": [
        {"clause": "排除或限制人身伤害赔偿责任", "law_ref": "民法典第506条(无效)"},
        {"clause": "约定无理由任意解除权", "law_ref": "民法典第563条"},
    ],
    "服务合同": [
        {"clause": "约定服务方永久免除责任", "law_ref": "民法典第506条"},
    ],
    "劳动合同": [
        {"clause": "押金或扣押身份证件", "law_ref": "劳动合同法第9条(禁止)"},
        {"clause": "约定巨额违约金", "law_ref": "劳动合同法第25条(限制)"},
        {"clause": "排除工伤保险责任", "law_ref": "社会保险法第33条"},
    ],
}

INDUSTRY_REGULATIONS: Dict[str, List[Dict[str, str]]] = {
    "互联网": [
        {"name": "网络安全法", "year": 2017, "scope": "网络运营者义务、个人信息保护"},
        {"name": "数据安全法", "year": 2021, "scope": "数据分级、跨境传输"},
        {"name": "个人信息保护法(PIPL)", "year": 2021, "scope": "个人信息处理、跨境提供"},
    ],
    "金融": [
        {"name": "商业银行法", "scope": "信贷业务规则"},
        {"name": "证券法", "scope": "证券发行与交易"},
    ],
    "医疗": [
        {"name": "药品管理法", "scope": "药品研制、生产、经营"},
        {"name": "医疗机构管理条例", "scope": "医疗机构准入"},
    ],
    "通用": [
        {"name": "民法典", "year": 2021, "scope": "合同总则与分则"},
        {"name": "公司法", "year": 2024, "scope": "公司设立、运营、治理"},
    ],
}

LOCAL_REGULATIONS: Dict[str, List[Dict[str, str]]] = {
    "北京": [{"name": "北京市优化营商环境条例", "scope": "政务服务、合同管理"}],
    "上海": [{"name": "上海市优化营商环境条例", "scope": "市场准入、政务服务"}],
    "深圳": [{"name": "深圳经济特区数据条例", "scope": "数据要素流通"}],
    "中国": [
        {"name": "民法典合同编", "scope": "全国统一合同规则"},
    ],
}

# 条款级风险扫描(关键词 + 模式 + 风险等级)
RISK_PATTERNS: List[Dict[str, Any]] = [
    {
        "id": "R001",
        "pattern": r"最终解释权",
        "level": "中",
        "issue": "经营者单方保留“最终解释权”，可能排除相对方解释和救济权利。",
        "law_ref": "《民法典》第496条、第497条；《消费者权益保护法》第26条",
        "suggestion": "删除“最终解释权归甲方所有”等单方解释表述，改为“本合同未尽事宜由双方协商确定；对条款理解发生争议的，按合同目的、交易习惯及诚信原则解释”。",
    },
    {
        "id": "R002",
        "pattern": r"概不退还|一律不退|不予退还",
        "level": "中",
        "issue": "“概不退还/一律不退”属于绝对化退款限制，可能加重对方责任或排除法定解除、返还权利。",
        "law_ref": "《民法典》第497条、第566条；《消费者权益保护法》第26条",
        "suggestion": "改为区分违约原因、履行进度和实际损失：因收款方原因解除的应退还相应款项；因付款方违约解除的，可扣除已发生合理成本和实际损失后返还余额。",
    },
    {
        "id": "R003",
        "pattern": r"一次性了结.*一切|一次性解决.*全部|不得再.*主张.*权利",
        "level": "高",
        "issue": "“一次性了结一切责任”可能过度免除一方未来责任，尤其对未知损害、故意或重大过失责任存在无效风险。",
        "law_ref": "《民法典》第506条、第497条",
        "suggestion": "限定和解/结算范围，明确仅针对已知事实和已列明款项，不排除因故意、重大过失、人身损害或法律强制规定产生的责任。",
    },
    {
        "id": "R004",
        "pattern": r"不设上限.*赔偿|赔偿.*不设上限|无限连带责任",
        "level": "高",
        "issue": "赔偿责任完全不设上限可能导致责任失衡，增加条款被调整或引发争议的风险。",
        "law_ref": "《民法典》第6条、第509条、第584条、第585条",
        "suggestion": "设置可预期的责任上限，例如以合同总价、已付款金额或直接损失为上限；同时保留故意、重大过失、保密侵权等例外情形。",
    },
    {
        "id": "R005",
        "pattern": r"放弃.*诉讼|不得.*起诉|不得.*申请仲裁|不得.*向法院",
        "level": "高",
        "issue": "预先要求一方放弃诉讼、仲裁等救济权利，可能排除法定诉权。",
        "law_ref": "《民事诉讼法》第122条；《仲裁法》第4条；《民法典》第497条",
        "suggestion": "删除“放弃诉讼/不得起诉”表述，改为约定明确的争议解决方式，如“协商不成，提交合同签订地有管辖权的人民法院诉讼解决”或约定具体仲裁委员会。",
    },
    {
        "id": "R006",
        "pattern": r"口头约定.*同等效力|口头承诺.*有效|口头变更.*有效",
        "level": "中",
        "issue": "承认口头约定与书面合同同等效力，容易造成证据不足和履行范围争议。",
        "law_ref": "《民法典》第469条、第490条、第543条",
        "suggestion": "改为“合同变更、补充应采用书面形式，经双方签字或盖章后生效；双方确认的电子邮件、系统订单等可作为书面形式”。",
    },
    {
        "id": "R007",
        "pattern": r"不可抗力.*免责|因不可抗力.*不承担",
        "level": "低",
        "issue": "不可抗力免责条款过于笼统，缺少通知、证明、减损和部分履行规则。",
        "law_ref": "《民法典》第180条、第590条、第591条",
        "suggestion": "补充不可抗力发生后的通知期限、证明材料、减损义务、受影响义务的暂停范围，以及影响消除后的继续履行或解除机制。",
    },
    {
        "id": "R008",
        "pattern": r"保密期限.*永久|永久.*保密|无限期.*保密",
        "level": "中",
        "issue": "永久保密义务如不区分商业秘密和一般信息，可能因范围过宽导致执行困难。",
        "law_ref": "《反不正当竞争法》第9条；《民法典》第501条、第509条",
        "suggestion": "将商业秘密保密至其公开或不再构成商业秘密，一般保密信息设定明确期限，例如合同终止后2至5年。",
    },
    {
        "id": "R009",
        "pattern": r"(押金|保证金).*(扣留|没收)|无条件.*没收.*(押金|保证金)",
        "level": "中",
        "issue": "无条件扣留或没收押金/保证金可能构成过高违约责任或格式条款失衡。",
        "law_ref": "《民法典》第497条、第586条、第587条、第585条",
        "suggestion": "明确保证金扣除条件、计算方式和返还期限，仅可在实际损失、已到期债务或约定违约金范围内扣除，剩余部分应及时返还。",
    },
    {
        "id": "R010",
        "pattern": r"违约金.*(\d{2,}|\d*\.\d+)\s*%",
        "level": "低",
        "issue": "违约金比例较高时，法院或仲裁机构可能根据实际损失予以调减。",
        "law_ref": "《民法典》第585条；《最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释》相关违约金调整规则",
        "suggestion": "结合交易金额、履行周期和可预见损失设置违约金，可写明按逾期金额每日万分之几或不超过实际损失的一定比例计算。",
    },
]


class LegalDataServer(BaseMCPServer):
    """法律数据 + 规则引擎 MCP server"""

    def __init__(self):
        super().__init__(name="legal_data_server", description="合规规则、必填条款、风险条款、法规库")

        self.register_tool(
            name="get_required_clauses",
            description="按合同类型返回必填条款清单及对应法条",
            input_schema={"type": "object",
                          "properties": {"contract_type": {"type": "string"}},
                          "required": ["contract_type"]},
            handler=self._get_required_clauses,
        )
        self.register_tool(
            name="get_prohibited_clauses",
            description="按合同类型返回禁止/高风险条款(以及法律依据)",
            input_schema={"type": "object",
                          "properties": {"contract_type": {"type": "string"}},
                          "required": ["contract_type"]},
            handler=self._get_prohibited_clauses,
        )
        self.register_tool(
            name="get_industry_regulations",
            description="按行业返回相关法规清单",
            input_schema={"type": "object",
                          "properties": {"industry": {"type": "string", "default": "通用"}},
                          "required": []},
            handler=self._get_industry_regulations,
        )
        self.register_tool(
            name="get_local_regulations",
            description="按地区返回地方法规/条例",
            input_schema={"type": "object",
                          "properties": {"jurisdiction": {"type": "string", "default": "中国"}},
                          "required": []},
            handler=self._get_local_regulations,
        )
        self.register_tool(
            name="check_clause_risks",
            description="对合同正文文本做条款级关键词风险扫描(返回命中的规则 ID、风险等级、原文片段)",
            input_schema={"type": "object",
                          "properties": {"contract_text": {"type": "string"}},
                          "required": ["contract_text"]},
            handler=self._check_clause_risks,
        )
        self.register_tool(
            name="check_compliance",
            description="对合同参数做合规扫描(金额、必填字段、合同类型合法性等),返回 issues+summary",
            input_schema={"type": "object",
                          "properties": {"contract_params": {"type": "object"}},
                          "required": ["contract_params"]},
            handler=self._check_compliance,
        )

    async def _get_required_clauses(self, contract_type: str) -> Dict[str, Any]:
        clauses = REQUIRED_CLAUSES.get(contract_type, [])
        return {
            "ok": True,
            "contract_type": contract_type,
            "count": len(clauses),
            "required_clauses": clauses,
            "_hint": "缺失这些条款被视为高风险,起草时务必包含",
        }

    async def _get_prohibited_clauses(self, contract_type: str) -> Dict[str, Any]:
        clauses = PROHIBITED_CLAUSES.get(contract_type, [])
        return {
            "ok": True,
            "contract_type": contract_type,
            "count": len(clauses),
            "prohibited_clauses": clauses,
            "_hint": "出现这些条款可能被判无效或引发争议",
        }

    async def _get_industry_regulations(self, industry: Optional[str] = "通用") -> Dict[str, Any]:
        regs = INDUSTRY_REGULATIONS.get(industry or "通用", INDUSTRY_REGULATIONS["通用"])
        return {"ok": True, "industry": industry, "count": len(regs), "regulations": regs}

    async def _get_local_regulations(self, jurisdiction: Optional[str] = "中国") -> Dict[str, Any]:
        regs = LOCAL_REGULATIONS.get(jurisdiction or "中国", LOCAL_REGULATIONS["中国"])
        return {"ok": True, "jurisdiction": jurisdiction, "count": len(regs), "regulations": regs}

    async def _check_clause_risks(self, contract_text: str) -> Dict[str, Any]:
        if not contract_text:
            return {"ok": True, "hits": [], "summary": {"high": 0, "medium": 0, "low": 0, "total": 0}}

        hits = []
        for rule in RISK_PATTERNS:
            for m in re.finditer(rule["pattern"], contract_text, flags=re.S):
                start = max(0, m.start() - 10)
                end = min(len(contract_text), m.end() + 10)
                hits.append({
                    "rule_id": rule["id"],
                    "level": rule["level"],
                    "issue": rule["issue"],
                    "law_ref": rule.get("law_ref", ""),
                    "suggestion": rule.get("suggestion", ""),
                    "match": m.group(0),
                    "context": contract_text[start:end].replace("\n", " "),
                })
        summary = {"high": 0, "medium": 0, "low": 0, "total": len(hits)}
        for h in hits:
            summary[h["level"]] = summary.get(h["level"], 0) + 1
        return {"ok": True, "hits": hits, "summary": summary}

    async def _check_compliance(self, contract_params: Dict[str, Any]) -> Dict[str, Any]:
        params = contract_params or {}
        issues: List[Dict[str, str]] = []

        # 规则1: 金额
        amount = params.get("contract_amount", 0) or 0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            issues.append({"rule": "金额合理性", "severity": "高",
                           "description": "合同金额必须大于0", "field": "contract_amount"})
        elif amount > 50_000_000:
            issues.append({"rule": "金额合理性", "severity": "中",
                           "description": f"金额 {amount:.0f} 元较大,建议加强审批", "field": "contract_amount"})

        # 规则2: 必填字段
        for field in ["contract_type", "jurisdiction"]:
            if not params.get(field):
                issues.append({"rule": "必填字段", "severity": "中",
                               "description": f"缺少必填字段: {field}", "field": field})

        # 规则3: 合同类型
        ct = params.get("contract_type")
        if ct and ct not in REQUIRED_CLAUSES:
            issues.append({"rule": "合同类型", "severity": "中",
                           "description": f"合同类型 [{ct}] 不在已建模清单: {list(REQUIRED_CLAUSES.keys())}",
                           "field": "contract_type"})

        # 规则4: 付款条款
        pt = params.get("payment_terms")
        if not pt:
            issues.append({"rule": "付款条款", "severity": "低",
                           "description": "建议明确付款条款(避免争议)", "field": "payment_terms"})

        # 规则5: 管辖地
        jur = params.get("jurisdiction")
        if jur and jur not in LOCAL_REGULATIONS:
            issues.append({"rule": "管辖地", "severity": "低",
                           "description": f"管辖地 [{jur}] 暂无明确地方法规,建议使用 中国 默认", "field": "jurisdiction"})

        high = sum(1 for i in issues if i["severity"] == "高")
        status = "不通过" if high > 0 else "通过"
        return {
            "ok": True,
            "compliance_status": status,
            "total_issues": len(issues),
            "high_severity": high,
            "issues": issues,
            "checked_rules": ["金额合理性", "必填字段", "合同类型", "付款条款", "管辖地"],
        }
