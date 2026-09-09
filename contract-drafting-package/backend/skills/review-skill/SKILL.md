---
name: review-skill
description: ReviewSkill · 合同审核与风险分析
---

# ReviewSkill · 合同审核与风险分析

## 功能描述
对合同正文或法律文书进行结构解析、法律风险识别、逻辑一致性检查和审核报告生成。

## 输入参数
- `document_content`: 待审核正文（必填）
- `context`: 案件上下文（可选）
- `check_type`: 检查类型（合同审核/文书审核）
- `report_type`: 报告类型（审核报告/风险报告）

## 执行步骤
### 1. 文书结构解析
拆分标题、主体、条款、附件和关键段落。
**使用MCP工具:** `mineru_server`（扫描件场景可选）

### 2. 法律风险识别
识别违约金、管辖、责任范围、付款条件、空白项等高风险内容。
**使用MCP工具:** `legal_data_server`

### 3. 逻辑一致性检查
检查条款之间、正文与上下文之间的冲突、闭环和金额口径问题。

### 4. 相似条款/历史参考检索
参考历史条款、类似审核意见或范本。
**使用MCP工具:** `vector_search_server`

### 5. 调用大模型生成审核建议
生成问题清单、修改建议和审核报告。
**使用MCP工具:** `qwen_server`

## 输出结果
```json
{
  "review_status": "pass|warning|fail",
  "overall_score": 0.85,
  "issues": [{"clause": "…", "severity": "high", "description": "…", "suggestion": "…"}],
  "suggestions": ["…"],
  "report": "…"
}
```

## 使用的MCP工具
- `mineru_server`: 扫描件/附件 OCR
- `legal_data_server`: 法规与法条依据
- `vector_search_server`: 相似条款和历史审核参考
- `qwen_server`: 审核分析与报告生成

## AI服务
- Qwen：风险判断、建议生成、报告汇总

## 性能指标
- 平均耗时: 1s - 5s
- 主要瓶颈: 模型推理与法规检索
