/**
 * Stats API - 统计相关接口
 */

import { get } from './client';

/**
 * Dashboard统计数据
 */
export interface DashboardStats {
  contracts: {
    total: number;
    this_month: number;
    last_month: number;
    growth_rate: number;
    by_status: Record<string, number>;
    this_month_amount: number;
  };
  approvals: {
    pending: number;
    approved_this_month: number;
    rejected_this_month: number;
    overdue: number;
  };
  customers: {
    total: number;
    new_this_month: number;
    risky_customers: number;
  };
  recent_contracts: any[];
  pending_items: {
    drafts: number;
    pending_approvals: number;
    reviewing_contracts: number;
  };
  generated_at: string;
}

/**
 * 获取Dashboard统计数据
 */
export async function getDashboardStats(): Promise<DashboardStats> {
  return get<DashboardStats>('/api/stats/dashboard');
}
