"""快速合同起草服务 - 绕过 deepagents 和 A2A 的轻量级实现

适用场景：
- 有现成模板的标准合同
- 无需复杂工具调用和多步推理
- 目标：60秒内完成起草

设计原则：
- 启动时创建 LLM 客户端（全局复用，避免重复初始化）
- 模板预加载到内存
- 直接调用大模型，无中间层
- prompt 工程：一次性生成完整合同
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional

from langchain_openai import ChatOpenAI
from jinja2 import Template

from app.core.config import get_settings
from app.core.net import proxy_immune_clients
from app.mcps.servers.template_server import TEMPLATE_LIBRARY

logger = logging.getLogger(__name__)
settings = get_settings()


class FastDraftingService:
    """快速合同起草服务：模板 + 大模型，60秒完成"""

    def __init__(self):
        """初始化服务（启动时调用一次，全局复用）"""
        # 创建 LLM 客户端（复用连接池）。
        # http_client / http_async_client 必须显式传入：SDK 默认 trust_env=True，
        # 会把请求绕经注入型代理（HTTP_PROXY=127.0.0.1:8279）挂死。见 app/core/net.py。
        _sync_http, _async_http = proxy_immune_clients(90)
        self._llm = ChatOpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_API_URL,
            model=settings.DRAFT_REVIEW_MODEL,
            temperature=0.1,  # 合同起草需要稳定输出
            timeout=90,  # 90秒超时足够生成合同
            max_retries=1,  # 最多重试1次
            http_client=_sync_http,
            http_async_client=_async_http,
        )

        # 预加载模板
        self._templates = TEMPLATE_LIBRARY

        logger.info(
            f"[FastDrafting] 初始化完成: model={settings.DRAFT_REVIEW_MODEL}, "
            f"templates={len(self._templates)}"
        )

    async def draft_contract(
        self,
        contract_type: str,
        customer_name: str,
        amount: float,
        requirements: str = "",
        industry: str = "通用",
        jurisdiction: str = "中国",
        materials_text: str = "",
        **extra_context
    ) -> Dict[str, Any]:
        """
        快速起草合同

        Args:
            contract_type: 合同类型（如"采购合同"、"劳动合同"）
            customer_name: 客户/对方名称
            amount: 合同金额
            requirements: 特殊要求
            industry: 行业
            jurisdiction: 管辖地
            materials_text: 附加材料文本
            **extra_context: 其他上下文信息

        Returns:
            {
                "content": "合同正文",
                "summary": "合同摘要",
                "template_used": "模板ID",
                "generation_time": 耗时秒数,
                "model": "使用的模型"
            }

        Raises:
            ValueError: 参数错误
            Exception: 生成失败
        """
        start = time.time()

        # 参数校验
        if not contract_type or not customer_name:
            raise ValueError("合同类型和客户名称不能为空")

        # 1. 获取模板（< 1秒）
        template_info = self._templates.get(contract_type)
        if not template_info:
            logger.warning(f"[FastDrafting] 未找到模板 [{contract_type}]，使用采购合同模板兜底")
            template_info = self._templates.get("采购合同")
            if not template_info:
                raise ValueError(f"未找到合同类型 [{contract_type}] 的模板")

        template_content = template_info["content"]
        template_id = template_info["template_id"]

        # 2. 构建 prompt（< 1秒）
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            contract_type=contract_type,
            template_content=template_content,
            customer_name=customer_name,
            amount=amount,
            requirements=requirements,
            industry=industry,
            jurisdiction=jurisdiction,
            materials_text=materials_text,
        )

        # 3. 调用大模型生成（主要耗时：40-60秒）
        logger.info(
            f"[FastDrafting] 开始生成: type={contract_type}, "
            f"customer={customer_name}, amount={amount}"
        )

        try:
            response = await self._llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])

            content = response.content.strip()

            # 基本校验：确保生成了足够的内容
            if len(content) < 200:
                logger.warning(f"[FastDrafting] 生成内容过短: {len(content)}字符")
                raise ValueError("生成的合同内容过短，可能生成失败")

            # 4. 生成摘要（简化版，避免额外耗时）
            summary = self._generate_summary(
                contract_type=contract_type,
                customer_name=customer_name,
                amount=amount,
            )

            elapsed = time.time() - start

            logger.info(
                f"[FastDrafting] 生成完成: 耗时 {elapsed:.2f}秒, "
                f"内容长度 {len(content)}字符"
            )

            return {
                "content": content,
                "summary": summary,
                "template_used": template_id,
                "generation_time": round(elapsed, 2),
                "model": settings.DRAFT_REVIEW_MODEL,
                "contract_type": contract_type,
                "customer_name": customer_name,
                "amount": amount,
            }

        except Exception as e:
            elapsed = time.time() - start
            logger.error(
                f"[FastDrafting] 生成失败: {e}, 耗时 {elapsed:.2f}秒"
            )
            raise

    def _build_system_prompt(self) -> str:
        """构建系统 prompt"""
        return """你是专业的合同起草助手，精通中国合同法和各类商业合同。

你的任务：
1. 根据提供的模板和实际信息，生成完整的合同正文
2. 严格遵循模板的结构和条款顺序
3. 用实际信息填充所有变量（如甲方、乙方、金额等）
4. 保持专业的法律用语和严谨的表述
5. 如有特殊要求，在相应条款中合理体现

输出要求：
- 直接输出完整的合同正文
- 不要输出"好的"、"让我来"等开场白
- 不要输出思考过程和解释说明
- 不要使用 markdown 格式（如 ```、**等）
- 确保所有变量都已填充，不留空白占位符"""

    def _build_user_prompt(
        self,
        contract_type: str,
        template_content: str,
        customer_name: str,
        amount: float,
        requirements: str,
        industry: str,
        jurisdiction: str,
        materials_text: str,
    ) -> str:
        """构建用户 prompt"""

        # 格式化金额
        amount_str = f"{amount:,.2f}"
        amount_cn = self._number_to_chinese(amount)

        prompt = f"""请基于以下模板生成一份{contract_type}：

【模板参考】
{template_content}

【实际信息】
- 甲方（我方）：[公司名称待填]
- 乙方（对方）：{customer_name}
- 合同金额：{amount_str} 元（大写：{amount_cn}）
- 行业领域：{industry}
- 管辖地：{jurisdiction}
"""

        # 添加特殊要求
        if requirements and requirements.strip():
            prompt += f"\n【特殊要求】\n{requirements.strip()}\n"

        # 添加附加材料
        if materials_text and materials_text.strip():
            prompt += f"\n【附加材料】\n{materials_text.strip()}\n"

        prompt += """
【输出要求】
请直接输出完整的合同正文，确保：
1. 所有变量都已填充（甲方、乙方、金额等）
2. 条款完整、逻辑严密
3. 符合中国法律规范
4. 直接输出合同内容，不要任何解释"""

        return prompt

    def _generate_summary(
        self,
        contract_type: str,
        customer_name: str,
        amount: float,
    ) -> str:
        """生成合同摘要（简化版，避免调用大模型）"""
        amount_str = f"{amount:,.2f}"
        return f"{contract_type} - 乙方：{customer_name} - 金额：{amount_str}元"

    def _number_to_chinese(self, num: float) -> str:
        """数字转中文大写（金额）

        简化实现，仅支持常见金额范围
        """
        if num == 0:
            return "零元整"

        # 简化处理：小于1亿的金额
        if num >= 100000000:
            return f"大写金额：{num:,.2f}元"  # 超大金额直接返回数字

        units = ["", "拾", "佰", "仟", "万", "拾", "佰", "仟"]
        digits = "零壹贰叁肆伍陆柒捌玖"

        int_part = int(num)
        dec_part = int((num - int_part) * 100)

        # 转换整数部分
        result = ""
        str_int = str(int_part)
        length = len(str_int)

        for i, digit in enumerate(str_int):
            if digit != "0":
                result += digits[int(digit)] + units[length - i - 1]
            elif i < length - 1 and str_int[i + 1] != "0":
                result += "零"

        result += "元"

        # 转换小数部分
        if dec_part > 0:
            jiao = dec_part // 10
            fen = dec_part % 10
            if jiao > 0:
                result += digits[jiao] + "角"
            if fen > 0:
                result += digits[fen] + "分"
        else:
            result += "整"

        return result


# 全局单例（启动时创建，避免重复初始化）
_fast_drafting_service: Optional[FastDraftingService] = None


def get_fast_drafting_service() -> FastDraftingService:
    """获取快速起草服务单例"""
    global _fast_drafting_service
    if _fast_drafting_service is None:
        _fast_drafting_service = FastDraftingService()
    return _fast_drafting_service
