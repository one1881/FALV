/**
 * Auth API - 认证相关接口
 */

import { get, post, saveTokens, clearTokens } from './client';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: number;
    username: string;
    full_name: string;
    email?: string;
    role: string;
    department?: string;
  };
}

/**
 * 用户登录
 */
export async function login(credentials: LoginRequest): Promise<LoginResponse> {
  const response = await post<LoginResponse>('/api/auth/login', credentials, {
    requireAuth: false,
  });

  // 保存令牌和用户信息
  saveTokens(response.access_token, response.refresh_token);
  if (typeof window !== 'undefined') {
    localStorage.setItem('user', JSON.stringify(response.user));
  }

  return response;
}

/**
 * 用户登出
 */
export function logout() {
  clearTokens();
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}

/**
 * 从后端获取当前用户信息
 */
export async function fetchCurrentUser() {
  return get('/api/auth/me');
}

/**
 * 获取当前用户信息
 */
export function getCurrentUser() {
  if (typeof window === 'undefined') return null;
  const userStr = localStorage.getItem('user');
  if (!userStr) return null;

  try {
    return JSON.parse(userStr);
  } catch {
    return null;
  }
}

/**
 * 检查是否已登录
 */
export function isAuthenticated(): boolean {
  if (typeof window === 'undefined') return false;
  return !!localStorage.getItem('access_token');
}
