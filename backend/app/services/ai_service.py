import logging
import httpx
from openai import OpenAI
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AIService:
    """AI服务类，用于合同分析

    注意：OpenAI 同步客户端在 async 路由里直接调用会阻塞整个 FastAPI 事件循环
    （单次调用最长 timeout+retries，期间所有请求全部冻结）。因此：
    1. 客户端必须设 timeout 和 max_retries，禁止用 SDK 默认值（600s×3 次）；
    2. async 链路请用 *_async 包装方法（线程池执行），不要直接调同步方法。
    """

    # 强制 trust_env=False：不读 HTTP_PROXY/HTTPS_PROXY，避免沙箱/工具进程注入的
    # 本地代理（127.0.0.1:8279）把 DashScope 模型请求绕死（根因修复 2026-09-10）。
    _HTTP_TIMEOUT = httpx.Timeout(120.0, connect=20.0)

    def __init__(self):
        self._http_client = httpx.Client(trust_env=False, timeout=self._HTTP_TIMEOUT)
        self.client = OpenAI(
            api_key=settings.primary_llm_api_key,
            base_url=self._normalize_base_url(settings.primary_llm_api_url),
            timeout=120,
            max_retries=1,
            http_client=self._http_client,
        )
        # 多模态视觉客户端（Qwen-VL，用于视频/图片画面理解）
        self.vl_client = None
        if settings.QWEN_VL_API_KEY:
            try:
                base_url = self._normalize_base_url(settings.QWEN_VL_API_URL)
                self.vl_client = OpenAI(
                    api_key=settings.QWEN_VL_API_KEY,
                    base_url=base_url,
                    timeout=120,
                    max_retries=1,
                    http_client=self._http_client,
                )
            except Exception as e:
                logger.error(f"Qwen-VL 客户端初始化失败: {e}")

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """统一 OpenAI 兼容端点 base_url。

        OpenAI SDK 会自动拼 /chat/completions，因此若配置里写了完整 chat 端点
        （如 https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions），
        需去掉末尾 /chat/completions，保留 /v1 前缀。
        """
        base = (url or "").strip().rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        return base or "https://api.deepseek.com"

    def _json_chat(
        self,
        messages: list,
        max_tokens: int = 3000,
        purpose: str = "json_chat",
        attempts: int = 3,
    ) -> dict:
        """要求模型返回 JSON 的健壮调用。

        解决两类线上失败：
        1. 输出被 max_tokens 截断 → json.loads 抛 "Unterminated string"。
           原实现把 json.loads 放在重试循环之外，一次截断即彻底失败。
           这里把解析纳入重试，并在检测到截断时逐次放大 token 预算。
        2. 推理模型偶发返回空 content → 继续重试。

        Returns:
            {"ok": True, "data": dict} 或 {"ok": False, "error": str}
        """
        import json
        import time

        last_error = "DeepSeek 返回空内容"
        budget = max_tokens
        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=settings.primary_llm_model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=budget,
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                content = (choice.message.content or "").strip()
                truncated = choice.finish_reason == "length"

                if not content:
                    last_error = f"DeepSeek 返回空内容（第{attempt + 1}次）"
                    budget = min(int(budget * 1.5), 8000)
                elif truncated:
                    last_error = f"DeepSeek 输出被截断，max_tokens={budget}（第{attempt + 1}次）"
                    budget = min(int(budget * 2), 8000)
                else:
                    try:
                        return {"ok": True, "data": json.loads(content)}
                    except ValueError as exc:
                        # 未被标记截断但仍解析失败，多为内容不完整，放大预算重试
                        last_error = f"JSON 解析失败: {exc}"
                        budget = min(int(budget * 2), 8000)
            except Exception as exc:
                last_error = str(exc)
            if attempt < attempts - 1:
                time.sleep(1)

        logger.error(f"{purpose} 调用失败: {last_error}")
        return {"ok": False, "error": last_error}

    def apply_clause_revision(
        self,
        paragraph: str,
        description: str,
        suggestion: str,
        legal_basis: str = "",
    ) -> dict:
        """按审核建议改写单个合同条款段落（同步实现，async 链路须走线程池调用）。

        Returns:
            {"ok": True, "revised": 改写后段落} 或 {"ok": False, "error": str}
        """
        system = (
            "你是资深合同起草律师。任务：根据审核意见，改写给定的合同条款段落。"
            "硬约束：1) 只做与审核意见直接相关的最小必要修改，其余文字原样保留；"
            "2) 保留原段落的条款编号与格式；3) 修改不得引入新的事实（金额、数量、日期等"
            "若审核意见给出选项，选择更符合律师惯例的一种并直接写入）；"
            "4) 原文可能含 Markdown 标记（## 标题、**加粗**、|表格行|），必须原样保留这些"
            "标记与表格结构，不得增删星号或井号；"
            "5) 若审核意见是跨条款矛盾，只修改本段落一侧的表述，不要重述另一条款的内容；"
            '6) 只输出 JSON：{"revised": "改写后的完整段落"}。'
        )
        user = (
            f"【合同条款段落】\n{paragraph}\n\n"
            f"【问题描述】\n{description}\n\n"
            f"【法律依据】\n{legal_basis or '无'}\n\n"
            f"【修改建议】\n{suggestion}\n"
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        call = self._json_chat(messages, max_tokens=2000, purpose="合同条款一键修改")
        if not call.get("ok"):
            return call
        revised = str(call.get("data", {}).get("revised") or "").strip()
        if not revised:
            return {"ok": False, "error": "模型未返回改写后的段落"}
        return {"ok": True, "revised": revised, "unchanged": revised == paragraph.strip()}

    def describe_image(self, image_base64: str, prompt: str = "", mime: str = "image/jpeg") -> dict:
        """用 Qwen-VL 理解一张图片/视频帧的画面内容。

        Args:
            image_base64: 图片的 base64 编码（不含 data: 前缀）
            prompt: 描述要求（默认让模型简洁描述画面里的人/动作/场景）
            mime: 图片 MIME 类型

        Returns:
            {"success": True, "description": "..."} 或 {"success": False, "error": "..."}
        """
        return self._call_vl([image_base64], [mime], prompt or self._default_image_prompt(), max_tokens=1200)

    def describe_video_frames(
        self,
        frames_base64: list[str],
        yolo_objects_summary: str,
        file_name: str = "",
        max_frames: int = 6,
    ) -> dict:
        """用 Qwen-VL(qwen3.8-27b) 对视频多帧做二次语义摘要。

        链路：YOLO 抽帧 + 对象检测 → 把代表帧 + 对象统计 → 喂 Qwen-VL 输出结构化 JSON。
        修复点：之前 video 分支只回 YOLO 的保底 summary（"视频中出现人员活动"），
        这里把 YOLO 结果带上去生成真实视频叙事 + 证据等级判定。

        Returns:
            {"ok": True, "data": {"summary","detailed","key_info","proof_purpose",
             "risk_notes","need_confirm","evidence_level"}} 或
            {"ok": False, "error": "..."}
        """
        if not frames_base64:
            return {"ok": False, "error": "frames_base64 为空"}
        # 帧过多截断到 max_frames，等距抽样
        if len(frames_base64) > max_frames:
            step = len(frames_base64) / max_frames
            idx = [int(i * step) for i in range(max_frames)]
            frames_base64 = [frames_base64[i] for i in idx]

        prompt = (
            f"你是中国法律案件的证据分析助手。当前是一段视频证据（{file_name or 'video.mp4'}），"
            f"已经由 YOLO 检测出以下对象统计：\n\n{yolo_objects_summary or '（YOLO 无对象输出）'}\n\n"
            f"以下是视频的 {len(frames_base64)} 个代表性抽帧（按时间顺序）。请基于这些帧和对象检测结果，"
            "用严格 JSON 输出（不要任何多余文字、不要 markdown 围栏）：\n"
            '{"summary":"一句话概括该视频证明的核心事实（结合帧画面+对象检测，避免套话）",'
            '"detailed":"120-260字详细描述：按时间顺序叙述每个时间段的画面内容、人物/车辆/物品/动作/场景，每段时间标注秒数",'
            '"key_info":{"人物":[],"机构/地点":[],"物品/对象":[],"金额":[],"日期时间":[],'
            '"可见文字/关键承诺":[],"关键事实":[]},'
            '"proof_purpose":"该证据能证明的法律事实（一句 30-80 字）",'
            '"risk_notes":["该证据的局限性或需交叉验证的点"],'
            '"need_confirm":["律师需要进一步确认的事实/时间/地点/主体"],'
            '"key_moments":[{"time":"mm:ss","speaker":"说话人N（纯画面事件填空字符串）","text":"原话摘录或画面关键行为描述","why":"一句话说明为什么关键"}],'
            '"evidence_level":"A/B/C 三档之一"}'
            "\nkey_info 各列表按视频实际内容填写，没有的留空数组但至少一个非空。"
            "\nkey_moments 为重要内容筛选：若上下文含音频转写，只挑出**能对案件定性**的语音片段"
            "（承诺/承认/否认、金额、日期期限、威胁恐吓、催告、身份信息、关键抗辩等），"
            "寒暄、语气词、无信息量的过场对话一律丢弃，宁缺毋滥；time 使用转写自带的时间戳，"
            "speaker 按转写标注填写；画面中的关键行为（如肢体冲突、物品交付、损毁动作）也可纳入，"
            "time 按该画面所在的时间段估计；没有关键内容时输出空数组，禁止编造不存在的语句。"
            "evidence_level 判定标准：A=直接证明案件关键事实；B=辅助证明背景经过；C=仅供线索参考。"
        )
        return self._call_vl_json(frames_base64, ["image/jpeg"] * len(frames_base64), prompt)

    # ---------- 异步包装：同步 OpenAI 调用丢进线程池，避免阻塞事件循环 ----------

    async def describe_image_async(self, image_base64: str, prompt: str = "", mime: str = "image/jpeg") -> dict:
        import asyncio
        return await asyncio.to_thread(self.describe_image, image_base64, prompt, mime)

    async def describe_video_frames_async(self, frames_base64: list, yolo_objects_summary: str, file_name: str = "", max_frames: int = 6) -> dict:
        import asyncio
        return await asyncio.to_thread(self.describe_video_frames, frames_base64, yolo_objects_summary, file_name, max_frames)

    def _default_image_prompt(self) -> str:
        return (
            "这是法律案件证据视频的一帧。请用中文简洁描述：画面里有什么人、在做什么动作、"
            "什么场景，以及可能的证据意义。控制在80字内。"
        )

    def _call_vl(self, images_base64: list[str], mimes: list[str], prompt: str, max_tokens: int = 1200) -> dict:
        """统一多模态调用（多图模式）。images_base64/mimes 同长度。"""
        if not self.vl_client:
            return {"success": False, "error": "QWEN_VL_API_KEY 未配置"}
        content = []
        for img_b64, mime in zip(images_base64, mimes):
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}})
        content.append({"type": "text", "text": prompt})
        try:
            response = self.vl_client.chat.completions.create(
                model=settings.QWEN_VL_MODEL,
                messages=[{"role": "user", "content": content}],
                temperature=0.1,
                max_tokens=max_tokens,
            )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                return {"success": False, "error": "Qwen-VL 返回空内容"}
            return {"success": True, "description": text, "source": "qwen_vl.describe_image"}
        except Exception as e:
            logger.error(f"Qwen-VL 调用失败: {e}")
            return {"success": False, "error": str(e)}

    def _call_vl_json(self, images_base64: list[str], mimes: list[str], prompt: str) -> dict:
        """多模态 JSON 调用。要求模型返回严格 JSON（response_format=json_object）。"""
        import json
        import time

        if not self.vl_client:
            return {"ok": False, "error": "QWEN_VL_API_KEY 未配置"}
        content = []
        for img_b64, mime in zip(images_base64, mimes):
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}})
        content.append({"type": "text", "text": prompt})
        last_error = "Qwen-VL 返回空内容"
        budget = 1800
        for attempt in range(3):
            try:
                response = self.vl_client.chat.completions.create(
                    model=settings.QWEN_VL_MODEL,
                    messages=[{"role": "user", "content": content}],
                    temperature=0.1,
                    max_tokens=budget,
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                text = (choice.message.content or "").strip()
                truncated = choice.finish_reason == "length"
                if not text:
                    last_error = f"Qwen-VL 返回空内容（第{attempt + 1}次）"
                    budget = min(int(budget * 1.5), 4000)
                elif truncated:
                    last_error = f"Qwen-VL 输出被截断, max_tokens={budget}（第{attempt + 1}次）"
                    budget = min(int(budget * 2), 4000)
                else:
                    try:
                        return {"ok": True, "data": json.loads(text)}
                    except ValueError as exc:
                        last_error = f"JSON 解析失败: {exc}"
                        budget = min(int(budget * 2), 4000)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(1)
        return {"ok": False, "error": last_error}

    def assess_case_acceptance(self, case_info: dict, materials_summary: str = "") -> dict:
        """用 LLM 对案件做「受理分析」：受理建议、风险、缺失材料、案由、管辖、策略。

        Args:
            case_info: 案件信息 {customer_name, opposite_party, dispute_amount, case_title, case_summary, claims}
            materials_summary: 已确认材料的摘要拼接（每份材料一句话 + 关键事实）

        Returns:
            {"success": True, "recommendation": ..., "risk_level": ..., "missing_materials": [...],
             "cause": {...}, "jurisdiction": {...}, "strategy_summary": ..., "next_steps": [...]}
            失败返回 {"success": False, "error": "..."}，调用方降级为规则兜底。
        """
        import json
        import time
        import hashlib
        from app.services.cache_service import get_cache
        cache_key = "assess:" + hashlib.md5(
            (json.dumps(case_info, ensure_ascii=False, sort_keys=True) + "|" + (materials_summary or "")).encode("utf-8")
        ).hexdigest()
        cached = get_cache().get(cache_key)
        if isinstance(cached, dict) and cached.get("success"):
            return {**cached, "source": "cache"}
        try:
            claims = case_info.get("claims") or []
            claims_text = "\n".join(f"- {c}" for c in claims) or "（未填写）"
            user_prompt = (
                "你是一名执业律师，请对下面这个待受理的案件做一次专业的受理分析，"
                "严格只输出合法 JSON，不要任何解释、不要 Markdown 代码块。\n\n"
                "【案件信息】\n"
                f"客户/原告：{case_info.get('customer_name') or '未提供'}\n"
                f"对方/被告：{case_info.get('opposite_party') or '未提供'}\n"
                f"争议金额：{case_info.get('dispute_amount') or '未提供'}\n"
                f"案件标题：{case_info.get('case_title') or '未提供'}\n"
                f"案情摘要：{case_info.get('case_summary') or '未提供'}\n"
                f"诉讼请求：\n{claims_text}\n\n"
                "【已确认的证据材料摘要】\n"
                f"{materials_summary or '（暂无已确认材料）'}\n\n"
                "请输出如下 JSON 结构（字段名必须完全一致）：\n"
                "{\n"
                ' "recommendation": "建议受理 / 可预受理需补充材料 / 暂缓受理 之一",\n'
                ' "risk_level": "高 / 中 / 低 之一",\n'
                ' "risk_points": ["主要风险点1", "风险点2"],\n'
                ' "missing_materials": ["缺失的关键材料1", "..."],\n'
                ' "cause": {"name": "推荐案由", "code": "案由代码", "legal_basis": "法律依据"},\n'
                ' "jurisdiction": {"primary_court": "建议管辖法院", "legal_basis": "管辖依据", "reasoning": "理由"},\n'
                ' "strategy_summary": "一句话诉讼策略",\n'
                ' "next_steps": ["下一步1", "下一步2"]\n'
                "}\n"
                "注意：recommendation、risk_level 只能取给定的枚举值；如信息不足，字段填合理的专业推断。"
            )
            messages = [
                {"role": "system", "content": "你是资深诉讼律师，负责案件受理阶段的专业判断，只输出 JSON。"},
                {"role": "user", "content": user_prompt},
            ]
            call = self._json_chat(messages, max_tokens=3000, purpose="受理分析")
            if not call.get("ok"):
                return {"success": False, "error": call.get("error")}
            parsed = call["data"]
            result = {
                "success": True,
                "recommendation": parsed.get("recommendation") or "",
                "risk_level": parsed.get("risk_level") or "",
                "risk_points": parsed.get("risk_points") or [],
                "missing_materials": parsed.get("missing_materials") or [],
                "cause": parsed.get("cause") or {},
                "jurisdiction": parsed.get("jurisdiction") or {},
                "strategy_summary": parsed.get("strategy_summary") or "",
                "next_steps": parsed.get("next_steps") or [],
                "source": "primary_llm.assess_case_acceptance",
            }
            get_cache().set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            logger.error(f"受理分析 LLM 调用失败: {str(e)}")
            return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 进程级单例（2026-09-12）
# ---------------------------------------------------------------------------
# AIService.__init__ 会创建 1 个 httpx.Client + 最多 2 个 OpenAI 客户端（各带连接池）。
# 证据链路里有 4 处 `AIService()` 即时实例化 —— 每次调用重建三套客户端，连接池完全不复用，
# 高频调用下还会堆积 TIME_WAIT 连接。统一走 get_ai_service()。
_AI_SERVICE: "AIService | None" = None


def get_ai_service() -> AIService:
    """获取 AIService 进程级单例。"""
    global _AI_SERVICE
    if _AI_SERVICE is None:
        _AI_SERVICE = AIService()
    return _AI_SERVICE
