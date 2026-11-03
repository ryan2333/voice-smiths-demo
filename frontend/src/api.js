export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
let context = { tenantId: '', csrfToken: '', version: 0 };

export function setRequestContext(tenantId = '', csrfToken = '') {
  context = { tenantId, csrfToken, version: context.version + 1 };
}

export function apiUrl(path) {
  return `${API_BASE}${path}`;
}

export async function request(path, options = {}) {
  const snapshot = context;
  const headers = { ...options.headers };
  if (snapshot.tenantId) headers['X-Tenant-ID'] = snapshot.tenantId;
  if (snapshot.csrfToken && !['GET', 'HEAD'].includes(options.method || 'GET')) headers['X-CSRF-Token'] = snapshot.csrfToken;
  const response = await fetch(apiUrl(path), { ...options, headers, credentials: 'include' });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((entry) => entry.msg).join('；') : data.detail;
    if (response.status === 401 && !path.startsWith('/api/auth/') && snapshot.version === context.version) {
      window.dispatchEvent(new Event('voice-smiths:unauthorized'));
    }
    const error = new Error(detail || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

export function jsonRequest(path, body, method = 'POST') {
  return request(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}
