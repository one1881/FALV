---
name: document-parsing-skill
description: DocumentParsingSkill · 文书结构解析
---

# DocumentParsingSkill · 文书结构解析

## 功能描述
把合同或法律文书拆成结构化片段：标题、当事人、请求事项、事实理由、证据附件和条款段落，为后续风险检查和逻辑检查提供结构化输入。

## 输入参数
- `document_content`: 文书原文（必填）
- `document_type`: 文书类型（合同/起诉状/协议等）
- `file_path`: 文件路径（可选，用于 OCR 场景）

## 执行步骤
### 1. 文本获取
优先使用传入原文；若为图片/扫描件，先调用 OCR 提取文字。
**使用MCP工具:** `mineru_server`（可选，仅扫描件）

### 2. 结构拆分
按标题层级、条款编号、段落特征拆分文书为标题、当事人、正文段落、附件等区块。

### 3. 关键要素提取
提取当事人、金额、期限、标的物等关键要素，标注所在段落位置。

### 4. 输出结构化结果
返回结构化的段落树 + 要素表。

## 输出结果
```json
{
  "sections": [{"title": "…", "content": "…", "level": 1}],
  "parties": ["甲方", "乙方"],
  "key_fields": {"金额": "…", "期限": "…"}
}
```

## 使用的MCP工具
- `mineru_server`: 扫描件 OCR（可选）

## AI服务
- 无（规则解析，不调用大模型；复杂结构可扩展 DeepSeek）

## 性能指标
- 平均耗时: 100ms - 500ms（文本解析）；含 OCR 时 2s - 5s
- 主要瓶颈: OCR 耗时（扫描件场景）

