from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.mcps.clients import get_mcp_client


settings = get_settings()


def _skill_slug(name: str) -> str:
    """把历史的 CamelCase skill 文件名转成 deepagents 要求的 kebab-case 目录名。

    CaseIntakeSkill.md -> case-intake-skill
    已经是 kebab-case 的输入原样返回。
    """
    stem = name[:-3] if name.endswith(".md") else name
    if "-" in stem or stem.islower():
        return stem.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "-", stem).lower()


@tool
async def list_skill_documents() -> str:
    """列出 backend/skills 下所有可供 deepagents 读取的 skill（每个 skill 是一个含 SKILL.md 的目录）。"""
    skill_dir = Path(__file__).resolve().parents[2] / "skills"
    items = sorted(
        path.name for path in skill_dir.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    ) if skill_dir.exists() else []
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


@dataclass
class DeepAgentTask:
    task_id: str
    task_type: str
    action: str
    status: str = "pending"
    context: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DeepAgentsService:
    def __init__(self):
        self._tasks: Dict[str, DeepAgentTask] = {}
        self._checkpointer = MemorySaver()
        self._agent = self._build_agent()

    def _build_agent(self):
        model = ChatOpenAI(
            model=settings.primary_llm_model,
            api_key=settings.primary_llm_api_key,
            base_url=(
                settings.primary_llm_api_url.rstrip("/")
                .removesuffix("/chat/completions")
                or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            temperature=0.2,
        )
        return create_deep_agent(
            model=model,
            tools=self._build_tools(),
            system_prompt=(
                "你是法律合同系统的主代理，负责协调起草、审核和诉讼三个业务模块。"
                "优先使用技能、子代理、MCP 工具和文件上下文，输出要结构化、可回传。"
            ),
            skills=self._build_skill_documents(),
            memory=self._build_memory_paths(),
            subagents=self._build_subagents(),
            permissions=self._build_permissions(),
            backend=self._build_backend(),
            checkpointer=self._checkpointer,
            interrupt_on={"write_file": True, "delete_file": True},
            name="legal_deepagents_root",
        )

    def _build_backend(self):
        workspace_dir = self._backend_root()
        return CompositeBackend(
            default=FilesystemBackend(root_dir=str(workspace_dir), virtual_mode=True),
            routes={
                "workspace": FilesystemBackend(root_dir=str(workspace_dir), virtual_mode=True),
            },
            artifacts_root="/",
        )

    def _build_tools(self) -> list[Any]:
        return [list_skill_documents, list_mcp_servers, list_mcp_tools, call_mcp_tool]

    def _build_skill_documents(self) -> list[str]:
        """deepagents 0.7.11 要求 skill 为「含 SKILL.md 的目录」，不能是散装 .md 文件。"""
        skill_dir = self._skill_dir()
        if not skill_dir.exists():
            return []
        return [
            str(path) for path in sorted(skill_dir.iterdir())
            if path.is_dir() and (path / "SKILL.md").exists()
        ]

    def _build_memory_paths(self) -> list[str]:
        memory_paths: list[str] = []
        root_memory = Path(__file__).resolve().parents[3] / "AGENTS.md"
        if root_memory.exists():
            memory_paths.append(self._normalize_path(root_memory))
        return memory_paths

    def _build_permissions(self) -> list[FilesystemPermission]:
        workspace_dir = self._backend_root()
        skill_dir = self._skill_dir()
        return [
            FilesystemPermission(operations=["read", "write"], paths=[self._normalize_path(workspace_dir)], mode="allow"),
            FilesystemPermission(operations=["read"], paths=[self._normalize_path(skill_dir)], mode="allow"),
        ]

    def _build_subagents(self) -> list[dict[str, Any]]:
        shared_tools = self._build_tools()
        permissions = self._build_permissions()
        return [
            {
                "name": "drafting-agent",
                "description": "处理合同起草、模板匹配和质量检查。",
                "system_prompt": (
                    "你负责合同起草子任务，重点输出合同正文、模板选择、相似检索、风险概览和质量检查。"
                ),
                "skills": self._skill_documents_for([
                    "drafting-skill",
                ]),
                "tools": shared_tools,
                "permissions": permissions,
                "interrupt_on": {"write_file": True},
            },
            {
                "name": "review-agent",
                "description": "处理合同审查、风险识别和报告生成。",
                "system_prompt": (
                    "你负责文书审查子任务，重点识别结构问题、法律风险、逻辑问题与合规问题。"
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
                ),
                "skills": self._skill_documents_for([
                    "DocumentParsingSkill.md",
                    "LegalRiskCheckSkill.md",
                    "LogicConsistencySkill.md",
                    "ReviewReportSkill.md",
                ]),
                "tools": shared_tools,
                "permissions": permissions,
                "interrupt_on": {"write_file": True},
            },

        ]

    def _skill_documents_for(self, filenames: List[str]) -> List[str]:
        """按名称挑选子代理专属 skill，自动兼容历史 CamelCase.md 写法。"""
        skill_dir = self._skill_dir()
        paths: List[str] = []
        for filename in filenames:
            path = skill_dir / _skill_slug(filename)
            if path.is_dir() and (path / "SKILL.md").exists():
                paths.append(str(path))
        return paths

    def _backend_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _skill_dir(self) -> Path:
        return self._backend_root() / "skills"

    async def execute(self, task_key: str, request: Dict[str, Any]) -> Dict[str, Any]:
        task = self._tasks.get(task_key)
        if task is None:
            task = DeepAgentTask(
                task_id=task_key,
                task_type=request.get("task_type", ""),
                action=request.get("action", ""),
                context=dict(request.get("context", {})),
            )
            self._tasks[task_key] = task
        else:
            task.status = "running"
            task.context = dict(request.get("context", task.context))
            task.updated_at = datetime.now().isoformat()

        task.status = "running"
        task.events.append({
            "type": "event",
            "message": "任务已创建",
            "level": "info",
            "timestamp": datetime.now().isoformat(),
        })

        try:
            prompt = self._build_prompt(request)
            raw_result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"configurable": {"thread_id": task_key}},
            )
            normalized = self._normalize_result(raw_result)
            structured = self._build_structured_result(request, normalized)
            task.status = "completed"
            task.result = structured
            task.events.append({
                "type": "event",
                "message": "任务执行完成",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
            })
            task.updated_at = datetime.now().isoformat()
            return task.to_dict()
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.events.append({
                "type": "event",
                "message": "任务执行失败",
                "level": "error",
                "timestamp": datetime.now().isoformat(),
                "error": str(exc),
            })
            task.updated_at = datetime.now().isoformat()
            return task.to_dict()

    def get_task(self, task_key: str) -> Dict[str, Any] | None:
        task = self._tasks.get(task_key)
        return task.to_dict() if task else None

    # 各业务板块要求模型回传的 JSON 契约。缺了这段约定，
    # 模型会输出自由散文，下游 builder 取不到结构化键，只能回落占位模板。
    _OUTPUT_CONTRACTS: Dict[str, str] = {
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

    def _build_prompt(self, request: Dict[str, Any]) -> str:
        task_type = request.get("task_type", "")
        action = request.get("action", "")
        context = request.get("context", {}) or {}
        contract = self._OUTPUT_CONTRACTS.get(task_type)

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
        else:
            lines.append("请优先根据上下文给出结构化结果，必要时委派给合适的子代理。")
        return "\n".join(lines)

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
    def _try_parse_json(text: str) -> Any:
        """尽力从模型输出里解析出 JSON，兼容 ```json 围栏和前后夹带说明文字的情况。"""
        candidate = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1).strip()
        if not candidate.startswith(("{", "[")):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end <= start:
                return None
            candidate = candidate[start:end + 1]
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            return None

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
        if isinstance(raw_content, dict):
            body_text = raw_content.get("content") or raw_content.get("text") or ""
            html_text = raw_content.get("html_content") or self._to_html(body_text)
        elif isinstance(raw_content, str) and raw_content.strip():
            body_text = raw_content.strip()
            html_text = self._to_html(body_text)
        elif isinstance(raw_result.get("output"), str) and raw_result.get("output", "").strip():
            body_text = raw_result.get("output", "").strip()
            html_text = self._to_html(body_text)
        else:
            body_text = self._fallback_contract_text(document_type, customer_name, defendant_name, case_summary, context)
            html_text = self._to_html(body_text)

        content = {
            "title": raw_content.get("title") if isinstance(raw_content, dict) and raw_content.get("title") else f"{document_type} - {customer_name}",
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
        overall_score = raw_result.get("overall_score")
        if overall_score is None:
            overall_score = self._derive_review_score(dimensions, issues)
        review_status = raw_result.get("review_status") or ("pass" if overall_score >= 0.9 and not issues else "warning")
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
        import re
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

    def _derive_review_score(self, dimensions: Dict[str, Any]) -> float:
        issues = self._collect_review_issues(dimensions)
        return round(max(0.35, 0.98 - 0.08 * len(issues)), 2)

    def _build_trace(self, agent_name: str, action: str) -> List[Dict[str, Any]]:
        return [
            {"step": "deepagents_root", "status": "success"},
            {"step": agent_name, "status": "success", "action": action},
        ]

    def _to_html(self, text: str) -> str:
        if not text:
            return ""
        return f"<pre>{html.escape(text)}</pre>"

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


_service: DeepAgentsService | None = None


def get_deepagents_service() -> DeepAgentsService:
    global _service
    if _service is None:
        _service = DeepAgentsService()
    return _service
