/**
 * API Client - 统一的HTTP客户端
 *
 * 功能:
 * 1. 自动添加Authorization头
 * 2. 自动处理401跳转登录
 * 3. 统一错误处理
 * 4. 支持文件上传
 */

function defaultApiBaseUrl(): string {
  return '';
}

const API_BASE_URL = import.meta.env.VITE_API_URL || defaultApiBaseUrl();
const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api';

function normalizeEndpoint(endpoint: string): string {
  if (endpoint.startsWith('http')) return endpoint;
  if (endpoint.startsWith('/api/v1')) return `${API_PREFIX}${endpoint.slice('/api/v1'.length)}`;
  if (endpoint.startsWith('/api/')) return `${API_PREFIX}${endpoint.slice('/api'.length)}`;
  return endpoint;
}

interface RequestOptions extends RequestInit {
  requireAuth?: boolean;
}

/**
 * 获取访问令牌
 */
function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

/**
 * 获取刷新令牌
 */
function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('refresh_token');
}

/**
 * 保存令牌
 */
function saveTokens(accessToken: string, refreshToken: string) {
  if (typeof window === 'undefined') return;
  localStorage.setItem('access_token', accessToken);
  localStorage.setItem('refresh_token', refreshToken);
}

/**
 * 清除令牌
 */
function clearTokens() {
  if (typeof window === 'undefined') return;
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
}

/**
 * 刷新访问令牌
 */
async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }

  try {
    const response = await fetch(`${API_BASE_URL}${API_PREFIX}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      return false;
    }

    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    return true;
  } catch (error) {
    console.error('Token refresh failed:', error);
    return false;
  }
}

/**
 * 统一的HTTP请求方法
 */
async function request<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const { requireAuth = true, headers = {}, ...rest } = options;

  // 构建完整URL
  const normalizedEndpoint = normalizeEndpoint(endpoint);
  const url = normalizedEndpoint.startsWith('http') ? normalizedEndpoint : `${API_BASE_URL}${normalizedEndpoint}`;

  // 准备请求头
  const requestHeaders: HeadersInit = {
    ...headers,
  };

  // 如果需要认证,添加Authorization头
  if (requireAuth) {
    const token = getAccessToken();
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`;
    }
  }

  // 如果body是对象且不是FormData,自动序列化为JSON
  if (rest.body && !(rest.body instanceof FormData) && typeof rest.body === 'object') {
    requestHeaders['Content-Type'] = 'application/json';
    rest.body = JSON.stringify(rest.body);
  }

  try {
    // 发送请求
    let response = await fetch(url, {
      ...rest,
      headers: requestHeaders,
    });

    // 如果是401且需要认证,尝试刷新令牌
    if (response.status === 401 && requireAuth) {
      const refreshed = await refreshAccessToken();

      if (refreshed) {
        // 重新发送请求
        const newToken = getAccessToken();
        if (newToken) {
          requestHeaders['Authorization'] = `Bearer ${newToken}`;
        }
        response = await fetch(url, {
          ...rest,
          headers: requestHeaders,
        });
      } else {
        // 刷新失败,清除令牌并跳转登录
        clearTokens();
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        throw new Error('Authentication failed');
      }
    }

    // 处理响应
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData.detail ?? errorData.message;
      // detail 可能是对象/数组（如 FastAPI 422 校验错误），直接塞进 Error 会变成 "[object Object]"
      const msg =
        typeof detail === "string" && detail
          ? detail
          : detail
            ? JSON.stringify(detail)
            : `HTTP ${response.status}`;
      throw new Error(msg);
    }

    // 解析响应
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      const data = await response.json();
      // 如果响应包含 { status: "success", data: ... },提取data
      if (data.status === 'success' && data.data !== undefined) {
        return data.data;
      }
      return data;
    }

    return response as any;
  } catch (error: any) {
    console.error('API request failed:', { url, error });
    if (error instanceof TypeError && String(error.message || '').includes('fetch')) {
      throw new Error(`无法连接后端接口：${url}`);
    }
    throw error;
  }
}

/**
 * GET请求
 */
export async function get<T>(endpoint: string, options?: RequestOptions): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'GET' });
}

/**
 * POST请求
 */
export async function post<T>(
  endpoint: string,
  data?: any,
  options?: RequestOptions
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'POST', body: data });
}

/**
 * PUT请求
 */
export async function put<T>(
  endpoint: string,
  data?: any,
  options?: RequestOptions
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'PUT', body: data });
}

/**
 * DELETE请求
 */
export async function del<T>(endpoint: string, options?: RequestOptions): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'DELETE' });
}

/**
 * 文件上传
 */
export async function upload<T>(
  endpoint: string,
  file: File,
  additionalData?: Record<string, any>
): Promise<T> {
  const formData = new FormData();
  formData.append('file', file);

  // 添加额外的表单数据
  if (additionalData) {
    Object.entries(additionalData).forEach(([key, value]) => {
      formData.append(key, value);
    });
  }

  return request<T>(endpoint, {
    method: 'POST',
    body: formData,
  });
}

export async function uploadMany<T>(
  endpoint: string,
  files: File[],
  fieldName = 'files'
): Promise<T> {
  const formData = new FormData();
  files.forEach((file) => formData.append(fieldName, file));

  return request<T>(endpoint, {
    method: 'POST',
    body: formData,
  });
}

/**
 * 导出工具函数
 */
export { saveTokens, clearTokens, getAccessToken, API_BASE_URL, API_PREFIX };
