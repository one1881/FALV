/**
 * Customers API - 客户相关接口
 */

import { get } from './client';

/**
 * 客户对象
 */
export interface Customer {
  id: number;
  name: string;
  code?: string;
  contact_person?: string;
  phone?: string;
  email?: string;
  address?: string;
  legal_representative?: string;
  unified_social_credit_code?: string;
  notes?: string;
  created_at?: string;
}

/**
 * 客户列表响应
 */
export interface CustomerListResponse {
  total: number;
  page: number;
  page_size: number;
  items: Customer[];
}

/**
 * 获取客户列表
 */
export async function getCustomers(search?: string): Promise<CustomerListResponse> {
  const endpoint = search ? `/api/customers?search=${encodeURIComponent(search)}` : '/api/customers';
  return get<CustomerListResponse>(endpoint);
}

/**
 * 获取客户详情
 */
export async function getCustomer(id: number): Promise<Customer> {
  return get<Customer>(`/api/customers/${id}`);
}
