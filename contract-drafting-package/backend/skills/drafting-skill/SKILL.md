---
name: drafting-skill
description: DraftingSkill · 合同起草与模板生成
---

# DraftingSkill · 合同起草与模板生成

## 功能描述
根据表单信息、主体信息、模板和检索结果，完成合同起草、正文生成、基础格式检查与完整性检查。

## 输入参数
- `case_title`: 文书/合同标题
- `customer_name`: 客户/甲方名称
- `opposite_party`: 对方/乙方名称
- `case_summary`: 业务背景或事实摘要
- `claims`: 起草要求或关键条款列表
- `document_type`: 文书类型（合同/协议/起诉状等）
- `requirements`: 额外起草要求
- `query_text`: 模板/相似文档检索关键词

## 执行步骤
### 1. 采集起草上下文
整理标题、主体、背景、要求，形成统一起草上下文。

### 2. 模板与相似文档检索
根据文书类型和关键词检索模板、相似合同或参考材料。
**使用MCP工具:** `template_server`、`vector_search_server`

### 3. 主体信息补全
必要时补充工商主体信息，提升起草准确度。
**使用MCP工具:** `enterprise_data_server`

### 4. 调用大模型生成正文
基于上下文和模板生成合同正文或诉讼文书正文。
**使用MCP工具:** `qwen_server`

### 5. 基础格式和完整性检查
检查标题、主体、条款、金额、期限、签署信息是否齐全。

## 输出结果
```json
{
  "case_title": "…",
  "content": "…",
  "html_content": "…",
  "summary": "…",
  "quality_check": {"status": "pass|warning", "issues": []}
}
```

## 使用的MCP工具
- `template_server`: 合同/文书模板库
- `vector_search_server`: 相似文档检索
- `enterprise_data_server`: 主体工商信息查询
- `qwen_server`: 文本生成与补全

## AI服务
- Qwen：正文生成与补全

## 性能指标
- 平均耗时: 1s - 5s
- 主要瓶颈: 模型生成与相似检索
