# 一律通 · 后端 API 接口文档（草案）

> 文档版本：v0.1（Mock 阶段推导）
> 生成日期：2026-08-22
> 说明：当前前端（React + Vite）处于纯前端 Mock 阶段，**所有接口均未真实对接后端**。本文档依据前端现有 Mock/State 行为推导出**应实现的后端接口契约**，供后端开发对齐使用。前端代码中标注 `数据均为 mock，后续接后端时替换` 的位置即可直接替换为本文档接口。

---

## 1. 通用约定

### 1.1 基础信息

| 项 | 值 |
|----|----|
| 协议 | HTTPS |
| Base URL | `https://api.yilvtong.com`（占位，待定） |
| 数据格式 | `application/json`（除文件上传为 `multipart/form-data`） |
| 时间格式 | ISO 8601（`YYYY-MM-DD HH:mm:ss`） |

### 1.2 鉴权

当前前端登录态由 `sessionStorage["aetheris-local-auth"]` 布尔值模拟，**无真实 token**。后端接入后建议采用：

```
Authorization: Bearer <token>
```

| 字段 | 说明 |
|------|------|
| token | JWT，登录后返回，有效期建议 2h |
| refreshToken | 可选，用于续期 |

### 1.3 统一响应结构

```json
{
  "code": 0,            // 0 成功，非 0 业务错误
  "message": "ok",      // 错误信息
  "data": {}            // 业务数据
}
```

### 1.4 状态码

| HTTP | 含义 |
|------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未登录 / token 失效 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器错误 |

---

## 2. 认证模块（Auth）

### 2.1 登录

`POST /api/auth/login`

**请求体**

```json
{
  "account": "string",     // 账号（手机/邮箱/工号），当前前端校验长度 ≥ 7
  "password": "string"     // 密码，当前前端校验长度 ≥ 7
}
```

**响应 data**

```json
{
  "token": "string",
  "refreshToken": "string",
  "user": {
    "id": "string",
    "name": "string",
    "role": "string"
  }
}
```

**前端对应**：`src/app/auth.ts` `signIn()`、`src/app/pages/Login.tsx:35-47`

### 2.2 登出

`POST /api/auth/logout`

**响应 data**：`{}`

**前端对应**：`src/app/auth.ts` `signOut()`

### 2.3 获取当前用户

`GET /api/auth/me`

**响应 data**：同 2.1 `user` 结构

---

## 3. 合同起草 / 生成（Contract）

### 3.1 生成合同

`POST /api/contract/generate`

**请求体**

```json
{
  "type": "sales | purchase | service | lease",  // 合同类型
  "requirement": "string"                          // 起草要求 / 提示词
}
```

**响应 data**

```json
{
  "contractDraft": "string",          // 合同正文 HTML
  "riskScore": 8.57,                  // 风险评分（0-10，越低越好）
  "riskLevel": "AA",                  // 风险等级
  "similarContracts": 3,              // 相似合同数
  "complianceWarnings": 1,            // 合规预警数
  "warnings": [
    {
      "text": "string",               // 预警描述
      "severity": "warning | danger"  // 严重度
    }
  ]
}
```

**前端对应**：`src/app/pages/ContractNew.tsx:355-369`、`ContractNewForm.tsx:122-171`

### 3.2 获取合同草稿正文

`GET /api/contract/draft/:type`

Query：`prompt=string`（可选，复用起草要求）

**响应 data**

```json
{
  "type": "string",
  "html": "string"          // 合同正文 HTML
}
```

**前端对应**：`src/app/pages/ContractDraft.tsx` `generateMockContract()`、`parsePrompt()`

### 3.3 合同下载（Word / PDF）

`GET /api/contract/:id/download?format=doc|pdf`

- `format=doc` → 返回 `.doc` 文件流
- `format=pdf` → 返回 `.pdf` 文件流（或前端通过 `window.print` 另存）

**前端对应**：`src/app/pages/ContractDraft.tsx`（Word 下载 / PDF 下载按钮）、`ContractManage.tsx`（列表行操作）

---

## 4. 合同管理（Contract Manage）

### 4.1 合同列表

`GET /api/contract/manage`

**Query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| tab | `all \| mine \| pending \| approved` | 列表分桶 |
| keyword | string | 名称搜索 |
| typeFilter | string | 合同类型筛选 |

**响应 data**

```json
{
  "counts": {
    "all": 0,
    "mine": 0,
    "pending": 0,
    "approved": 0
  },
  "list": [
    {
      "id": "string",
      "name": "string",            // 合同名称
      "type": "string",            // 类型中文
      "typeValue": "sales",        // 类型值
      "owner": "string",           // 归属部门/人
      "status": "draft | pending | approved | high-risk",
      "updatedAt": "string",       // 更新时间
      "content": "string"          // 合同正文
    }
  ]
}
```

**前端对应**：`src/app/pages/ContractManage.tsx` `MOCK_CONTRACTS`（:44-115）、`ContractItem`（:26-35）

### 4.2 合同详情

`GET /api/contract/:id`

**响应 data**：同 4.1 单条 `ContractItem`（含 `content`）

### 4.3 起草历史（草稿箱）

`GET /api/contract/drafts`

**响应 data**：同 4.1 `list`（按状态分桶，前端复用 `MOCK_CONTRACTS`）

**前端对应**：`src/app/pages/ContractDrafts.tsx`

---

## 5. 合同审查（Review）

### 5.1 上传并分析

`POST /api/review/analyze`

`multipart/form-data`：

| 字段 | 说明 |
|------|------|
| file | 待审查合同文件 |
| stance | 审查立场（甲方/乙方/中立） |
| mode | 审查模式 |

**响应 data**

```json
{
  "risks": [
    {
      "clause": "string",       // 条款
      "level": "high | mid | low",
      "desc": "string",
      "suggestion": "string"
    }
  ],
  "playbook": [ "string" ],     // 审查要点
  "versionDiff": {}             // 版本差异（可选）
}
```

**前端对应**：`src/app/pages/Review.tsx` `configs`、`standardPlaybook`、`reviewState` 状态机

### 5.2 审查要点库

`GET /api/review/playbook`

**响应 data**：`{ "playbook": ["string"] }`

**前端对应**：`src/app/pages/Review.tsx` `standardPlaybook`（:21-25）

---

## 6. 法规 / 分析（Analysis）

### 6.1 法规检索

`GET /api/law/search`

Query：`q=string`、`bookId=string`（库：法律法规/司法裁判/实务文章）

**响应 data**

```json
{
  "list": [
    { "id": "string", "title": "string", "tags": ["string"] }
  ]
}
```

### 6.2 法规详情

`GET /api/law/:id`

**响应 data**

```json
{
  "id": "string",
  "title": "string",
  "content": "string",
  "cases": [ "string" ],
  "references": [ "string" ],
  "tags": ["string"]
}
```

**前端对应**：`src/app/pages/Analysis.tsx` `DATABASE.laws`（:12-57）、`BOOK_LIBRARIES`（:60-85）

### 6.3 分析统计聚合

`GET /api/analysis/stats`

Query：`searchQuery=string`、`bookId=string`

**响应 data**

```json
{
  "laws": 0,
  "cases": 0,
  "articles": 0,
  "riskClauses": 0,
  "keywords": ["string"],
  "dimensions": [ { "name": "string", "value": 0 } ]
}
```

**前端对应**：`src/app/pages/Analysis.tsx` `buildMockStats()`（:88-108）

---

## 7. 风险总览（Dashboard）

### 7.1 总览统计

`GET /api/dashboard/overview`

**响应 data**

```json
{
  "riskContractTotal": 126,
  "highRisk": 18,
  "pendingReview": 42,
  "resolved": 66
}
```

**前端对应**：`src/app/pages/Dashboard.tsx` `RISK_OVERVIEW`（:103-108）、`ALL_RISK_CONTRACTS`、`PENDING_REVIEW`、`RESOLVED_ITEMS`

### 7.2 风险趋势

`GET /api/dashboard/trend`

**响应 data**

```json
{
  "series": [ { "time": "string", "value": 0 } ]
}
```

**前端对应**：`src/app/pages/Dashboard.tsx` `PERFORMANCE_DATA`（:9-17）

### 7.3 风险拓扑分布

`GET /api/dashboard/risk-distribution`

**响应 data**

```json
{
  "distribution": [
    { "category": "付款", "count": 0 },
    { "category": "履约", "count": 0 },
    { "category": "责任", "count": 0 },
    { "category": "合规", "count": 0 }
  ]
}
```

**前端对应**：`src/app/pages/Dashboard.tsx` `RISK_DATA`（:19-24）

### 7.4 高风险合同列表

`GET /api/dashboard/risk-contracts`

**响应 data**

```json
{
  "total": 18,
  "list": [
    {
      "name": "string",
      "level": "高危 | 中危",
      "owner": "string",
      "issue": "string",
      "time": "string"
    }
  ]
}
```

**前端对应**：`src/app/pages/Dashboard.tsx` `HIGH_RISK_CONTRACTS`（:36-40）、`CONTRACT_RISK_DETAILS`（:78-101）

### 7.5 合同风险详情

`GET /api/contract/:name/risk-detail`

**响应 data**

```json
{
  "score": 0,
  "risks": [
    { "clause": "string", "level": "string", "desc": "string", "suggestion": "string" }
  ]
}
```

**前端对应**：`src/app/pages/Dashboard.tsx` `CONTRACT_RISK_DETAILS`（:78-101）

---

## 8. 待办 / 历史

### 8.1 待复核事项

`GET /api/pending-review`

**响应 data**：`{ "total": 42, "list": [...] }`

**前端对应**：`src/app/pages/Dashboard.tsx` `PENDING_REVIEW`（:54-63）

### 8.2 已处置事项

`GET /api/resolved`

**响应 data**：`{ "total": 66, "list": [...] }`

**前端对应**：`src/app/pages/Dashboard.tsx` `RESOLVED_ITEMS`（:66-75）

---

## 9. 接口清单速查

| 方法 | 路径 | 说明 | 前端来源 |
|------|------|------|----------|
| POST | `/api/auth/login` | 登录 | auth.ts / Login.tsx |
| POST | `/api/auth/logout` | 登出 | auth.ts |
| GET | `/api/auth/me` | 当前用户 | auth.ts |
| POST | `/api/contract/generate` | 生成合同 | ContractNew / ContractNewForm |
| GET | `/api/contract/draft/:type` | 草稿正文 | ContractDraft |
| GET | `/api/contract/:id/download` | 下载 Word/PDF | ContractDraft / ContractManage |
| GET | `/api/contract/manage` | 合同列表 | ContractManage |
| GET | `/api/contract/:id` | 合同详情 | ContractManage |
| GET | `/api/contract/drafts` | 草稿箱 | ContractDrafts |
| POST | `/api/review/analyze` | 上传审查 | Review |
| GET | `/api/review/playbook` | 审查要点库 | Review |
| GET | `/api/law/search` | 法规检索 | Analysis |
| GET | `/api/law/:id` | 法规详情 | Analysis |
| GET | `/api/analysis/stats` | 分析统计 | Analysis |
| GET | `/api/dashboard/overview` | 总览 | Dashboard |
| GET | `/api/dashboard/trend` | 风险趋势 | Dashboard |
| GET | `/api/dashboard/risk-distribution` | 风险分布 | Dashboard |
| GET | `/api/dashboard/risk-contracts` | 高风险列表 | Dashboard |
| GET | `/api/contract/:name/risk-detail` | 风险详情 | Dashboard |
| GET | `/api/pending-review` | 待复核 | Dashboard |
| GET | `/api/resolved` | 已处置 | Dashboard |

---

## 10. 后端接入注意事项

1. **鉴权**：当前前端无 token，接入时需引入 Bearer Token，并在 `ProtectedRoute` 中校验。
2. **Mock 替换点**：全局搜索 `MOCK_`、`buildMockStats`、`simulateGeneration`、`generationResult` 即可定位所有需替换为真实请求的位置。
3. **分页**：列表类接口（4.1 / 4.3 / 7.4）建议补充 `page`、`pageSize` 分页参数。
4. **流式生成**：`/api/contract/generate` 当前前端用 `setTimeout/setInterval` 模拟进度，后端可用 SSE / WebSocket 推送 `progress` 与 `logs`。
5. **错误码**：统一使用第 1.3 / 1.4 节约定，前端按 `code !== 0` 提示。
