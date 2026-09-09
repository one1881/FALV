---
name: document-generation-skill
description: DocumentGenerationSkill · 法律文书生成
---

# DocumentGenerationSkill · 法律文书生成

## 功能描述
调用大模型生成合同、协议、起诉状、答辩状、律师函、审核意见和诉讼材料正文。大模型负责内容创作，模板只负责排版与格式，两者解耦。

## 输入参数
- `document_type`: 文书类型（合同/起诉状/律师函等）
- `template_content`: 模板骨架（可选，用于控制格式）
- `case_context`: 案件上下文（当事人、案情、诉求、金额等）
- `requirements`: 补充要求（语气、篇幅、重点条款等）

## 执行步骤
### 1. 组装生成提示词
将文书类型、案件上下文、补充要求组装为结构化 prompt。

### 2. 调用大模型生成正文
调用 DeepSeek 生成文书正文，失败则降级为模板填充。
**使用MCP工具:** `deepseek_server.chat_completion`

### 3. 模板套用与格式化
将生成内容套入模板骨架，统一排版、段落和占位符替换。

### 4. 返回初稿
返回可编辑的文书初稿，附生成来源标记。

## 输出结果
```json
{
  "document_type": "起诉状",
  "content": "…",
  "source": "deepseek_server.chat_completion"
}
```

## 使用的MCP工具
- `deepseek_server`: 大模型正文生成
- `template_server`: 模板骨架（可选）

## AI服务
- DeepSeek（deepseek-v4-flash）：正文内容生成

## 性能指标
- 平均耗时: 3s - 10s（大模型生成）
- 主要瓶颈: 大模型推理耗时

