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

    def analyze_contract_risk(self, contract_content: str) -> dict:
        """分析合同风险点

        Args:
            contract_content: 合同内容文本

        Returns:
            包含风险分析结果的字典
        """
        try:
            prompt = f"""作为一名专业的法律顾问，请分析以下合同内容，识别潜在的法律风险点。

合同内容：
{contract_content}

请按以下格式输出分析结果：
1. 高风险点（如果有）
2. 中风险点（如果有）
3. 低风险点（如果有）
4. 整体风险评级（低/中/高）
5. 建议改进措施

请用简洁清晰的语言，突出重点。"""

            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": "你是一位专业的法律顾问，擅长合同风险分析。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )

            analysis_text = response.choices[0].message.content

            return {
                "success": True,
                "analysis": analysis_text,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"合同风险分析失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def extract_contract_clauses(self, contract_content: str) -> dict:
        """提取合同关键条款

        Args:
            contract_content: 合同内容文本

        Returns:
            包含提取结果的字典
        """
        try:
            prompt = f"""请从以下合同内容中提取关键条款信息：

合同内容：
{contract_content}

请提取以下信息（如果存在）：
1. 合同双方（甲方、乙方）
2. 合同标的
3. 合同金额
4. 履行期限
5. 付款方式
6. 违约责任
7. 争议解决方式
8. 其他重要条款

请用结构化的方式列出，每条信息单独一行。如果某项信息不存在，注明"未提及"。"""

            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": "你是一位专业的法律文书分析助手，擅长提取合同关键信息。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1500
            )

            extraction_text = response.choices[0].message.content

            return {
                "success": True,
                "clauses": extraction_text,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"条款提取失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def generate_contract_summary(self, contract_content: str) -> dict:
        """生成合同摘要

        Args:
            contract_content: 合同内容文本

        Returns:
            包含摘要的字典
        """
        try:
            prompt = f"""请为以下合同生成一份简洁的摘要（200字以内）：

合同内容：
{contract_content}

摘要应包括：
- 合同类型
- 合同双方
- 主要内容
- 关键条款
- 金额和期限（如果有）"""

            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": "你是一位专业的法律文书助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            summary_text = response.choices[0].message.content

            return {
                "success": True,
                "summary": summary_text,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"摘要生成失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def chat_about_contract(self, contract_content: str, question: str, chat_history: list = None) -> dict:
        """与AI助手对话咨询合同问题

        Args:
            contract_content: 合同内容文本
            question: 用户的问题
            chat_history: 对话历史 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]

        Returns:
            包含回答的字典
        """
        try:
            messages = [
                {"role": "system", "content": "你是一位专业的法律顾问，正在帮助用户理解和分析合同内容。请基于提供的合同内容回答用户的问题。"},
                {"role": "user", "content": f"这是需要分析的合同内容：\n{contract_content}"}
            ]

            # 添加对话历史
            if chat_history:
                messages.extend(chat_history)

            # 添加当前问题
            messages.append({"role": "user", "content": question})

            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=1500
            )

            answer = response.choices[0].message.content

            return {
                "success": True,
                "answer": answer,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"AI对话失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def generate_contract_content(self, prompt: str) -> dict:
        """生成合同内容

        Args:
            prompt: 合同生成提示词

        Returns:
            包含生成内容的字典
        """
        try:
            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": "你是一位专业的法律合同起草专家，擅长起草各类商业合同。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=3000
            )

            content = (response.choices[0].message.content or "").strip()
            if not content:
                return {
                    "success": False,
                    "error": "DeepSeek 返回了空合同正文",
                }

            return {
                "success": True,
                "content": content,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"合同生成失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def extract_evidence_fields(
        self,
        material_text: str,
        file_name: str = "",
        file_type: str = "",
    ) -> dict:
        """用 LLM 从证据原文里抽取结构化字段。

        输入：OCR/ASR/抽帧后的文本片段 + 文件名 + 文件类型
        输出（严格 JSON）：
          evidence_name     正式证据名称（按法院习惯改写）
          evidence_type     书证/言词证据/鉴定意见/视听资料/物证照片/电子数据
          proof_purpose     本证据要证明的事实（1-2 句法庭话术）
          three_natures     {真实性, 合法性, 关联性} 各一句
          risk_notes        对方可能质证的点
          supplement_advice 我方需要补强什么
          group_hint        第一组主体资格 / 第二组法律关系 / 第三组履行 / 第四组违约 / 第五组金额 / 第六组沟通 / 第七组其他
          confidence        0~1，LLM 自我评估抽取可信度
        失败时返回 {"success": False, "error": "..."}，调用方应降级到模板关键词逻辑。
        """
        try:
            snippet = (material_text or "")[:1800]
            system_prompt = (
                "你是一名执业律师助理，擅长把诉讼证据材料整理成可向法院提交的证据目录。"
                "你必须只输出合法 JSON，不要任何解释、不要 Markdown 代码块。"
            )
            user_prompt = (
                "请阅读下面这份证据材料，提取结构化字段并严格按 JSON 格式输出。\n"
                f"文件名：{file_name}\n"
                f"文件类型：{file_type}\n"
                "证据原文：\n"
                f"{snippet}\n\n"
                "输出 JSON 结构：\n"
                '{"evidence_name": "正式证据名称（按法院提交习惯）",\n'
                ' "evidence_type": "书证/言词证据/鉴定意见/视听资料/物证照片/电子数据 之一",\n'
                ' "proof_purpose": "1-2 句法庭话术，说明本证据要证明的事实",\n'
                ' "three_natures": {"真实性": "一句", "合法性": "一句", "关联性": "一句"},\n'
                ' "risk_notes": ["对方质证点1", "质证点2"],\n'
                ' "supplement_advice": ["补强建议1"],\n'
                ' "group_hint": "第一组主体资格/第二组法律关系成立/第三组履行/第四组违约/第五组金额损失/第六组沟通催告/第七组其他辅助 之一",\n'
                ' "confidence": 0.85}'
            )
            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return {"success": False, "error": "DeepSeek 返回了空 JSON"}
            import json
            try:
                parsed = json.loads(content)
            except Exception as e:
                return {"success": False, "error": f"JSON 解析失败: {e}; raw={content[:200]}"}
            return {
                "success": True,
                "evidence_name": parsed.get("evidence_name") or "",
                "evidence_type": parsed.get("evidence_type") or "",
                "proof_purpose": parsed.get("proof_purpose") or "",
                "three_natures": parsed.get("three_natures") or {},
                "risk_notes": parsed.get("risk_notes") or [],
                "supplement_advice": parsed.get("supplement_advice") or [],
                "group_hint": parsed.get("group_hint") or "",
                "confidence": float(parsed.get("confidence") or 0),
                "source": "primary_llm.extract_evidence_fields",
            }
        except Exception as e:
            logger.error(f"证据字段抽取失败: {str(e)}")
            return {"success": False, "error": str(e)}

    def summarize_material(
        self,
        material_text: str,
        file_name: str = "",
        file_type: str = "",
    ) -> dict:
        """用 LLM 对一份材料生成「重点摘要 + 证据价值评估」。

        输出（严格 JSON）：
          summary        一句话说明这份材料证明/记录了什么
          key_facts      关键事实 {字段: 值}（金额/日期/主体/承诺等）
          evidence_value 高 / 中 / 低（对案件的证明价值）
          needs_confirm  是否需要律师人工确认（金额/主体/日期不确定时为 true）
          risk_flags     风险提示列表
        失败返回 {"success": False, "error": "..."}，调用方降级为规则兜底。
        """
        import json
        try:
            snippet = (material_text or "")[:2000]
            system_prompt = (
                "你是一名执业律师助理，负责快速判断一份诉讼证据材料的证明价值和重点。"
                "你必须只输出合法 JSON，不要任何解释、不要 Markdown 代码块。"
            )
            user_prompt = (
                "请阅读下面这份材料，给出重点摘要和证据价值评估，严格按 JSON 输出。\n"
                f"材料名：{file_name}\n"
                f"材料类型：{file_type}\n"
                "材料内容：\n"
                f"{snippet}\n\n"
                "输出 JSON 结构：\n"
                '{"summary": "一句话说明这份材料证明或记录了什么",\n'
                ' "key_facts": {"关键字段": "值", "金额": "...", "日期": "...", "主体": "..."},\n'
                ' "evidence_value": "高/中/低 之一",\n'
                ' "needs_confirm": true 或 false,\n'
                ' "risk_flags": ["风险提示1"]}'
            )
            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return {"success": False, "error": "DeepSeek 返回了空 JSON"}
            try:
                parsed = json.loads(content)
            except Exception as e:
                return {"success": False, "error": f"JSON 解析失败: {e}"}
            value_map = {"高": "high", "中": "medium", "低": "low"}
            return {
                "success": True,
                "summary": parsed.get("summary") or "",
                "key_facts": parsed.get("key_facts") or {},
                "evidence_value": value_map.get(parsed.get("evidence_value"), "medium"),
                "needs_confirm": bool(parsed.get("needs_confirm", True)),
                "risk_flags": parsed.get("risk_flags") or [],
                "source": "primary_llm.summarize_material",
            }
        except Exception as e:
            logger.error(f"材料摘要评估失败: {str(e)}")
            return {"success": False, "error": str(e)}

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

    def analyze_case_strategy(self, case_info: dict, materials_summary: str = "", evidence_summary: str = "") -> dict:
        """用 LLM 做诉讼策略分析：案由、管辖、构成要件、举证责任、争议焦点、诉讼策略。

        Returns:
            {"success": True, "cause": {...}, "jurisdiction": {...}, "element_proof": [...],
             "dispute_focus": [...], "strategy_summary": ..., "litigation_path": [...]}
            失败返回 {"success": False, "error": "..."}
        """
        import json
        import time
        import hashlib
        from app.services.cache_service import get_cache
        cache_key = "strategy:" + hashlib.md5(
            (json.dumps(case_info, ensure_ascii=False, sort_keys=True) + "|" + (materials_summary or "") + "|" + (evidence_summary or "")).encode("utf-8")
        ).hexdigest()
        cached = get_cache().get(cache_key)
        if isinstance(cached, dict) and cached.get("success"):
            return {**cached, "source": "cache"}
        try:
            claims = case_info.get("claims") or []
            claims_text = "\n".join(f"- {c}" for c in claims) or "（未填写）"
            user_prompt = (
                "你是一名资深诉讼律师，请对下面这个案件做一次完整的诉讼策略分析，"
                "严格只输出合法 JSON，不要任何解释、不要 Markdown 代码块。\n\n"
                "【案件信息】\n"
                f"客户/原告：{case_info.get('customer_name') or '未提供'}\n"
                f"对方/被告：{case_info.get('opposite_party') or '未提供'}\n"
                f"被告住所地：{case_info.get('defendant_address') or (case_info.get('defendant') or {}).get('address') or '未提供'}\n"
                f"争议金额：{case_info.get('dispute_amount') or '未提供'}\n"
                f"案情摘要：{case_info.get('case_summary') or '未提供'}\n"
                f"诉讼请求：\n{claims_text}\n\n"
                "【已确认证据材料摘要】\n"
                f"{materials_summary or '（暂无）'}\n\n"
                "【证据目录/时间线摘要】\n"
                f"{evidence_summary or '（暂无）'}\n\n"
                "请输出如下 JSON 结构（字段名必须完全一致）：\n"
                "{\n"
                ' "cause": {"name": "推荐案由", "code": "案由代码", "legal_basis": "法律依据"},\n'
                ' "jurisdiction": {"primary_court": "建议管辖法院", "legal_basis": "管辖依据", "reasoning": "理由"},\n'
                ' "element_proof": [{"element": "构成要件", "proof_target": "证明目标", "evidence_focus": "关注证据"}],\n'
                ' "dispute_focus": ["争议焦点1", "争议焦点2"],\n'
                ' "strategy_summary": "一句话诉讼策略",\n'
                ' "litigation_path": [{"stage": "阶段", "action": "动作"}],\n'
                ' "next_steps": ["下一步1", "下一步2"]\n'
                "}\n"
                "注意：案由、管辖要结合案情和被告住所地给出专业判断；信息不足时给出合理专业推断。"
            )
            messages = [
                {"role": "system", "content": "你是资深诉讼律师，负责诉讼策略分析，只输出 JSON。"},
                {"role": "user", "content": user_prompt},
            ]
            call = self._json_chat(messages, max_tokens=4000, purpose="诉讼策略分析")
            if not call.get("ok"):
                return {"success": False, "error": call.get("error")}
            parsed = call["data"]
            result = {
                "success": True,
                "cause": parsed.get("cause") or {},
                "jurisdiction": parsed.get("jurisdiction") or {},
                "element_proof": parsed.get("element_proof") or [],
                "dispute_focus": parsed.get("dispute_focus") or [],
                "strategy_summary": parsed.get("strategy_summary") or "",
                "litigation_path": parsed.get("litigation_path") or [],
                "next_steps": parsed.get("next_steps") or [],
                "source": "primary_llm.analyze_case_strategy",
            }
            get_cache().set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            logger.error(f"诉讼策略分析 LLM 调用失败: {str(e)}")
            return {"success": False, "error": str(e)}

    async def chat(self, prompt: str, chat_history: list = None) -> dict:
        """通用AI对话

        Args:
            prompt: 提示词
            chat_history: 对话历史

        Returns:
            包含回答的字典
        """
        try:
            messages = []
            if chat_history:
                messages.extend(chat_history)
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=settings.primary_llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )

            answer = response.choices[0].message.content

            return {
                "success": True,
                "answer": answer,
                "model": settings.primary_llm_model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        except Exception as e:
            logger.error(f"AI对话失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
