---
name: template-retrieval-skill
description: TemplateRetrievalSkill · 模板与相似文档检索
---

# TemplateRetrievalSkill · 模板与相似文档检索

## 功能描述
统一查找法律文书模板、相似合同、相似条款、相似案例和历史参考材料，为起草和诉讼分析提供参考依据。基于 BGE 语义向量做相似度检索，支持按类型和金额范围过滤。

## 输入参数
- `query_text`: 待检索的正文/摘要（必填）
- `contract_type`: 可选，限定合同类型
- `amount_min` / `amount_max`: 可选，金额范围
- `top_k`: 返回条数，默认 5
- `min_similarity`: 最小相似度阈值

## 执行步骤
### 1. 文本向量化
将查询文本用 BGE 模型编码为 512 维语义向量。
**使用MCP工具:** `vector_search_server.embed_text`

### 2. 相似检索
按类型/金额过滤后，计算查询向量与历史文档向量的余弦相似度，取 top_k。
**使用MCP工具:** `vector_search_server.search_similar`

### 3. 模板匹配
若需具体文书模板，从模板库返回匹配的模板骨架。
**使用MCP工具:** `template_server`

### 4. 结果排序与返回
按相似度降序返回，附相似度分数和文档摘要。

## 输出结果
```json
{
  "total_found": 5,
  "similar_contracts": [{"contract_id": 1, "title": "…", "similarity_score": 0.87}]
}
```

## 使用的MCP工具
- `vector_search_server`: 语义向量检索（BGE 512 维）
- `template_server`: 法律文书模板库

## AI服务
- 无（向量检索 + 模板匹配，不调用大模型）

## 性能指标
- 平均耗时: 300ms - 1s（含 BGE 编码）
- 主要瓶颈: BGE 模型编码耗时（已做向量缓存优化）

