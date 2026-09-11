import { get, post } from './client';

/** 提取上传文档正文（.txt/.docx/.pdf；.doc 老格式会返回明确提示） */
export async function extractDocumentText(filename: string, base64: string): Promise<{ content: string; chars?: number }> {
  return post<{ content: string; chars?: number }>('/api/review/extract-text', { filename, base64 });
}

export interface ReviewDocumentRequest {
  document_type?: string;
  contract_id?: number;
  content: string;
  title?: string;
  context?: Record<string, any>;
}

export interface ReviewIssue {
  type: string;
  severity: 'high' | 'medium' | 'low' | string;
  clause?: string;
  /** 问题描述：这块有什么问题 */
  description: string;
  /** 风险理由/原因：为什么有问题、有什么风险 */
  reason?: string;
  /** 法律依据：引用的法条 / 条款依据 */
  legal_basis?: string;
  /** 修改建议：建议怎么改 */
  suggestion: string;
}

export interface ReviewDimension {
  score: number;
  level?: string;
  summary?: string;
  issues?: ReviewIssue[];
}

export interface ReviewDocumentResponse {
  review_status?: string;
  overall_score?: number;
  dimensions?: Record<string, ReviewDimension>;
  issues?: ReviewIssue[];
  suggestions?: string[];
  parsed_document?: Record<string, any>;
  agents_executed?: string[];
  skills_used?: string[];
  mcp_tools_used?: string[];
  execution_trace?: any[];
  [key: string]: any;
}

export async function reviewDocument(data: ReviewDocumentRequest): Promise<ReviewDocumentResponse> {
  return post<ReviewDocumentResponse>('/api/review/review-document', data);
}

/** 审核任务快照（轮询返回） */
export interface ReviewTaskSnapshot {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  error?: string | null;
  result?: ReviewDocumentResponse | null;
  events?: { message: string; timestamp: string; level?: string }[];
  created_at?: string;
  updated_at?: string;
  review_record_id?: number | null;
  record_created?: boolean;
}

/** 异步提交审核：立即返回 task_key，规避浏览器/代理对分钟级同步请求的超时限制 */
export function startReviewDocumentAsync(data: ReviewDocumentRequest) {
  return post<{ task_key: string; status: string; poll_url: string }>('/api/review/review-document-async', data);
}

/** 轮询审核任务快照 */
export function getReviewTask(taskKey: string) {
  return get<ReviewTaskSnapshot>(`/api/review/tasks/${encodeURIComponent(taskKey)}`);
}

/** 历史审查记录（一条 = 一次 AI 审查的完整结果） */
export interface ReviewRecordItem {
  id: number;
  review_id: string;
  contract_id: number | null;
  document_type: string | null;
  review_status: string;
  review_status_label: string;
  is_completed: boolean;
  reviewer_name: string | null;
  overall_score: number | null;
  issues: ReviewIssue[] | null;
  suggestions: string[] | null;
  dimensions: Record<string, any> | null;
  parsed_document?: Record<string, any>;
  agents_executed?: string[];
  skills_used?: string[];
  mcp_tools_used?: string[];
  execution_trace?: any[];
  reviewed_at: string | null;
}

export async function getReviewRecords(options?: { contractId?: number; limit?: number }): Promise<ReviewRecordItem[]> {
  const params = new URLSearchParams();
  if (options?.contractId != null) params.set("contract_id", String(options.contractId));
  if (options?.limit != null) params.set("limit", String(options.limit));
  const qs = params.toString();
  const resp = await get<{ status: string; total: number; records: ReviewRecordItem[] }>(`/api/review/records${qs ? `?${qs}` : ""}`);
  return resp.records || [];
}

/** 把历史记录还原成结果页可直接渲染的 ReviewDocumentResponse */
export function recordToResponse(record: ReviewRecordItem): ReviewDocumentResponse {
  return {
    review_status: record.review_status,
    overall_score: record.overall_score ?? undefined,
    dimensions: record.dimensions || undefined,
    issues: record.issues || [],
    suggestions: record.suggestions || [],
    parsed_document: record.parsed_document,
    agents_executed: record.agents_executed,
    skills_used: record.skills_used,
    mcp_tools_used: record.mcp_tools_used,
    execution_trace: record.execution_trace,
  };
}
