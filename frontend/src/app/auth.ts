/**
 * Authentication Module - 对接真实的JWT认证
 *
 * 已迁移到使用真实API: /api/auth/login
 * Token存储在localStorage
 */

import * as authAPI from '../lib/api/auth';

export const AUTH_STORAGE_KEY = "aetheris-local-auth";

/**
 * 检查是否已登录
 */
export function isAuthenticated(): boolean {
  return authAPI.isAuthenticated();
}

/**
 * 用户登录 (对接真实API)
 */
export async function signIn(username: string, password: string): Promise<void> {
  try {
    await authAPI.login({ username, password });
    // 为了向后兼容,也设置sessionStorage
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem(AUTH_STORAGE_KEY, "true");
    }
  } catch (error) {
    console.error('Login failed:', error);
    throw error;
  }
}

/**
 * 用户登出
 */
export function signOut(): void {
  authAPI.logout();
  if (typeof window !== 'undefined') {
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

/**
 * 获取当前用户
 */
export function getCurrentUser() {
  return authAPI.getCurrentUser();
}
