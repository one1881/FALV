---
name: enterprise-query-skill
description: EnterpriseQuerySkill · 企业信息查询
---

# EnterpriseQuerySkill · 企业信息查询

## 功能描述
查询客户、原告、被告等企业主体的工商信息和基础信用/风险信息，为案件主体真实性核验和诉讼材料准备提供数据支撑。

## 输入参数
- `enterprise_name`: 企业名称（必填）
- `query_type`: 查询类型（工商基础/信用/风险，默认工商基础）

## 执行步骤
### 1. 校验输入
检查企业名称是否为空，为空则跳过查询并返回空结果。

### 2. 调用企业数据服务
通过 `enterprise_data_server` 查询工商注册、经营状态、法人等基础信息。

### 3. 结果归一化
将查询结果转换为统一的主体信息结构（名称、信用代码、法人、状态）。

## 输出结果
```json
{
  "enterprise_name": "…",
  "credit_code": "…",
  "legal_person": "…",
  "status": "…"
}
```

## 使用的MCP工具
- `enterprise_data_server`: 企业工商/信用数据查询

## AI服务
- 无（外部数据查询，不调用大模型）

## 性能指标
- 平均耗时: 500ms - 2s（依赖外部数据服务）
- 主要瓶颈: 外部数据接口响应

