"""AgentCore —— 主代理与 A2A 子代理服务共享的核心能力。

从原 DeepAgentsService 中抽出（逐字迁移，行为不变）：
- prompt 构建（输出契约 OUTPUT_CONTRACTS）
- deepagents/LangGraph 结果归一化 + JSON 抢救（围栏/非法转义/trailing comma/括号配对）
- drafting / review / litigation 三类结构化结果加工（指标逻辑都在这里，不许动）
- deepagents 构建材料（model / tools / skills / permissions / backend）

拆分原因（A2A 架构改造，2026-09-07）：
主代理（:8000 进程内）与两个独立 A2A 子代理服务（:8001 起草、:8002 审核）
需要共用同一套 prompt 契约与结果加工逻辑，保证 A2A 拆分后指标不劣化。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver  # noqa: F401 — 保留供类型参考
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.checkpoint import build_checkpointer
from app.mcps.clients import get_mcp_client


settings = get_settings()

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
SKILL_DIR = BACKEND_ROOT / "skills"


def _skill_slug(name: str) -> str:
    """把历史的 CamelCase skill 文件名转成 deepagents 要求的 kebab-case 目录名。

    CaseIntakeSkill.md -> case-intake-skill
    已经是 kebab-case 的输入原样返回。
    """
    stem = name[:-3] if name.endswith(".md") else name
    if "-" in stem or stem.islower():
        return stem.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "-", stem).lower()


# ---------------------------------------------------------------------------
# 共享 MCP/skill 工具（主代理与子代理都挂载）
# ---------------------------------------------------------------------------
@tool
async def list_skill_documents() -> str:
    """列出 backend/skills 下所有可供 deepagents 读取的 skill（每个 skill 是一个含 SKILL.md 的目录）。"""
    items = sorted(
        path.name for path in SKILL_DIR.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    ) if SKILL_DIR.exists() else []
    return json.dumps({"ok": True, "data": {"items": items, "count": len(items)}}, ensure_ascii=False)


@tool
async def list_mcp_servers() -> str:
    """列出当前已注册的 MCP server。"""
    client = get_mcp_client()
    return json.dumps({"ok": True, "data": client.list_servers()}, ensure_ascii=False, default=str)


@tool
async def list_mcp_tools() -> str:
    """列出当前已注册的 MCP tool。"""
    client = get_mcp_client()
    return json.dumps({"ok": True, "data": client.list_tools()}, ensure_ascii=False, default=str)


@tool
async def call_mcp_tool(server_name: str, tool_name: str, params_json: str = "{}") -> str:
    """调用指定 MCP 工具。params_json 必须是 JSON 字符串。"""
    try:
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            raise ValueError("params_json 必须解析为 JSON 对象")
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"参数解析失败: {exc}"}, ensure_ascii=False)

    client = get_mcp_client()
    result = await client.call(server_name, tool_name, **params)
    return json.dumps(result, ensure_ascii=False, default=str)


def build_chat_model():
    """起草/审核专用模型（DRAFT_REVIEW_MODEL），与诉讼文本模型(QWEN_MODEL)分离。

    timeout/max_retries 必须显式收紧：代理抖动时 openai SDK 默认等 600s 且重试 2 次，
    用户端会表现为"进度条卡死十几分钟"。
    """
    return ChatOpenAI(
        model=settings.draft_review_llm_model,
        api_key=settings.primary_llm_api_key,
        base_url=(
            settings.primary_llm_api_url.rstrip("/")
            .removesuffix("/chat/completions")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        temperature=0.2,
        timeout=300,
        max_retries=1,
    )


# ---------------------------------------------------------------------------
# 子代理规格（system_prompt 与 skill 名单自原 _build_subagents 逐字迁移）
# ---------------------------------------------------------------------------
DRAFTING_SPEC: Dict[str, Any] = {
    "name": "drafting-agent",
    "description": "处理合同起草、模板匹配和质量检查。",
    "system_prompt": (
        "你负责合同起草子任务，重点输出合同正文、模板选择、相似检索、风险概览和质量检查。"
        "最终回复必须只输出一个 JSON 对象，不要输出任何思考过程、解释文字或 markdown 围栏。"
        "JSON 结构：{\"content\":{\"title\":\"标题\",\"content\":\"完整正文\",\"html_content\":\"HTML正文\"},"
        "\"contract_summary\":{\"summary\":\"摘要\",\"key_points\":[]},"
        "\"quality_check\":{\"status\":\"pass|warning\",\"issues\":[],\"suggestions\":[]}}。"
    ),
    "skill_files": ["drafting-skill"],
}

REVIEW_SPEC: Dict[str, Any] = {
    "name": "review-agent",
    "description": "处理合同审查、风险识别和报告生成。",
    "system_prompt": (
        "你负责文书审查子任务，重点识别结构问题、法律风险、逻辑问题与合规问题。\n"
        "【穷尽式审查要求——最高优先级】\n"
        "1. 必须逐条、逐款通读全文，发现的每一个问题都要输出，issues 数量不设上限，"
        "不要只挑最严重的几条，禁止为了精简而省略已发现的问题。\n"
        "2. 输出前必须完成以下检查清单（每项都要过一遍，没问题的项可以不出 issue，"
        "但检查过的事实要在心里核对过，不得跳过）：\n"
        "   a. 金额一致性：全文所有金额的大小写、前后条款数字是否一致（如本金、还款额、违约金基数）；\n"
        "   b. 日期/时间逻辑：签订日期、生效日期、交付日期、期限起止是否自洽（不得早于签订日、不得倒挂）；\n"
        "   c. 法条引用：引用的法律是否现行有效（如《合同法》已废止应改《民法典》）、条文内容是否与所支撑条款匹配；\n"
        "   d. 违约金/利率：比例是否过高（超过实际损失30%、年化明显超司法保护上限）；\n"
        "   e. 管辖约定：协议管辖法院是否与争议有实际联系、是否违反专属管辖、诉讼与仲裁是否并存矛盾；\n"
        "   f. 缺失条款：违约责任、争议解决、不可抗力、保密、验收/交接程序、单方解除机制等关键条款是否缺失；\n"
        "   g. 权利义务失衡：免责条款是否排除重大过失责任、单方变更权、显失公平条款；\n"
        "   h. 签署要件：签字盖章位、日期是否齐备。\n"
        "3. 同一条款有多个独立问题的，分别输出多条 issue。\n"
        "请按以下 JSON 契约输出最终结果（直接作为工具调用的最终消息返回，不要放在嵌套字段里）：\n"
        "{\n"
        '  "review_status": "pass|warning|fail",\n'
        '  "overall_score": 0-1 的小数（问题越多越低，建议起点 0.9，每发现一个严重问题扣 0.1-0.2），\n'
        '  "issues": [\n'
        '    {"clause": "涉及的条款名或第N条", "severity": "high|medium|low",\n'
        '     "description": "问题描述", "reason": "风险理由（可与描述合并）",\n'
        '     "legal_basis": "引用的法条/司法解释", "suggestion": "具体修改建议"}\n'
        "  ],\n"
        '  "suggestions": ["整体优化建议1", "整体优化建议2"]\n'
        "}\n"
        "严格要求：issues 必须是顶层字段的数组，每个 issue 必须包含 clause、severity、description、suggestion 四项，"
        "不能把所有问题塞到 dimensions 子字段里。哪怕只发现 1 个问题，也要输出 issues 数组。"
        "宁多报不可漏报：漏掉一个真实缺陷比多列一条疑问严重得多。"
    ),
    "skill_files": [
        "document-parsing-skill",
        "legal-risk-check-skill",
        "logic-consistency-skill",
        "review-report-skill",
    ],
}


# ---------------------------------------------------------------------------
# 各业务板块要求模型回传的 JSON 契约。缺了这段约定，
# 模型会输出自由散文，下游 builder 取不到结构化键，只能回落占位模板。
# ---------------------------------------------------------------------------
OUTPUT_CONTRACTS: Dict[str, str] = {
    "drafting": (
        '{"content":{"title":"文书标题","content":"完整正文，含条款编号，不得省略、不得写待补充",'
        '"html_content":"正文的 HTML"},'
        '"contract_summary":{"summary":"摘要","key_points":["要点"]},'
        '"quality_check":{"status":"pass|warning","total_issues":0,"issues":[],"suggestions":[]},'
        '"risk_assessment":{"overall":{"score":0-100,"level":"低|中|高"},'
        '"legal_risk":{},"financial_risk":{},"operational_risk":{}}}'
    ),
    "review": (
        '{"review_status":"pass|warning|fail","overall_score":0-1 的小数,'
        '"dimensions":{"legal_compliance":{"issues":[],"suggestions":[]},'
        '"logic_consistency":{"issues":[],"suggestions":[]},'
        '"risk_assessment":{"issues":[],"suggestions":[]},'
        '"compliance_scan":{"issues":[],"suggestions":[]}},'
        '"issues":[{"clause":"条款定位","severity":"高|中|低","description":"问题描述",'
        '"legal_basis":"法律依据","suggestion":"修改建议"}],"suggestions":["整体建议"]}'
    ),
}


class AgentCore:
    """主代理与 A2A 子代理共用的构建材料与结果加工逻辑。"""

    # ---- deepagents 构建材料 ----
    def build_tools(self) -> list[Any]:
        return [list_skill_documents, list_mcp_servers, list_mcp_tools, call_mcp_tool]

    def build_skill_documents(self) -> list[str]:
        """deepagents 0.7.11 要求 skill 为「含 SKILL.md 的目录」，不能是散装 .md 文件。

        必须返回 FilesystemBackend 可识别的虚拟路径（/skills/<name>），
        返回 Windows 绝对路径会导致模型按绝对路径读 SKILL.md 时报
        "Windows absolute paths are not supported"，白白浪费 2~5 次工具调用。
        """
        if not SKILL_DIR.exists():
            return []
        return [
            f"/skills/{path.name}" for path in sorted(SKILL_DIR.iterdir())
            if path.is_dir() and (path / "SKILL.md").exists()
        ]

    def skill_documents_for(self, filenames: List[str]) -> List[str]:
        """按名称挑选子代理专属 skill，自动兼容历史 CamelCase.md 写法（返回虚拟路径）。"""
        paths: List[str] = []
        for filename in filenames:
            path = SKILL_DIR / _skill_slug(filename)
            if path.is_dir() and (path / "SKILL.md").exists():
                paths.append(f"/skills/{path.name}")
        return paths

    def build_memory_paths(self) -> list[str]:
        memory_paths: list[str] = []
        root_memory = Path(__file__).resolve().parents[3] / "AGENTS.md"
        if root_memory.exists():
            memory_paths.append(self._normalize_path(root_memory))
        # PG 长期记忆：装配期物化为文件挂载（PG 为源，运行后由 sync_runtime_memory 回写）
        try:
            from app.services.agent_memory_service import get_runtime_memory_path
            runtime_memory = get_runtime_memory_path()
            if runtime_memory is not None and runtime_memory.exists():
                memory_paths.append(self._normalize_path(runtime_memory))
        except Exception as exc:  # noqa: BLE001 — 记忆挂载失败不阻断装配
            logger.warning("[agent-core] 长期记忆挂载跳过: %s", exc)
        return memory_paths

    def build_permissions(self) -> list[FilesystemPermission]:
        skill_dir = SKILL_DIR
        return [
            FilesystemPermission(operations=["read", "write"], paths=[self._normalize_path(BACKEND_ROOT)], mode="allow"),
            FilesystemPermission(operations=["read"], paths=[self._normalize_path(skill_dir)], mode="allow"),
        ]

    def build_backend(self) -> CompositeBackend:
        return CompositeBackend(
            default=FilesystemBackend(root_dir=str(BACKEND_ROOT), virtual_mode=True),
            routes={
                "workspace": FilesystemBackend(root_dir=str(BACKEND_ROOT), virtual_mode=True),
            },
            artifacts_root="/",
        )

    def build_sub_agent(self, spec: Dict[str, Any]):
        """按子代理规格构建独立 deep agent（A2A 服务进程内运行 / 主控回退共用）。"""
        return create_deep_agent(
            model=build_chat_model(),
            tools=self.build_tools(),
            system_prompt=spec["system_prompt"],
            skills=self.skill_documents_for(spec["skill_files"]),
            permissions=self.build_permissions(),
            backend=self.build_backend(),
            checkpointer=build_checkpointer(),
            interrupt_on={"write_file": True},
            name=spec["name"],
        )

    # ---- prompt 构建 ----
    def _build_prompt(self, request: Dict[str, Any], as_root: bool = False) -> str:
        task_type = request.get("task_type", "")
        action = request.get("action", "")
        context = request.get("context", {}) or {}
        contract = OUTPUT_CONTRACTS.get(task_type)

        lines = [
            f"请按法律系统业务处理任务。任务类型：{task_type}；动作：{action}。",
            "请充分利用已加载的 skill 文档与子代理能力，产出可直接交付给律师使用的专业内容。",
            f"上下文：{json.dumps(context, ensure_ascii=False, default=str)}",
        ]
        if contract:
            lines += [
                "",
                "【输出要求】最终回复只输出一个 JSON 对象，不要任何解释文字或 markdown 围栏，严格遵循以下结构：",
                contract,
                "",
                "硬性要求：所有字段必须基于上下文给出实质内容；"
                "严禁输出「待补充」「待完善」「TODO」之类占位文字；"
                "正文需符合中国法律实务写作规范，引用现行有效的法律条文。",
            ]
            if as_root:
                lines += [
                    "",
                    "【执行方式】本任务必须先调用对应的 A2A 派发工具（起草: dispatch_drafting_task；"
                    "审核: dispatch_review_task）交由子代理执行；"
                    "然后把工具返回的 JSON 原样、完整地作为你的最终回复输出，"
                    "不得改写、增删或省略任何字段，不要再做任何解释。",
                ]
        else:
            lines.append("请优先根据上下文给出结构化结果，必要时委派给合适的子代理。")
        return "\n".join(lines)

    # ---- 结果归一化 ----
    def _normalize_result(self, result: Any) -> Dict[str, Any]:
        """把 deepagents/LangGraph 的图状态归一化成下游 builder 能消费的扁平字典。

        关键点：`agent.ainvoke()` 返回的是 `{"messages": [...]}` 形式的图状态，
        真正的模型产出在末尾 AI 消息里。若不抽取出来，
        `_build_*_result` 取不到 content/output/dimensions 等键，
        会全部回落到占位兜底模板（表现为「待 deepagents 完善生成」）。
        """
        if not isinstance(result, dict) and hasattr(result, "model_dump"):
            result = result.model_dump()
        if not isinstance(result, dict):
            return {"output": str(result)}

        normalized = dict(result)
        text = self._extract_final_text(normalized.get("messages"))
        if text:
            normalized.setdefault("output", text)
            parsed = self._try_parse_json(text)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if key not in ("messages", "output"):
                        normalized.setdefault(key, value)
        return normalized

    @staticmethod
    def _extract_final_text(messages: Any) -> str:
        """从消息列表尾部向前找出最后一条非空的 AI 文本内容。"""
        if not isinstance(messages, (list, tuple)):
            return ""
        for message in reversed(list(messages)):
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                if message.get("role") in ("user", "system"):
                    continue
                content = message.get("content")
            if content is None:
                continue
            # LangChain 的 content 可能是 str，也可能是 [{"type":"text","text":...}]
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = "\n".join(part for part in parts if part).strip()
            else:
                text = str(content).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _loads_lenient(seg: str) -> Any:
        r"""先按标准 JSON 解析；失败则迭代修复常见模型输出问题后重试。

        模型输出常见的两类非法 JSON：
        1) 非法转义（如 `\p`，合法转义只有 `\" \\ / b f n r t u`）；
        2) trailing comma（对象/数组最后一个元素后多逗号，如 `},`）。
        每轮只做一处最小修复并重试，直到成功或无可修。
        """
        if not seg:
            return None
        try:
            return json.loads(seg)
        except (ValueError, TypeError):
            pass
        cur = seg
        for _ in range(40):  # 最多修 40 轮，防死循环
            repaired = AgentCore._strip_bad_escapes(cur)
            if repaired != cur:
                cur = repaired
            else:
                repaired = AgentCore._strip_trailing_commas(cur)
                if repaired == cur:
                    break
                cur = repaired
            try:
                return json.loads(cur)
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def _strip_bad_escapes(text: str) -> str:
        r"""删除 JSON 字符串内的非法转义反斜杠。

        只匹配 `\` 后跟的不是合法转义目标（\" \\ / b f n r t u 或 uXXXX 四 hex）的
        位置，并把那个反斜杠删掉。一次只删一个，逐步收敛。
        """
        pattern = re.compile(
            r'\\(?!(?:["\\/bfnrt])|(?:u[0-9a-fA-F]{4}))'
        )
        return pattern.sub("", text, count=1)

    @staticmethod
    def _strip_trailing_commas(text: str) -> str:
        """删除 JSON 的 trailing comma（如 `},`、`],`）。

        模型经常在对象/数组收尾多打一个逗号。用带字符串状态感知的扫描
        只处理结构位置的逗号，避免误删字符串内部的 `,}`。
        """
        VALID_ESC = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
        out: list[str] = []
        i, n = 0, len(text)
        in_str = False
        while i < n:
            ch = text[i]
            if not in_str:
                if ch == '"':
                    in_str = True
                out.append(ch)
                i += 1
                continue
            # 字符串内部
            if ch == "\\" and i + 1 < n:
                nxt = text[i + 1]
                if nxt in VALID_ESC:
                    out.append(ch)
                    out.append(nxt)
                    i += 2
                    continue
            if ch == '"' and text[i - 1] != "\\":
                in_str = False
            out.append(ch)
            i += 1
        cleaned = "".join(out)
        # 现在字符串外结构位置的 ,} / ,] 都是真 trailing comma
        return re.sub(r",\s*([}\]])", r"\1", cleaned, count=1)

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        """尽力从模型输出里解析出 JSON，兼容 ```json 围栏和前后夹带说明文字的情况。

        模型偶尔会输出多层嵌套/带思考过程前缀的围栏 JSON，甚至正文里混入 ``` 代码块，
        单次正则截取容易失败。策略：
        1) 逐个尝试用所有可能的 ``` 结束点切围栏内容解析；
        2) 都不行就退回"括号配对"从文本中找出真正完整的最外层 JSON 块；
        3) 仍失败返回 None（由下游兜底）。
        """
        candidate = (text or "").strip()
        if not candidate:
            return None

        # 1) 围栏路径：找首个 ```json 起始，逐个结束点尝试解析
        fence_start = re.search(r"```(?:json)?\s*", candidate)
        if fence_start:
            body = candidate[fence_start.end():]
            for m in re.finditer(r"```", body):
                seg = body[:m.start()].strip()
                if not seg:
                    continue
                parsed = AgentCore._loads_lenient(seg)
                if parsed is not None:
                    return parsed

        # 2) 裸 JSON / 括号配对：从第一个 {/[ 起做括号深度配对，取真正闭合处
        start = -1
        for idx, ch in enumerate(candidate):
            if ch in "{[":
                start = idx
                break
        if start == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        end = -1
        for idx in range(start, len(candidate)):
            ch = candidate[idx]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end > start:
            segment = candidate[start:end + 1]
            parsed = AgentCore._loads_lenient(segment)
            if parsed is not None:
                return parsed

        # 3) 兜底：首尾大括号截取（老逻辑）
        if end > start:
            tail = candidate[start:candidate.rfind("}") + 1]
        else:
            tail = candidate[start:]
        return AgentCore._loads_lenient(tail)

    # ---- 结构化结果加工（指标逻辑，逐字迁移，勿改） ----
    def _build_structured_result(self, request: Dict[str, Any], raw_result: Dict[str, Any]) -> Dict[str, Any]:
        task_type = request.get("task_type", "")
        action = request.get("action", "")
        context = request.get("context", {}) or {}
        if task_type == "drafting":
            return self._build_drafting_result(action, context, raw_result)
        if task_type == "review":
            return self._build_review_result(action, context, raw_result)
        if task_type == "litigation":
            return self._build_litigation_result(action, context, raw_result)
        return {
            "status": "success",
            "task_type": task_type,
            "action": action,
            "result": raw_result,
            "agents_executed": ["DeepAgentsService"],
            "execution_trace": [{"step": "deepagents_root", "status": "success"}],
            "deepagents_output": raw_result,
        }

    def _build_drafting_result(self, action: str, context: Dict[str, Any], raw_result: Dict[str, Any]) -> Dict[str, Any]:
        case_summary = context.get("case_summary") or context.get("description") or context.get("requirements") or ""
        customer_name = context.get("customer_name") or (context.get("parties") or {}).get("plaintiff", {}).get("name") or "待补充"
        defendant_name = (context.get("parties") or {}).get("defendant", {}).get("name") or context.get("counterparty") or "待补充"
        document_type = context.get("document_type") or context.get("contract_type") or "法律文书"

        raw_content = raw_result.get("content")
        _title = None
        if isinstance(raw_content, dict):
            body_text = raw_content.get("content") or raw_content.get("text") or ""
            html_text = raw_content.get("html_content") or self._to_html(body_text)
            _title = raw_content.get("title")
        elif isinstance(raw_content, str) and raw_content.strip():
            body_text, html_text, _title = self._unwrap_drafting_text(raw_content)
        elif isinstance(raw_result.get("output"), str) and raw_result.get("output", "").strip():
            body_text, html_text, _title = self._unwrap_drafting_text(raw_result.get("output", ""))
        else:
            body_text = self._fallback_contract_text(document_type, customer_name, defendant_name, case_summary, context)
            html_text = self._to_html(body_text)

        # 多层解包兜底：模型偶尔把 {"content": {...}} 整体再序列化一层 JSON 字符串
        # （\n 以字面转义出现），只解一层会让编辑器渲染出一坨原始 JSON。循环解到纯文本为止。
        for _ in range(5):
            if isinstance(body_text, dict):
                _title = body_text.get("title") or _title
                html_text = body_text.get("html_content") or html_text
                body_text = body_text.get("content") or body_text.get("text") or ""
                continue
            if isinstance(body_text, str):
                stripped = body_text.strip()
                if stripped.startswith("{") or stripped.startswith("```"):
                    new_body, new_html, new_title = self._unwrap_drafting_text(stripped)
                    if not new_body or new_body == stripped:
                        break  # 解不开就停，保留原文，避免死循环
                    body_text = new_body
                    html_text = new_html or html_text
                    _title = _title or new_title
                    continue
            break
        if not isinstance(body_text, str):
            body_text = str(body_text)

        content = {
            "title": (raw_content.get("title") if isinstance(raw_content, dict) and raw_content.get("title")
                      else _title or f"{document_type} - {customer_name}"),
            "content": body_text,
            "html_content": html_text,
        }

        data_collection = raw_result.get("data_collection") or {
            "party_id": context.get("party_id"),
            "customer_name": customer_name,
            "contract_type": context.get("contract_type") or document_type,
            "industry": context.get("industry") or "通用",
            "jurisdiction": context.get("jurisdiction") or "中国",
            "materials_count": len(context.get("materials") or []),
        }
        template_selection = raw_result.get("template_selection") or raw_result.get("template_matching") or {
            "template_id": f"TPL-{document_type}",
            "template_name": f"{document_type}标准模板",
            "document_type": document_type,
            "template_sections": ["当事人信息", "核心条款", "事实与理由", "签署与日期"],
        }
        similarity_search = raw_result.get("similarity_search") or raw_result.get("similarity") or {
            "status": "success",
            "total_found": 0,
            "similar_contracts": [],
        }
        quality_check = raw_result.get("quality_check") or {
            "status": "pass",
            "total_issues": 0,
            "high_severity": 0,
            "checked_rules": ["structure", "mandatory_fields", "logic"],
            "issues": [],
            "suggestions": [],
        }
        quality_score = raw_result.get("quality_score")
        if quality_score is None:
            quality_score = 0.88 if quality_check.get("status") == "pass" else 0.72
        risk_assessment = raw_result.get("risk_assessment") or {
            "overall": {
                "score": round(float(quality_score) * 100, 1),
                "level": "低" if quality_score >= 0.85 else "中",
            },
            "legal_risk": {},
            "financial_risk": {},
            "operational_risk": {},
            "reputation_risk": {},
        }
        contract_summary = raw_result.get("contract_summary") or {
            "summary": case_summary[:200] or f"{document_type}初稿已生成。",
            "key_points": ["主体信息", "核心条款", "履约要点"],
        }
        contract_generation = raw_result.get("contract_generation") or {
            "title": content["title"],
            "content": body_text,
            "html_content": html_text,
            "document_type": document_type,
        }

        deepagents_output = {
            **raw_result,
            "data_collection": data_collection,
            "template_selection": template_selection,
            "similarity_search": similarity_search,
            "quality_check": quality_check,
            "risk_assessment": risk_assessment,
            "contract_summary": contract_summary,
            "contract_generation": contract_generation,
        }

        return {
            "status": "success",
            "task_type": "drafting",
            "action": action,
            "document_id": context.get("document_id") or "DOC-PENDING",
            "document_type": document_type,
            "content": content,
            "quality_score": quality_score,
            "data_collection": data_collection,
            "template_selection": template_selection,
            "similarity_search": similarity_search,
            "risk_assessment": risk_assessment,
            "quality_check": quality_check,
            "contract_summary": contract_summary,
            "contract_generation": contract_generation,
            "agents_executed": ["DeepAgentsService", "drafting-agent"],
            "execution_trace": self._build_trace("drafting-agent", action),
            "deepagents_output": deepagents_output,
        }

    def _build_review_result(self, action: str, context: Dict[str, Any], raw_result: Dict[str, Any]) -> Dict[str, Any]:
        dimensions = raw_result.get("dimensions") if isinstance(raw_result.get("dimensions"), dict) else {}
        if not dimensions:
            dimensions = {
                "legal_compliance": raw_result.get("legal_compliance", {}),
                "logic_consistency": raw_result.get("logic_consistency", {}),
                "risk_assessment": raw_result.get("risk_assessment", {}),
                "compliance_scan": raw_result.get("compliance_scan", {}),
            }
        suggestions = raw_result.get("suggestions") or []
        if not suggestions:
            suggestions = self._collect_review_suggestions(dimensions)
        issues = raw_result.get("issues") or self._collect_review_issues(dimensions)
        # 兜底：AI 把 issues 塞在 dimensions 子字段的字符串数组里时，补全成对象数组（前端靠 clause/severity 匹配段号）
        if issues and isinstance(issues, list) and issues and isinstance(issues[0], str):
            issues = [self._normalize_string_issue(s, idx) for idx, s in enumerate(issues)]
        # 二次兜底：dimensions 里散落的字符串 issues 没被顶层收集时，扫一遍
        if not issues:
            collected = []
            for key in ("risk_assessment", "legal_compliance", "logic_consistency", "compliance_scan"):
                block = dimensions.get(key) or {}
                block_issues = block.get("issues") if isinstance(block, dict) else None
                if isinstance(block_issues, list):
                    for s in block_issues:
                        if isinstance(s, str):
                            collected.append(self._normalize_string_issue(s, len(collected)))
                        else:
                            collected.append(s)
            if collected:
                issues = collected
        # 三次兜底：模型输出畸形嵌套 JSON（穷尽式 prompt 下高频）——
        # parse 失败时从原始文本正则抢救 issues / review_status / overall_score
        salv_status, salv_score, salv_issues = None, None, []
        if not issues:
            salv_status, salv_score, salv_issues = self._salvage_review_from_raw(
                str(raw_result.get("output") or "")
            )
            if salv_issues:
                seen: set = set()
                issues = []
                for idx, s in enumerate(salv_issues):
                    norm = self._normalize_string_issue(s, len(issues)) if isinstance(s, str) else s
                    key = str(norm.get("description") if isinstance(norm, dict) else norm)[:40]
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(norm)
        overall_score = raw_result.get("overall_score")
        if overall_score is None and salv_score is not None:
            overall_score = salv_score
        if overall_score is None:
            overall_score = self._derive_review_score(dimensions, issues)
        review_status = raw_result.get("review_status") or salv_status or (
            "pass" if overall_score >= 0.9 and not issues else "warning"
        )
        parsed_document = raw_result.get("parsed_document") or context.get("parsed_document") or {}
        deepagents_output = {
            **raw_result,
            "dimensions": dimensions,
            "issues": issues,
            "suggestions": suggestions,
            "overall_score": overall_score,
            "review_status": review_status,
            "parsed_document": parsed_document,
        }
        return {
            "status": "success",
            "task_type": "review",
            "action": action,
            "review_status": review_status,
            "overall_score": overall_score,
            "parsed_document": parsed_document,
            "dimensions": dimensions,
            "issues": issues,
            "suggestions": suggestions,
            "agents_executed": ["DeepAgentsService", "review-agent"],
            "execution_trace": self._build_trace("review-agent", action),
            "deepagents_output": deepagents_output,
        }

    def _build_litigation_result(self, action: str, context: Dict[str, Any], raw_result: Dict[str, Any]) -> Dict[str, Any]:
        intake = raw_result.get("intake") or context.get("intake") or {}
        evidence = raw_result.get("evidence") or context.get("evidence") or {}
        cause = raw_result.get("cause") or {}
        jurisdiction = raw_result.get("jurisdiction") or {}
        strategy = raw_result.get("strategy") or raw_result.get("assessment") or {}
        compliance = raw_result.get("compliance") or {}
        pleading = raw_result.get("pleading") or raw_result.get("draft") or {}

        if action == "analyze_materials":
            evidence_payload = {
                "materials": raw_result.get("materials") or evidence.get("materials", []),
                "summary": raw_result.get("summary") or evidence.get("summary") or {},
                "confirmation_blocks": raw_result.get("confirmation_blocks") or evidence.get("confirmation_blocks") or [],
                "evidence_catalog": raw_result.get("evidence_catalog") or evidence.get("evidence_catalog") or [],
                "timeline": raw_result.get("timeline") or evidence.get("timeline") or [],
                "facts": raw_result.get("facts") or evidence.get("facts") or [],
                "missing_materials": raw_result.get("missing_materials") or evidence.get("missing_materials") or [],
            }
            deepagents_output = {**raw_result, "evidence": evidence_payload}
            return {
                "status": "success",
                "task_type": "litigation",
                "action": action,
                **evidence_payload,
                "agents_executed": ["DeepAgentsService", "litigation-agent"],
                "execution_trace": self._build_trace("litigation-agent", action),
                "deepagents_output": deepagents_output,
            }

        if action == "generate_case_draft":
            deepagents_output = {
                **raw_result,
                "draft": pleading or context.get("evidence_organizing") or {},
                "assessment": strategy,
                "cause": cause,
                "jurisdiction": jurisdiction,
                "compliance": compliance,
            }
            return {
                "status": "success",
                "task_type": "litigation",
                "action": action,
                "draft": pleading or context.get("evidence_organizing") or {},
                "assessment": strategy,
                "cause": cause,
                "jurisdiction": jurisdiction,
                "risk": raw_result.get("risk") or {},
                "strategy": strategy,
                "compliance": compliance,
                "agents_executed": ["DeepAgentsService", "litigation-agent"],
                "execution_trace": self._build_trace("litigation-agent", action),
                "deepagents_output": deepagents_output,
            }

        if action == "archive_case":
            deepagents_output = {
                **raw_result,
                "draft": pleading or context.get("evidence_organizing") or {},
                "cause": cause,
                "jurisdiction": jurisdiction,
                "compliance": compliance,
                "archive_status": raw_result.get("archive_status") or "ready_for_database",
            }
            return {
                "status": "success",
                "task_type": "litigation",
                "action": action,
                "draft": pleading or context.get("evidence_organizing") or {},
                "cause": cause,
                "jurisdiction": jurisdiction,
                "risk": raw_result.get("risk") or {},
                "strategy": strategy,
                "compliance": compliance,
                "archive_status": deepagents_output["archive_status"],
                "agents_executed": ["DeepAgentsService", "litigation-agent"],
                "execution_trace": self._build_trace("litigation-agent", action),
                "deepagents_output": deepagents_output,
            }

        deepagents_output = {
            **raw_result,
            "intake": intake,
            "evidence": evidence,
            "cause": cause,
            "jurisdiction": jurisdiction,
            "pleading": pleading,
            "compliance": compliance,
            "strategy": strategy,
        }
        return {
            "status": "success",
            "task_type": "litigation",
            "action": action,
            "case_id": raw_result.get("case_id") or context.get("case_id") or context.get("intake_id") or "CASE-PENDING",
            "intake": intake,
            "evidence": evidence,
            "cause": cause,
            "jurisdiction": jurisdiction,
            "pleading": pleading,
            "compliance": compliance,
            "strategy": strategy,
            "agents_executed": ["DeepAgentsService", "litigation-agent"],
            "execution_trace": self._build_trace("litigation-agent", action),
            "deepagents_output": deepagents_output,
        }

    def _collect_review_issues(self, dimensions: Dict[str, Any]) -> List[Any]:
        issues: List[Any] = []
        for key in ("risk_assessment", "legal_compliance", "logic_consistency", "compliance_scan"):
            block = dimensions.get(key) or {}
            block_issues = block.get("issues") if isinstance(block, dict) else None
            if isinstance(block_issues, list):
                issues.extend(block_issues)
        return issues

    def _normalize_string_issue(self, text: str, idx: int) -> Dict[str, Any]:
        """AI 把 issue 输出成纯字符串时，自动补全 clause/severity/description/legal_basis/suggestion 字段。
        前端靠 clause 匹配段号 → 段落标红 → 显示问题块；不补全就匹配不到段。"""
        s = str(text or "").strip()
        # 严重度按关键词推断
        high_keys = ("无效", "违法", "严重", "显失公平", "过高", "不成立", "缺失", "未明确")
        low_keys = ("建议", "可以", "优化", "考虑", "完善")
        severity = "medium"
        if any(k in s for k in high_keys):
            severity = "high"
        elif any(k in s for k in low_keys):
            severity = "low"
        # 法律依据：从字符串里捞 "《XX法》第X条" 或 "《民法典》..." 这样的引用
        legal_basis = ""
        m = re.search(r"《[^》]+》(第[^，。；,;\s]+条(?:第[一二三四五六七八九十百]+款)?)?", s)
        if m:
            legal_basis = m.group(0)
        # clause：尝试捞"第N条"或"第N款"，没有就用"条款"+序号
        cm = re.search(r"第[一二三四五六七八九十百零\d]+条", s)
        if cm:
            clause = cm.group(0)
        else:
            clause = f"问题{idx + 1}"
        return {
            "type": "risk",
            "clause": clause,
            "severity": severity,
            "description": s,
            "reason": s,
            "legal_basis": legal_basis,
            "suggestion": "请根据上述风险人工补全修改建议",
        }

    def _derive_review_score(self, dimensions: Dict[str, Any], issues: Optional[List[Any]] = None) -> float:
        if issues is None:
            issues = self._collect_review_issues(dimensions)
        return round(max(0.35, 0.98 - 0.08 * len(issues)), 2)

    def _collect_review_suggestions(self, dimensions: Dict[str, Any]) -> List[str]:
        suggestions: List[str] = []
        for key in ("risk_assessment", "legal_compliance", "logic_consistency", "compliance_scan"):
            block = dimensions.get(key) or {}
            if isinstance(block, dict):
                for item in block.get("suggestions") or []:
                    suggestions.append(str(item))
        return suggestions

    def _salvage_review_from_raw(self, raw_text: str):
        """从模型原始（可能畸形嵌套的）JSON 文本中抢救 review_status / overall_score / issues。

        v3 穷尽式 prompt 下模型倾向输出 dimensions 多层嵌套结构且嵌套层级写错，
        整体 json.loads 失败，但每个 "issues": [...] 数组本身是完好的——
        用括号配平抓数组、再抓数组内带引号的长字符串即可恢复全部问题条目。
        """
        if not raw_text:
            return None, None, []
        issues: List[Any] = []
        status = None
        score = None

        parsed = self._try_parse_json(raw_text)

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "issues" and isinstance(v, list):
                        issues.extend(v)
                    else:
                        _walk(v)
            elif isinstance(node, list):
                for it in node:
                    _walk(it)

        if isinstance(parsed, dict):
            _walk(parsed)
            status = parsed.get("review_status")
            score = parsed.get("overall_score")

        if not issues:
            junk_keys = {"severity", "description", "legal_basis", "suggestion",
                         "clause", "reason", "issues", "title", "type", "risk"}
            for m in re.finditer(r'"issues"\s*:\s*\[', raw_text):
                start = m.end() - 1
                depth = 0
                end = len(raw_text) - 1
                for i in range(start, len(raw_text)):
                    ch = raw_text[i]
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                inner = raw_text[start + 1:end]
                # 首选：数组片段本身通常是合法 JSON，整体解析可保留 issue 对象结构
                try:
                    arr = json.loads(f"[{inner}]")
                    for el in arr:
                        if isinstance(el, str):
                            if len(el.strip()) >= 8:
                                issues.append(el.strip())
                        elif isinstance(el, dict):
                            issues.append(el)
                    continue
                except Exception:
                    pass
                # 兜底：正则抓带引号长字符串，过滤 JSON 键名碎片
                for sm in re.finditer(r'"((?:[^"\\]|\\.)*)"', inner):
                    s = sm.group(1).strip()
                    if len(s) >= 30 and s.lower() not in junk_keys:
                        issues.append(s)

        if status is None:
            m = re.search(r'"review_status"\s*:\s*"(pass|warning|fail)"', raw_text)
            status = m.group(1) if m else None
        if score is None:
            m = re.search(r'"overall_score"\s*:\s*(0?\d(?:\.\d+)?)', raw_text)
            if m:
                try:
                    score = float(m.group(1))
                except ValueError:
                    score = None
        return status, score, issues

    def _build_trace(self, agent_name: str, action: str) -> List[Dict[str, Any]]:
        return [
            {"step": "deepagents_root", "status": "success"},
            {"step": agent_name, "status": "success", "action": action},
        ]

    def _to_html(self, text: str) -> str:
        if not text:
            return ""
        return f"<pre>{html.escape(text)}</pre>"

    def _unwrap_drafting_text(self, text: str) -> tuple[str, str, str | None]:
        """解包起草正文文本。

        模型在子代理/多轮链路里偶尔会把整份契约对象再包一层
        ```json 围栏或直接输出成字符串形态（content 变成整段 JSON 文本），
        导致前端正文渲染出 ```json 围栏标记。这里尝试把内层真正的
        契约正文解出来；解不出则剥掉首尾围栏后原样返回。
        返回 (body_text, html_text, title|None)。
        """
        raw = (text or "").strip()
        if not raw:
            return "", "", None
        parsed = self._try_parse_json(raw)
        if isinstance(parsed, dict):
            inner = parsed.get("content") if "content" in parsed else parsed
            if isinstance(inner, dict):
                body = (inner.get("content") or inner.get("text") or "").strip()
                if body:
                    html = inner.get("html_content") or self._to_html(body)
                    return body, html, inner.get("title")
            elif isinstance(inner, str) and inner.strip():
                return inner.strip(), self._to_html(inner), parsed.get("title")
        # 解析失败：剥掉可能的围栏尾巴，避免 ```json 残留在正文里
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        return cleaned or raw, self._to_html(cleaned or raw), None

    def _fallback_contract_text(
        self,
        document_type: str,
        customer_name: str,
        defendant_name: str,
        case_summary: str,
        context: Dict[str, Any],
    ) -> str:
        claim_lines = context.get("claims") or []
        claims_text = "\n".join(f"- {claim}" for claim in claim_lines) if claim_lines else "- 待补充诉讼请求或核心条款"
        return (
            f"{document_type}\n\n"
            f"甲方：{customer_name}\n"
            f"乙方：{defendant_name}\n\n"
            f"案件/合同摘要：{case_summary or '待补充'}\n\n"
            f"核心条款/请求：\n{claims_text}\n\n"
            "事实与理由：待 deepagents 完善生成。"
        )

    @staticmethod
    def _normalize_path(path_value: Path) -> str:
        normalized = path_value.resolve().as_posix()
        if ":" in normalized:
            normalized = normalized.replace(":", "")
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        return normalized
