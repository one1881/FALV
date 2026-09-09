"""
Template MCP Server - 合同模板管理 + Jinja2 渲染
MCP 工具:
- list_templates: 列出所有可用模板
- get_template:   按 ID 获取模板原文
- render_template:Jinja2 渲染(返回最终合同正文)
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
import logging

from jinja2 import Template, Environment, BaseLoader
from app.mcps.base_server import BaseMCPServer

logger = logging.getLogger(__name__)


# 模板库(从 data_collector_agent 迁移过来集中管理)
TEMPLATE_LIBRARY: Dict[str, Dict[str, str]] = {
    "采购合同": {
        "template_id": "TPL-CGHT-001",
        "template_name": "采购合同标准模板",
        "version": "1.0",
        "category": "购销",
        "content": (
            "甲方(采购方): {{甲方名称}}\n"
            "乙方(供应方): {{乙方名称}}\n\n"
            "根据《中华人民共和国民法典》及相关法律法规,甲乙双方就采购事宜达成如下协议:\n\n"
            "第一条 采购标的\n"
            "乙方向甲方提供以下产品/服务: {{采购标的}}\n\n"
            "第二条 合同金额\n"
            "合同总金额为人民币 {{合同金额}} 元(大写: {{金额大写}})\n\n"
            "第三条 付款方式\n"
            "{{付款条款}}\n\n"
            "第四条 交付安排\n"
            "{{交付计划}}\n\n"
            "第五条 质量保证\n"
            "乙方保证提供的产品/服务符合国家标准和行业规范。\n\n"
            "第六条 违约责任\n"
            "任何一方违约,应承担相应法律责任并赔偿对方损失。\n\n"
            "第七条 争议解决\n"
            "因本合同引起的争议,双方应友好协商解决;协商不成的,提交{{管辖法院}}诉讼解决。\n\n"
            "甲方(盖章): _______________  日期: _______________\n"
            "乙方(盖章): _______________  日期: _______________\n"
        ),
    },
    "销售合同": {
        "template_id": "TPL-XSHT-001",
        "template_name": "销售合同标准模板",
        "version": "1.0",
        "category": "购销",
        "content": (
            "销售合同\n\n"
            "甲方(销售方): {{甲方名称}}\n"
            "乙方(购买方): {{乙方名称}}\n\n"
            "第一条 销售标的: {{销售标的}}\n"
            "第二条 合同金额: 人民币 {{合同金额}} 元\n"
            "第三条 付款方式: {{付款条款}}\n"
            "第四条 交付安排: {{交付计划}}\n"
            "第五条 违约责任: 依据《中华人民共和国民法典》相关规定处理\n\n"
            "甲方签字: _______________  乙方签字: _______________\n"
        ),
    },
    "服务合同": {
        "template_id": "TPL-FWHT-001",
        "template_name": "服务合同标准模板",
        "version": "1.0",
        "category": "服务",
        "content": (
            "服务合同\n\n"
            "甲方(委托方): {{甲方名称}}\n"
            "乙方(服务方): {{乙方名称}}\n\n"
            "第一条 服务内容: {{服务内容}}\n"
            "第二条 服务费用: 人民币 {{合同金额}} 元\n"
            "第三条 付款方式: {{付款条款}}\n"
            "第四条 服务期限: {{服务期限}}\n\n"
            "甲方签字: _______________  乙方签字: _______________\n"
        ),
    },
    "劳动合同": {
        "template_id": "TPL-LDHT-001",
        "template_name": "劳动合同标准模板",
        "version": "1.0",
        "category": "劳动",
        "content": (
            "劳动合同\n\n"
            "甲方(用人单位): {{甲方名称}}\n"
            "乙方(劳动者): {{乙方名称}}\n\n"
            "第一条 合同期限: {{合同期限}}\n"
            "第二条 工作内容: {{工作岗位}}\n"
            "第三条 劳动报酬: 人民币 {{合同金额}} 元/月\n"
            "第四条 工作时间与休息休假按国家规定执行\n"
            "第五条 社会保险与福利按国家规定执行\n"
        ),
    },
    "租赁合同": {
        "template_id": "TPL-ZLHT-001",
        "template_name": "租赁合同标准模板",
        "version": "1.0",
        "category": "租赁",
        "content": (
            "租赁合同\n\n"
            "出租人(甲方): {{甲方名称}}\n"
            "承租人(乙方): {{乙方名称}}\n\n"
            "第一条 租赁标的: {{租赁标的}}\n"
            "第二条 租赁期限: {{租赁期限}}\n"
            "第三条 租金: 人民币 {{合同金额}} 元\n"
            "第四条 付款方式: {{付款条款}}\n"
        ),
    },
    "保密协议": {
        "template_id": "TPL-BSXY-001",
        "template_name": "保密协议标准模板",
        "version": "1.0",
        "category": "知识产权",
        "content": (
            "保密协议\n\n"
            "披露方(甲方): {{甲方名称}}\n"
            "接收方(乙方): {{乙方名称}}\n\n"
            "第一条 保密信息范围\n"
            "第二条 保密期限: {{保密期限}}\n"
            "第三条 违约责任\n"
            "第四条 争议解决\n"
        ),
    },
    "起诉状": {
        "template_id": "TPL-QSZ-001",
        "template_name": "民事起诉状标准模板",
        "version": "1.0",
        "category": "诉讼文书",
        "content": (
            "民事起诉状\n\n"
            "原告：{{原告名称}}\n"
            "被告：{{被告名称}}\n\n"
            "诉讼请求：\n"
            "{{诉讼请求}}\n\n"
            "事实与理由：\n"
            "{{事实与理由}}\n\n"
            "证据清单：\n"
            "{{证据清单}}\n\n"
            "此致\n"
            "{{管辖法院}}\n\n"
            "具状人：{{原告名称}}\n"
            "日期：____年__月__日\n"
        ),
    },
    "答辩状": {
        "template_id": "TPL-DBZ-001",
        "template_name": "民事答辩状标准模板",
        "version": "1.0",
        "category": "诉讼文书",
        "content": (
            "民事答辩状\n\n"
            "答辩人：{{答辩人名称}}\n"
            "被答辩人：{{被答辩人名称}}\n\n"
            "答辩人就{{案由}}一案，提出答辩如下：\n\n"
            "答辩意见：\n"
            "{{答辩意见}}\n\n"
            "事实与理由：\n"
            "{{事实与理由}}\n\n"
            "证据清单：\n"
            "{{证据清单}}\n\n"
            "此致\n"
            "{{管辖法院}}\n\n"
            "答辩人：{{答辩人名称}}\n"
            "日期：____年__月__日\n"
        ),
    },
}


class TemplateServer(BaseMCPServer):
    """合同模板 MCP server"""

    def __init__(self):
        super().__init__(name="template_server", description="合同模板库与 Jinja2 渲染")

        self.register_tool(
            name="list_templates",
            description="列出所有可用合同模板(类型、ID、版本)",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=self._list_templates,
        )
        self.register_tool(
            name="get_template",
            description="根据合同类型获取模板(ID + 原文),contract_type 取值如 '销售合同'/'采购合同'/'服务合同'/'劳动合同'/'租赁合同'/'保密协议'",
            input_schema={
                "type": "object",
                "properties": {"contract_type": {"type": "string"}},
                "required": ["contract_type"],
            },
            handler=self._get_template,
        )
        self.register_tool(
            name="render_template",
            description="用 Jinja2 渲染模板(把变量填进 {{变量}} 占位符),返回最终合同正文文本",
            input_schema={
                "type": "object",
                "properties": {
                    "contract_type": {"type": "string"},
                    "variables": {"type": "object"},
                },
                "required": ["contract_type", "variables"],
            },
            handler=self._render_template,
        )

    async def _list_templates(self) -> Dict[str, Any]:
        items = [
            {"contract_type": k, **v} for k, v in TEMPLATE_LIBRARY.items()
        ]
        return {"ok": True, "count": len(items), "templates": items}

    async def _get_template(self, contract_type: str) -> Dict[str, Any]:
        tpl = TEMPLATE_LIBRARY.get(contract_type)
        if not tpl:
            return {
                "ok": False,
                "error": f"未找到合同类型 [{contract_type}],可用类型: {list(TEMPLATE_LIBRARY.keys())}",
                "template_id": None,
                "template_content": "",
            }
        return {
            "ok": True,
            "template_id": tpl["template_id"],
            "template_name": tpl["template_name"],
            "version": tpl["version"],
            "category": tpl["category"],
            "template_content": tpl["content"],
        }

    async def _render_template(self, contract_type: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        tpl = TEMPLATE_LIBRARY.get(contract_type)
        if not tpl:
            return {"ok": False, "error": f"未找到合同类型 [{contract_type}]", "rendered": ""}
        try:
            env = Environment(loader=BaseLoader())
            tmpl = env.from_string(tpl["content"])
            rendered = tmpl.render(**(variables or {}))
            return {
                "ok": True,
                "rendered": rendered,
                "template_id": tpl["template_id"],
                "variables_used": list((variables or {}).keys()),
            }
        except Exception as e:
            return {"ok": False, "error": f"渲染失败: {e}", "rendered": ""}
