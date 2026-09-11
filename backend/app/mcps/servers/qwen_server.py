from __future__ import annotations

import json
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.mcps.base_server import BaseMCPServer


class QwenServer(BaseMCPServer):
    @staticmethod
    def _chat_url() -> str:
        """QWEN_API_URL 允许配裸 base URL（/compatible-mode/v1），自动补 /chat/completions。"""
        base = settings.QWEN_API_URL.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def __init__(self):
        super().__init__(name="qwen_server", description="Qwen 证据理解和关键信息抽取 MCP Server")
        self.register_tool(
            name="extract_key_info",
            description="根据材料类型和解析结果提取关键信息、证明目的和确认项",
            input_schema={"type": "object", "properties": {"material_type": {"type": "string"}, "content": {"type": "string"}, "parser_result": {"type": "object"}}, "required": ["material_type"]},
            handler=self._extract_key_info,
        )
        self.register_tool(
            name="assess_acceptance",
            description="基于证据目录、时间线和确认结果生成受理评估",
            input_schema={"type": "object", "properties": {"context": {"type": "object"}}, "required": ["context"]},
            handler=self._assess_acceptance,
        )

    async def _extract_key_info(self, material_type: str, content: str = "", parser_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parser_result = parser_result or {}
        prompt = self._build_extract_prompt(material_type, content, parser_result)
        if not settings.QWEN_API_URL:
            return self._fallback_extract(material_type, content, parser_result)
        try:
            payload = {
                "model": settings.QWEN_MODEL,
                "messages": [
                    {"role": "system", "content": "你是法律证据分析助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }
            headers = {"Authorization": f"Bearer {settings.QWEN_API_KEY}", "Content-Type": "application/json"} if settings.QWEN_API_KEY else {"Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self._chat_url(), headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content_text = self._extract_message_content(data)
            parsed = self._loads_json(content_text)
            return {"provider": "qwen", "mode": "api", **parsed, "raw": data}
        except Exception as exc:
            return {**self._fallback_extract(material_type, content, parser_result), "error": f"Qwen 调用失败：{type(exc).__name__}: {exc}"}

    async def _assess_acceptance(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = "请基于以下案件证据上下文输出 JSON：recommendation、risk_level、missing_materials、next_steps、reasoning。\n" + json.dumps(context, ensure_ascii=False)
        if not settings.QWEN_API_URL:
            return {
                "provider": "qwen",
                "mode": "fallback",
                "recommendation": "可预受理，需补充材料",
                "risk_level": "中",
                "missing_materials": ["主体信息", "金额证明", "催告记录"],
                "next_steps": ["逐块确认 AI 分析结果", "补齐缺失证据", "确认入库后进入诉讼策略"],
                "reasoning": "Qwen API 未配置，使用规则回退评估。",
            }
        try:
            payload = {
                "model": settings.QWEN_MODEL,
                "messages": [
                    {"role": "system", "content": "你是法律案件受理评估助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }
            headers = {"Authorization": f"Bearer {settings.QWEN_API_KEY}", "Content-Type": "application/json"} if settings.QWEN_API_KEY else {"Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self._chat_url(), headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return {"provider": "qwen", "mode": "api", **self._loads_json(self._extract_message_content(data)), "raw": data}
        except Exception as exc:
            return {"provider": "qwen", "mode": "fallback", "recommendation": "可预受理，需补充材料", "risk_level": "中", "missing_materials": ["Qwen 评估失败，请人工复核"], "next_steps": ["人工复核证据", "补齐材料"], "reasoning": str(exc)}

    def _build_extract_prompt(self, material_type: str, content: str, parser_result: Dict[str, Any]) -> str:
        audio_rule = ""
        if material_type == "audio":
            audio_rule = (
                "音频材料补充约定：解析结构中若含 asr_segments（带时间戳与说话人编号的分段转写），"
                "请基于各说话人的言语内容推断其角色身份（如\"疑似债权人\"\"疑似客服\"\"疑似办案人员\"\"身份不明\"），"
                "在输出中增加 speaker_roles 字段：[{\"speaker\": \"说话人1\", \"role\": \"疑似…\", \"依据\": \"对应的关键话语摘要\"}]。"
                "角色判断是 AI 推断，仅供律师参考，每个 role 前必须带\"疑似\"字样；"
                "若有多个说话人，summary 中可指明关键承诺/事实出自哪个说话人及其说话时间点。"
                "另必须输出 key_moments 字段（重要内容筛选）：从 asr_segments 中只挑出**能对案件定性**的片段"
                "（承诺/承认/否认、金额、日期期限、威胁恐吓、催告、身份信息、关键抗辩等），"
                "寒暄、语气词、无信息量的过场对话一律丢弃，宁缺毋滥；"
                "每条格式 {\"time\": \"mm:ss\", \"speaker\": \"说话人N\", \"text\": \"原话摘录\", \"why\": \"一句话说明为什么关键\"}，"
                "time 使用该片段自带的时间戳；没有关键片段时输出空数组，禁止编造不存在的语句。"
            )
        return "\n".join([
            "请分析以下证据材料，输出严格 JSON，字段包括：document_type、summary、key_info、proof_purpose、risk_notes、need_confirm、useful、evidence_level。",
            "字段约定：useful 为布尔值，表示该证据对己方是否有利（true=有利，false=不利）；evidence_level 取值仅限 A/B/C（A=证明力强，B=证明力中等，C=证明力弱或需补证）。",
            "key_info 约定（重要）：必须输出非空对象，结构为 {\"人物\": [\"提及的人名/称呼\"], \"机构/地点\": [\"出现的机构、场所、地点\"], \"金额\": [\"提及的金额\"], \"日期时间\": [\"提及的日期/时间\"], \"关键事实/承诺\": [\"关键事实、承诺或约定\"]}。各列表按材料实际内容填写，没有的留空数组，但至少一个列表非空。",
            "summary 约定（重要）：用一句话凝练概括该材料证明的核心事实，30~90 个汉字，律师可直接引用。风格参照：'该收据证明曾小伟于2023年11月15日至17日入住汉庭酒店人民广场店402房并已结清'、'该聊天记录显示被告承诺于2026年4月底归还借款10万元'。禁止使用 markdown 标题（###）、禁止分点（-）、禁止写'人物与物体'这类栏目式清单，详细的人物/物体/动作/时间清单全部放进 key_info。",
            audio_rule,
            f"材料类型：{material_type}",
            f"解析文本：{content[:6000]}",
            "解析结构：" + json.dumps(parser_result, ensure_ascii=False)[:6000],
        ])

    def _extract_message_content(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            return message.get("content") or choices[0].get("text") or "{}"
        return data.get("content") or data.get("text") or json.dumps(data, ensure_ascii=False)

    def _loads_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("not a dict")
            return parsed
        except Exception:
            return {"summary": text, "key_info": {}, "proof_purpose": "待人工确认", "risk_notes": [], "need_confirm": [], "useful": None, "evidence_level": "C"}

    def _fallback_extract(self, material_type: str, content: str, parser_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": "qwen",
            "mode": "fallback",
            "document_type": parser_result.get("document_type") or material_type,
            "summary": content[:300] or parser_result.get("summary") or "待解析内容",
            "key_info": parser_result.get("key_info") or {"待确认字段": "主体、金额、日期、承诺、证明目的"},
            "proof_purpose": parser_result.get("proof_purpose") or "证明案件相关事实，需律师确认。",
            "risk_notes": ["Qwen API 未配置，当前为规则回退结果。"],
            "need_confirm": ["全文是否准确", "关键信息是否可采", "证明目的是否成立"],
            "useful": parser_result.get("useful", True),
            "evidence_level": parser_result.get("evidence_level", "C"),
        }
