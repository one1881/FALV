/**
 * Approvals API - 审批相关接口
 */

import { get, post } from './client';

/**
 * 审批步骤
 */
export interface ApprovalStep {
  id: number;
  workflow_id: number;
  workflow_public_id?: string;
  workflow_status?: string;
  workflow_submitted_at?: string;
  workflow_completed_at?: string;
  workflow_summary?: string;
  workflow_risk_score?: number;
  workflow_risk_level?: string;
  step_number: number;
  approver_role: string;
  approver_id?: number;
  approver_name?: string;
  reviewer_id?: number;
  reviewer_name?: string;
  review_status_label?: string;
  status: string;
  deadline?: string;
  approved_at?: string;
  submitted_by?: number;
  submitted_by_name?: string;
  completed?: boolean;
  is_completed?: boolean;
  comments?: string;
  created_at: string;
  contract?: {
    id: number;
    contract_number?: string;
    title?: string;
    contract_code: string;
    customer_name?: string;
    amount?: number;
    contract_type?: string;
    status?: string;
    status_label?: string;
    is_completed?: boolean;
    created_by?: number;
    created_by_name?: string;
  };
}

/**
 * 审批列表响应
 */
export interface ApprovalListResponse {
  total: number;
  items: ApprovalStep[];
}

/**
 * 获取审批列表
 */
export async function getApprovals(
  status?: string,
  approverId?: number,
  scope?: 'all' | 'my_pending' | 'my_submitted',
): Promise<ApprovalListResponse> {
  const params = new URLSearchParams();
  if (status) params.append('status', status);
  if (approverId) params.append('approver_id', String(approverId));
  if (scope) params.append('scope', scope);

  const queryString = params.toString();
  const endpoint = queryString ? `/api/approvals?${queryString}` : '/api/approvals';

  return get<ApprovalListResponse>(endpoint);
}

/**
 * 通过审批
 */
export async function approveStep(stepId: number, comments?: string): Promise<any> {
  return post<any>(`/api/approvals/${stepId}/approve`, { comments });
}

/**
 * 驳回审批
 */
export async function rejectStep(stepId: number, comments: string): Promise<any> {
  return post<any>(`/api/approvals/${stepId}/reject`, { comments });
}

export async function getApprovalWorkflow(workflowId: string): Promise<any> {
  return get<any>(`/api/approvals/${workflowId}`);
}

export async function withdrawApproval(workflowId: string): Promise<any> {
  return post<any>(`/api/approvals/${workflowId}/withdraw`);
}
