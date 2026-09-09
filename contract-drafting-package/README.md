# 法律 AI 辅助系统 · 最终版

这是从原项目迁移出的干净最终版目录，只保留当前主业务和最终架构口径所需代码。

## 最终架构口径

- 三大功能模块：合同/文书起草、合同/文书审核、诉讼管理。
- Agent：1 个总调度 + 3 个功能 Coordinator + 5 个业务 Agent。
- Skills：保留可复用业务能力，细步骤不再额外拆 Agent。
- MCP：默认只保留 5 个核心 MCP Server。

## Agent

```text
CoordinatorAgent
├── DocumentDraftingCoordinator
│   └── DocumentDraftingAgent
├── ReviewCoordinator
│   └── ReviewAnalysisAgent
└── LitigationCoordinator
    ├── MaterialAnalysisAgent
    ├── EvidenceOrganizerAgent
    ├── EvidenceAgent
    └── LitigationAnalysisAgent
```

## 核心 MCP

- `deepseek_server`
- `template_server`
- `legal_data_server`
- `enterprise_data_server`
- `vector_search_server`

接口 `/api/mcp/tools` 默认只展示核心 MCP 工具。

## 目录

```text
frontend/   React + TypeScript 前端
backend/    FastAPI 后端、Agent、Skills、MCP、业务服务
docs/       项目文档
最终架构设计方案.md
```

## 启动后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端健康检查：`http://localhost:8000/health`

## 启动前端

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

前端地址：`http://localhost:5173`

## 验证

本目录已执行过：

```bash
cd backend && python -m compileall app
cd frontend && npm install --no-audit --no-fund && npm run build
```

后端编译通过，前端构建通过。Vite 仅提示单个 chunk 超过 500 kB，不影响运行。
