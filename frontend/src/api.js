export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

export function apiUrl(path) {
  return `${API_BASE}${path}`;
}

export async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((entry) => entry.msg).join('；') : data.detail;
    throw new Error(detail || `请求失败 (${response.status})`);
  }
  return data;
}

export function jsonRequest(path, body, method = 'POST') {
  return request(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}
