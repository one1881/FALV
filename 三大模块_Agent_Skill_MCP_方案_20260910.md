# 法律科技系统 · 三大模块 Agent / Skill / MCP 方案

> 版本：2026-09-10
> 依据：`backend/app/services/agent_core.py`、`deepagents_service.py`、`app/a2a_servers/`、`app/mcps/registry.py`、`backend/skills/` 源码实测
> 口径：以下所有名称、数量均以当前代码为准，非设计稿

---

## 一、一句话总览

系统由**一个主控代理 + 两个独立子代理 + 一个共享能力层**构成：

- **Agent 层**：3 个 agent —— 主代理 `legal_deepagents_root`（:8000 进程内）、`drafting-agent`（A2A :8001）、`review-agent`（A2A :8002）。诉讼模块不设子代理，由主代理本体执行。
- **Skill 层**：5 个 skill —— 起草 1 个、审查 4 个（文件即技能，`backend/skills/<name>/SKILL.md`）。
- **MCP 层**：6 个 MCP server —— 合同线 3 个（模板/企业数据/向量检索）+ 证据线 3 个（Qwen/ASR/YOLO）。
- **协议层**：Agent 之间走 **A2A**（Agent Card 发现 + JSON-RPC `message/send`），Agent 调能力走 **MCP**（进程内注册中心 + 统一 `call_tool`）。

三大业务模块与前端入口：

| 模块 | 业务 | 前端路由 |
|---|---|---|
| 一、合同起草 | 表单/主体信息 → 起草正文 → 质量检查 → 审批归档 | `/drafting`、`/drafting/contracts`、`/drafting/editor/:id`、`/approvals` |
| 二、AI 合同审查 | 合同全文 → 穷尽式逐条款扫描 → 风险/逻辑/合规 → 审查报告 | `/review/result`、`/review-management` |
| 三、诉讼支持（证据管理） | 案件受理 → 材料上传 → AI 识别 → 律师确认 → 归档 → 诉讼策略 | `/litigation/new`、`/litigation/evidence` |

---

## 二、Agent 层（3 个）

| Agent 名称 | 部署位置 | 干什么 | 加载的 Skill | 可用工具 |
|---|---|---|---|---|
| `legal_deepagents_root`（主代理 / A2A 主控） | `:8000` 后端进程内（deepagents 官方框架） | 任务入口与总调度。识别任务类型 → 起草/审查走 A2A 派发，诉讼任务本体执行。**只做转发，不改写子代理产物** | 全部 5 个 | `list_skill_documents`、`list_mcp_servers`、`list_mcp_tools`、`call_mcp_tool`、`dispatch_drafting_task`、`dispatch_review_task` |
| `drafting-agent`（起草子代理） | 独立 A2A 服务 `:8001` | 合同起草：模板匹配 → 相似案例检索 → 正文生成 → 基础格式/完整性检查 → 风险概览 | `drafting-skill`（1 个） | MCP 元工具 4 件套（经 `call_mcp_tool` 调能力） |
| `review-agent`（审查子代理） | 独立 A2A 服务 `:8002` | 合同审查：逐条逐款穷尽式扫描，识别结构问题、法律风险、逻辑冲突、合规缺陷 → 输出 issue 清单与审查报告 | `document-parsing-skill`、`legal-risk-check-skill`、`logic-consistency-skill`、`review-report-skill`（4 个） | MCP 元工具 4 件套 |

### A2A 协作机制（要点）

1. **发现**：主代理读子代理 `GET /.well-known/agent-card.json` 拿到 Agent Card（名称、描述、技能列表）。
2. **派发**：`POST /` JSON-RPC 2.0 `message/send`，上下文按 `thread_id` 暂存取回，**不经 LLM 转抄**（避免 JSON 契约被转述破坏）。
3. **回退**：子代理不可达（连不上/超时/协议错）→ 自动在 `:8000` 进程内执行同一套子代理逻辑（`agent_runtime.run_sub_agent_task`，transport=`in-process`），业务不中断。
4. **强约束**：若主代理 LLM 没走派发工具自行作答，系统**强制回退**子代理链路，保证穷尽式审查契约一定生效。
5. **真实失败不重试**：子代理已执行但报错（如模型欠费 Arrearage）→ 直接抛出，不做双倍耗时重试。

### 子代理 Agent Card

| 名称 | 描述 | 技能 ID |
|---|---|---|
| `drafting-agent` | 合同起草子代理：模板匹配、正文起草、相似检索、质量检查与风险评估 | `contract_drafting` |
| `review-agent` | 合同审查子代理：穷尽式逐条款扫描，识别法律风险、逻辑问题与合规问题并生成审查报告 | `contract_review` |

---

## 三、Skill 层（5 个）

Skill = 可被 Agent 加载的领域知识包（目录内含 `SKILL.md`），走 deepagents 虚拟路径 `/skills/<name>` 挂载。

| Skill 名称 | 中文名 | 归属 | 干什么 |
|---|---|---|---|
| `drafting-skill` | 合同起草与模板生成 | drafting-agent | 根据表单信息、主体信息、模板和检索结果完成合同起草、正文生成、格式检查与完整性检查 |
| `document-parsing-skill` | 文书结构解析 | review-agent | 把合同/法律文书拆成结构化片段：标题、当事人、请求事项、事实理由、证据附件、条款段落，为后续检查提供结构化输入 |
| `legal-risk-check-skill` | 法律风险与合规审核 | review-agent | 识别合规风险、条款风险、要素缺失、空白项、风险等级与修改建议（合并法律合规 + 通用合规 + 风险评分 + 条款风险识别） |
| `logic-consistency-skill` | 逻辑一致性检查 | review-agent | 检查案情、诉求、证据、金额口径之间的逻辑冲突：事实矛盾、请求冲突、金额口径不一致、条款闭环不足、证据逻辑问题 |
| `review-report-skill` | 审核/分析报告生成 | review-agent | 汇总起草质量、审核风险、诉讼分析结论、修改建议与律师复核提示，生成结构化审核报告/分析报告 |

**分工逻辑**：起草线 1 个（专精生成），审查线 4 个（解析 → 风险 → 逻辑 → 报告，构成完整审查流水线）。

---

## 四、MCP 层（6 个 Server / 14 个 Tool）

MCP = 能力供给层，进程内单例注册中心（`MCPRegistry`），统一入口 `call_tool(server_name, tool_name, params)`。
对前端/调试暴露 `GET /api/mcp/servers`、`GET /api/mcp/tools`、`POST /api/mcp/{server}/{tool}`。

### 合同线（3 个）

| Server 名称 | 中文名 | 工具（Tool） | 干什么 |
|---|---|---|---|
| `template_server` | 合同模板库与 Jinja2 渲染 | `list_templates`、`get_template`、`render_template` | 列出/获取合同模板（销售、采购、服务、劳动、租赁、保密协议），用 Jinja2 把变量填进 `{{占位符}}` 渲染出合同正文 |
| `enterprise_data_server` | 客户/合同/工商信息数据库查询 | `get_customer`、`list_customers`、`get_contract_metadata`、`get_credit_score`、`get_cache_age` | 查客户工商信息（统一信用代码、法人、联系方式、地址）、合同元数据（类型/金额/状态/风险分）、可解释信用评分，并返回缓存年龄供 Agent 判断是否刷新 |
| `vector_search_server` | 历史合同相似检索 | `search_similar`、`embed_text` | 按合同类型/金额范围/文本相似度检索历史合同，返回 top_k 及相似度分数；提供 128 维文本嵌入 |

### 证据线（3 个）

| Server 名称 | 中文名 | 工具（Tool） | 干什么 |
|---|---|---|---|
| `qwen_server` | Qwen 证据理解与关键信息抽取 | `extract_key_info`、`assess_acceptance` | 按材料类型和解析结果提取关键信息、证明目的与确认项；基于证据目录、时间线、确认结果生成受理评估 |
| `asr_server` | 通义听悟语音转写 | `transcribe_audio` | DashScope `paraformer-v2` 转写录音，本地文件自动上传，长音频按配置切片 |
| `yolo_server` | YOLO 视频抽帧识别 | `analyze_video` | 按间隔抽帧并用 `yolo11s.pt` 识别视频对象与关键帧，输出结果供 Qwen-VL 做二次语义摘要 |

---

## 五、三大模块 × Agent/Skill/MCP 对照

### 模块一：合同起草

| 维度 | 内容 |
|---|---|
| Agent | 主代理 `legal_deepagents_root` → A2A 派发 → `drafting-agent`（:8001） |
| Skill | `drafting-skill` |
| MCP | `template_server`（模板与渲染）、`enterprise_data_server`（当事人/客户主体信息）、`vector_search_server`（相似历史合同） |
| 干什么 | 律师在起草中心填表单 → 主代理派发 → 子代理取模板 + 查主体 + 检索相似合同 → 渲染生成正文 → 质量检查（`pass/warning`）→ 回传结构化 JSON（正文/摘要/质量检查/风险概览）→ 前端编辑器 + 审批流 |

### 模块二：AI 合同审查

| 维度 | 内容 |
|---|---|
| Agent | 主代理 `legal_deepagents_root` → A2A 派发 → `review-agent`（:8002） |
| Skill | `document-parsing-skill` → `legal-risk-check-skill` → `logic-consistency-skill` → `review-report-skill` |
| MCP | `enterprise_data_server`（合同元数据/主体核验）、`vector_search_server`（同类合同参照） |
| 干什么 | 上传/选定合同 → 主代理派发 → 子代理按 8 项检查清单穷尽式扫描（金额一致性、日期逻辑、法条时效、违约金比例、管辖约定、缺失条款、权利义务失衡、签署要件）→ 输出 `issues` 数组（条款定位/严重度/描述/法律依据/修改建议）+ 综合评分 → 生成审查报告供律师复核 |

> 审查子代理的硬约束：`issues` 不设上限、同一条款多个问题分别列条、宁多报不可漏报；输出必须是顶层 `issues` 数组，禁止塞进 `dimensions` 子字段。

### 模块三：诉讼支持（证据管理）

| 维度 | 内容 |
|---|---|
| Agent | **主代理本体执行**（不设独立子代理） |
| Skill | 主代理可用的全部 5 个 skill（按需加载） |
| MCP | `qwen_server`（关键信息抽取/受理评估）、`asr_server`（录音转写）、`yolo_server`（视频抽帧识别） |
| 干什么 | 案件受理 → 材料上传（图片/音频/视频/文书）→ 分类型 AI 识别：图片走 Qwen 多模态抽取（summary/detailed/key_info）、音频走 ASR 转写 + Qwen 归纳、视频走 YOLO 抽帧 + Qwen-VL 二次语义摘要 → 生成确认块 → 律师逐项确认/编辑 → 归档 → 生成诉讼策略与受理评估 |

---

## 六、模型分工（配置入口 `backend/.env`）

| 用途 | 模型 | 配置项 |
|---|---|---|
| 起草 / 审查（A2A 子代理） | `qwen3.7-flash-2026-07-15` | `DRAFT_REVIEW_MODEL` |
| 诉讼 / 文本通用 | `qwen3.7-flash` | `QWEN_MODEL` |
| 图片 / 视频视觉理解 | `qwen3.8-27b` | `QWEN_VL_MODEL` |
| 语音转写 | DashScope `paraformer-v2` | — |
| 视频对象检测 | `yolo11s.pt` | `YOLO_MODEL_PATH` |

---

## 七、支撑机制

| 机制 | 实现 | 作用 |
|---|---|---|
| 短期记忆 | `app/core/checkpoint.py` 的 `build_checkpointer()`（Redis 检查点，进程级单例） | 多轮任务上下文保持；Redis 不可达自动回退 `MemorySaver` |
| 长期记忆 | PG `agent_memories` 表 + 项目宪法 `AGENTS.md` + `runtime/AGENT_MEMORY.md` | 装配期物化 PG → 文件挂载；任务后 `sync_runtime_memory` 文件 → PG 回写 |
| 审批中断 | `interrupt_on={"write_file": True, "delete_file": True}` | 写文件/删文件前中断，交人工审批（对应 `/approvals`） |
| 文件沙箱 | `CompositeBackend` + `FilesystemPermission` | 后端目录读写允许、skill 目录只读 |
| 调用链追踪 | 子代理结果含 `execution_trace`（transport: a2a / in-process） | 前端可展示真实执行路径，A2A 回退可见 |

---

## 八、一页速查表

```
主代理 legal_deepagents_root (:8000, deepagents)
├── dispatch_drafting_task ──A2A──▶ drafting-agent (:8001)
│      skill: drafting-skill
│      MCP  : template_server / enterprise_data_server / vector_search_server
├── dispatch_review_task ───A2A──▶ review-agent (:8002)
│      skill: document-parsing / legal-risk-check / logic-consistency / review-report
│      MCP  : enterprise_data_server / vector_search_server
└── 本体执行 ──▶ 诉讼支持（证据管理）
       skill: 全部 5 个（按需）
       MCP  : qwen_server / asr_server / yolo_server

能力层 MCP 注册中心（6 server / 14 tool）
  合同线：template_server(3) / enterprise_data_server(5) / vector_search_server(2)
  证据线：qwen_server(2) / asr_server(1) / yolo_server(1)
```

**数量口径**：Agent 3 个（1 主控 + 2 子代理）、Skill 5 个（起草 1 + 审查 4）、MCP Server 6 个（合同线 3 + 证据线 3）、MCP Tool 14 个。

---

## 九、需要留意的架构不一致点（供后续优化）

1. **诉讼模块未走 MCP 统一入口**：`litigation_intake_service.py` 直接 `from app.mcps.servers.yolo_server import YoloServer` 后实例化调用 `_analyze_video`，绕过了 `registry.call_tool`。建议统一走注册中心，否则 MCP 层的可观测性/缓存/权限策略在证据线失效。
2. **诉讼模块无独立 Agent**：起草/审查已有 A2A 子代理隔离，诉讼仍由主代理本体跑，与"三大模块对称"的叙事不一致。若答辩/汇报强调架构对称性，可考虑补 `litigation-agent`。
3. **主代理加载全部 5 个 skill**：`build_skill_documents()` 返回全部，起草任务理论上也能看到审查 skill。当前靠 system_prompt 约束，属提示词级而非机制级隔离。
