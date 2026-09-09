/**
 * Contracts API - 合同相关接口
 */

import { get, post, put, del, getAccessToken } from './client';

/**
 * 合同列表查询参数
 */
export interface ContractListParams {
  page?: number;
  page_size?: number;
  status?: string;
  contract_type?: string;
  customer_id?: number;
  search?: string;
}

/**
 * 合同对象
 */
export interface Contract {
  id: number;
  contract_number?: string;
  contract_code?: string;
  customer_id?: number;
  customer_name?: string;
  contract_type: string;
  title?: string;
  amount?: number;
  currency?: string;
  term?: string;
  status: string;
  status_label?: string;
  content?: string;
  file_url?: string;
  created_by?: number;
  created_by_name?: string;
  owner_lawyer_id?: number;
  owner_lawyer_name?: string;
  completed?: boolean;
  is_completed?: boolean;
  created_at: string;
  updated_at?: string;
}

/**
 * 合同详情
 */
export interface ContractDetail extends Contract {
  content?: string;
  html_content?: string;
  risk_report?: any;
  compliance_report?: any;
  similarity_report?: any;
  approval_workflow?: any;
  approval_steps?: any[];
  current_approval_step?: any;
}

/**
 * 合同列表响应
 */
export interface ContractListResponse {
  total: number;
  page: number;
  page_size: number;
  items: Contract[];
}

/**
 * 获取合同列表
 */
export async function getContracts(params: ContractListParams = {}): Promise<ContractListResponse> {
  const queryParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      queryParams.append(key, String(value));
    }
  });

  const queryString = queryParams.toString();
  const endpoint = queryString ? `/api/contracts?${queryString}` : '/api/contracts';

  return get<ContractListResponse>(endpoint);
}

/**
 * 获取合同详情
 */
export async function getContract(id: number): Promise<ContractDetail> {
  return get<ContractDetail>(`/api/contracts/${id}`);
}

/**
 * 更新合同
 */
export async function updateContract(id: number, data: Partial<Contract>): Promise<Contract> {
  return put<Contract>(`/api/contracts/${id}`, data);
}

/**
 * 删除合同
 */
export async function deleteContract(id: number): Promise<void> {
  return del<void>(`/api/contracts/${id}`);
}

/**
 * 从粘贴的合同正文直接创建合同草稿（供审核结果页『提交审核』使用，不跑 AI 生成）
 */
export async function createContractFromContent(data: {
  title: string;
  contract_type: string;
  content: string;
  customer_name?: string;
  amount?: number;
}): Promise<Contract> {
  return post<Contract>('/api/contracts/from-content', data);
}

/**
 * 合同生成请求（对齐后端 ContractGenerateRequest）
 */
export interface ContractGenerateRequest {
  contract_type: string;
  customer_name?: string;
  party_id?: number;
  amount?: number;
  jurisdiction?: string;
  industry?: string;
  description?: string;
  requirements?: string;
  materials_text?: string;
  materials?: Array<{
    name: string;
    size: number;
    type: string;
    text_extracted?: boolean;
  }>;
}

/**
 * 合同生成响应（对齐后端 ContractGenerateResponse）
 */
export interface ContractGenerateResponse {
  contract_id: number;
  contract_number: string;
  content: string;
  html_content: string;
  status: string;
  risk_score?: number;
  risk_level?: string;
  similar_contracts?: number;
  compliance_pass?: boolean;
  risk_dimensions?: Record<string, any>;
  similar_contract_list?: Array<Record<string, any>>;
  compliance_issues?: Array<Record<string, any>>;
  compliance_summary?: Record<string, any>;
  contract_summary?: Record<string, any>;
  data_collection?: Record<string, any>;
  regulation_matches?: Record<string, any>;
  main_model_compliance?: Record<string, any>;
  template_selection?: Record<string, any>;
  workflow_stages?: Array<Record<string, any>>;
  workflow_id?: string;
  approval_workflow?: Record<string, any>;
}

/**
 * 生成合同
 */
export async function generateContract(data: ContractGenerateRequest): Promise<ContractGenerateResponse> {
  return post<ContractGenerateResponse>('/api/contracts/generate', data);
}

export async function submitContractApproval(
  contractId: number,
  data: { summary?: string; risk_score?: number; risk_level?: string } = {},
) {
  return post(`/api/contracts/${contractId}/submit-approval`, data);
}

export async function archiveContract(id: number, reason?: string): Promise<any> {
  return post(`/api/contracts/${id}/archive`, { reason });
}

/**
 * 导出真正的 .docx（后端 python-docx 生成，避免 HTML 伪 .doc 乱码）
 */
export async function downloadContractDocx(title: string, content: string): Promise<{ blob: Blob; filename: string }> {
  const prefix = import.meta.env.VITE_API_PREFIX || "/api";
  const base = import.meta.env.VITE_API_URL || "";
  const token = getAccessToken();
  const res = await fetch(`${base}${prefix}/contracts/export-docx`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: token ? `Bearer ${token}` : "",
    },
    body: JSON.stringify({ title, content }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || "导出失败");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  const filename = m ? decodeURIComponent(m[1]) : "合同.docx";
  return { blob, filename };
}

/**
 * 导出真正的 PDF（后端 reportlab 生成，A4 中文排版，直接下载而非打印）
 */
export async function downloadContractPdf(title: string, content: string): Promise<{ blob: Blob; filename: string }> {
  const prefix = import.meta.env.VITE_API_PREFIX || "/api";
  const base = import.meta.env.VITE_API_URL || "";
  const token = getAccessToken();
  const res = await fetch(`${base}${prefix}/contracts/export-pdf`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: token ? `Bearer ${token}` : "",
    },
    body: JSON.stringify({ title, content }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || "导出 PDF 失败");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/);
  const filename = m ? decodeURIComponent(m[1]) : "合同.pdf";
  return { blob, filename };
}

/**
 * 条款审查
 */
/**
 * 合同对比
 */
/**
 * 风险分析
 */
