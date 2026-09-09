---
name: review-report-skill
description: ReviewReportSkill · 审核/分析报告生成
---

# ReviewReportSkill · 审核/分析报告生成

## 功能描述
汇总起草质量、审核风险、诉讼分析结论、修改建议和律师复核提示，生成结构化的审核报告或分析报告。

## 输入参数
- `report_type`: 报告类型（起草质量/审核报告/诉讼分析报告）
- `analysis_results`: 各 Skill 的分析结果（风险清单、逻辑问题、案由分析等）
- `document_content`: 文书原文（可选）

## 执行步骤
### 1. 汇总分析结果
整合风险清单、严重程度、逻辑问题、案由分析等结果。

### 2. 调用大模型生成报告正文
将结构化结果交给大模型生成连贯、专业的报告正文。
**使用MCP工具:** `deepseek_server.chat_completion`

### 3. 组装完整报告
附加法律依据、修改建议和律师复核提示，生成最终报告。

## 输出结果
```json
{
  "report_type": "审核报告",
  "content": "…",
  "risks": [{"severity": "…", "title": "…", "suggestion": "…"}],
  "source": "deepseek_server.chat_completion"
}
```

## 使用的MCP工具
- `deepseek_server`: 报告正文生成

## AI服务
- DeepSeek（deepseek-v4-flash）：报告正文生成

## 性能指标
- 平均耗时: 3s - 10s（大模型生成）
- 主要瓶颈: 大模型推理耗时

