/**
 * Litigation API - 诉讼管理相关接口
 *
 * 对齐后端 backend/app/routes/litigation.py（前缀 /api/litigation）
 * 包含：案件列表/详情、各阶段载荷、受理流程（创建/上传/确认/归档）、
 * 文书 .md 单件导出与材料包 .zip 整包导出。
 */

import { get, post, API_BASE_URL, API_PREFIX } from './client';

/* ------------------------------------------------------------------ */
/* 类型定义                                                             */
/* ------------------------------------------------------------------ */

export interface LitigationCaseItem {
  id: number;
  case_id: string;
  case_title?: string;
  case_summary?: string;
  status?: string;
  status_label?: string;
  created_at?: string;
}

export interface LitigationCaseDetail {
  id: number;
  case_id: string;
  case_title?: string;
  case_summary?: string;
  claims?: string[];
  status?: string;
  status_label?: string;
  is_completed?: boolean;
  intake_lawyer_name?: string;
  created_at?: string;
  parties?: Array<{
    id: number;
    party_type?: string;
    entity_type?: string;
    name?: string;
    id_number?: string;
    credit_code?: string;
    address?: string;
    phone?: string;
    enterprise_info?: any;
  }>;
  latest_result?: any;
}

export interface CaseEvidencePayload {
  case?: LitigationCaseDetail;
  summary?: Record<string, any>;
  evidence_catalog?: any[];
  items?: any[];
  extraction_stats?: Record<string, any>;
}

export interface CaseAnalysisPayload {
  case?: LitigationCaseDetail;
  cause?: Record<string, any>;
  jurisdiction?: Record<string, any>;
  risk?: Record<string, any>;
  facts?: any[];
  evidence_catalog?: any[];
  defense_predictions?: any[];
  cross_examination?: any[];
  judge_questions?: any[];
  trial_outline?: Record<string, any>;
  pretrial_package?: Record<string, any>;
}

export interface CaseStagePayload {
  case_id?: string;
  stage?: string;
  status?: string;
  payload?: any;
  updated_at?: string;
  [key: string]: any;
}

export interface IntakeMaterial {
  id?: number;
  material_id: string;
  file_name: string;
  file_type?: string;
  file_size?: number;
  status?: string;
  analysis_text?: string;
  summary?: string;
  evidence_value?: string;
  needs_confirm?: boolean;
  risk_flags?: string[];
  key_facts?: string[];
}

export interface ConfirmationBlock {
  id?: number;
  block_id: string;
  material_id?: string;
  source_file?: string;
  block_type?: string;
  status?: string;
  confirmed_result?: any;
  data?: any;
  created_at?: string;
}

/* ------------------------------------------------------------------ */
/* 案件                                                               */
/* ------------------------------------------------------------------ */

/** 案件列表 */
export async function getLitigationCases(limit = 50): Promise<{ items: LitigationCaseItem[]; total: number }> {
  return get<{ items: LitigationCaseItem[]; total: number }>(`/api/litigation/cases?limit=${limit}`);
}

/** 案件详情 */
export async function getLitigationCase(caseId: string): Promise<LitigationCaseDetail> {
  return get<LitigationCaseDetail>(`/api/litigation/cases/${caseId}`);
}

/** 证据载荷 */
export async function getCaseEvidence(caseId: string): Promise<CaseEvidencePayload> {
  return get<CaseEvidencePayload>(`/api/litigation/cases/${caseId}/evidence`);
}


/* ------------------------------------------------------------------ */
/* 受理流程                                                            */
/* ------------------------------------------------------------------ */

/** 创建受理记录 */
export async function createLitigationIntake(data: {
  source?: string;
  case_type?: string;
  customer_name?: string;
  opposite_party?: string;
}): Promise<{ intake_id: string; status: string }> {
  return post<{ intake_id: string; status: string }>('/api/litigation/intake', data);
}

/** 上传受理材料（文件夹内的多个文件） */
export async function uploadIntakeFiles(intakeId: string, files: File[]): Promise<{
  intake_id: string;
  saved: IntakeMaterial[];
  status: string;
}> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  return post(`/api/litigation/intake/${intakeId}/files`, formData, {
    headers: {} as any,
  } as any);
}

/** 对已上传材料调用真实 AI 分析（图片视觉 / 音频转写 / 字段抽取），生成确认块 */
export async function analyzeIntakeMaterials(intakeId: string): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/materials/analyze`);
}

/** 单文件 AI 分析（逐文件调用，供进度条实时更新） */
export async function analyzeIntakeMaterial(intakeId: string, materialId: string): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/materials/${materialId}/analyze`);
}

/** 受理详情（材料 + 确认块） */
export async function getIntake(intakeId: string): Promise<any> {
  return get<any>(`/api/litigation/intake/${intakeId}`);
}

/** 受理后分析（后端能力，当前前端不直接使用） */
export async function assessIntake(intakeId: string, body: Record<string, any> = {}): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/assess`, body);
}

/** 确认单个确认块 */
export async function confirmIntakeBlock(
  intakeId: string,
  data: { block_id: string; confirmed_result?: any; status?: string },
): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/confirm`, {
    block_id: data.block_id,
    confirmed_result: data.confirmed_result ?? null,
    status: data.status || 'confirmed',
  });
}

/** 保存受理草稿（案件要素） */
export async function saveIntakeDraft(intakeId: string, data: Record<string, any>): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/draft`, data);
}

/** 归档受理：默认新建案件；传 target_case_id 则把材料追加进已有案件小库 */
export async function archiveIntakeCase(
  intakeId: string,
  data: { case_info?: Record<string, any>; assessment?: Record<string, any>; target_case_id?: string } = {},
): Promise<any> {
  return post<any>(`/api/litigation/intake/${intakeId}/archive`, data);
}

/* ------------------------------------------------------------------ */
/* 导出                                                                */
/* ------------------------------------------------------------------ */

/** 下载单个文书 .md */
export async function exportCaseDoc(caseId: string, doc: string): Promise<Response> {
  return get<Response>(`/api/litigation/cases/${caseId}/exports/${doc}.md`);
}


/**
 * 触发浏览器下载（text / blob）
 * @param url 直接走 fetch 的 URL（不经 client，避免 JSON 包装）
 */
export function downloadFromUrl(url: string, fallbackName: string) {
  fetch(url, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
    },
  })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const disposition = res.headers.get('content-disposition') || '';
      const match = disposition.match(/filename="?([^";]+)"?/);
      const filename = match ? match[1] : fallbackName;
      return res.blob().then((blob) => ({ blob, filename }));
    })
    .then(({ blob, filename }) => {
      const urlObj = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = urlObj;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(urlObj);
    })
    .catch((err) => {
      console.error('下载失败:', err);
    });
}

/** 下载 .md 文书（带授权头） */
export function downloadCaseDoc(caseId: string, doc: string, fallbackName: string) {
  downloadFromUrl(`/api/litigation/cases/${caseId}/exports/${doc}.md`, fallbackName);
}

/** 下载证据目录/其他文书为 PDF（reportlab 渲染，支持中文） */
export async function downloadCaseDocPdf(caseId: string, doc: string, fallbackName: string) {
  const token = localStorage.getItem("access_token");
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/litigation/cases/${caseId}/exports/${doc}.pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `PDF 生成失败 (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fallbackName.endsWith(".pdf") ? fallbackName : `${fallbackName}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
}

