import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SessionApp from './SessionApp';
import { setRequestContext } from './api';

let loggedIn;
let tenants;
let members;
const user = { id: 'reader', email: 'reader@example.com', display_name: '读者' };

function response(data, status = 200) {
  return { ok: status < 400, status, json: async () => structuredClone(data) };
}

function project(tenantId) {
  const content = tenantId === 'space-a' ? '甲空间的故事' : '乙空间的故事';
  return { id: `${tenantId}-project`, title: `${tenantId}小说`, encoding: 'utf-8', chapter_count: 1, roles: [], voice_map: {}, chapters: [{ number: 1, title: '初见', segments: [{ id: 1, speaker: '旁白', text: content }] }] };
}

beforeEach(() => {
  setRequestContext();
  localStorage.clear();
  loggedIn = false;
  tenants = [{ id: 'space-a', name: '甲工作空间', role: 'owner' }, { id: 'space-b', name: '乙工作空间', role: 'admin' }];
  members = [{ ...user, role: 'owner' }];
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    const tenantId = options.headers?.['X-Tenant-ID'] || 'space-a';
    if (path === '/api/auth/me') return loggedIn ? response({ user, tenants, csrf_token: 'session-csrf' }) : response({ detail: '请先登录' }, 401);
    if (['/api/auth/register', '/api/auth/login'].includes(path)) { loggedIn = true; return response({ user, tenants, csrf_token: 'session-csrf' }); }
    if (path === '/api/auth/logout') { loggedIn = false; return response({ ok: true }); }
    if (path === '/api/voices') return response({ voices: [] });
    if (path === '/api/config') return response({ upload_dir: `/data/uploads/${tenantId}`, audio_dir: `/data/audio/${tenantId}`, data_dir: '/data', workers: 2 });
    if (path === '/api/projects') return response({ projects: tenantId === 'new-space' ? [] : [project(tenantId)] });
    if (path === `/api/projects/${tenantId}-project`) return response(project(tenantId));
    if (path === '/api/jobs') return response({ jobs: [] });
    if (path === '/api/tenants' && options.method === 'POST') {
      const created = { id: 'new-space', name: JSON.parse(options.body).name, role: 'owner' };
      tenants = [...tenants, created];
      return response(created, 201);
    }
    if (path === `/api/tenants/${tenantId}/members`) {
      if (options.method === 'POST') members.push({ id: 'new-member', email: JSON.parse(options.body).email, display_name: '新成员', role: 'member' });
      return response(options.method ? { ok: true } : { members });
    }
    if (path === `/api/tenants/${tenantId}/members/new-member` && options.method === 'DELETE') {
      members = members.filter((member) => member.id !== 'new-member');
      return response({ ok: true });
    }
    throw new Error(`Unexpected request ${path}`);
  }));
});

afterEach(() => { setRequestContext(); vi.unstubAllGlobals(); });

async function login(expectedStory = '甲空间的故事') {
  await screen.findByRole('button', { name: '登录工作空间' });
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: user.email } });
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'test-password-123' } });
  fireEvent.click(screen.getByRole('button', { name: '登录工作空间' }));
  await screen.findByText(expectedStory);
}

describe('accounts and tenants', () => {
  it('switches themes from login and settings while keeping the account choice across tenant changes', async () => {
    render(<SessionApp />);
    await screen.findByRole('button', { name: '登录工作空间' });
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'paper' } });
    expect(document.documentElement).toHaveAttribute('data-theme', 'paper');
    await login();
    fireEvent.click(screen.getByRole('button', { name: /存储与设置/ }));
    fireEvent.click(screen.getByRole('radio', { name: /午夜深色/ }));
    expect(screen.getByLabelText('界面主题')).toHaveValue('midnight');
    fireEvent.change(screen.getByLabelText('切换工作空间'), { target: { value: 'space-b' } });
    await screen.findByText('乙空间的故事');
    expect(document.documentElement).toHaveAttribute('data-theme', 'midnight');
    expect(localStorage.getItem('voice-smiths-theme:reader')).toBe('midnight');
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    await screen.findByRole('button', { name: '登录工作空间' });
    expect(screen.getByLabelText('界面主题')).toHaveValue('paper');
    await login('乙空间的故事');
    expect(screen.getByLabelText('界面主题')).toHaveValue('midnight');
  });

  it('registers, enters the workspace, and logs out without exposing session tokens in localStorage', async () => {
    render(<SessionApp />);
    await screen.findByRole('button', { name: '注册账号' });
    fireEvent.click(screen.getByRole('button', { name: '注册账号' }));
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '读者' } });
    fireEvent.change(screen.getByLabelText('工作空间名称'), { target: { value: '小说团队' } });
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'test-password-123' } });
    fireEvent.click(screen.getByRole('button', { name: '注册并开始创作' }));
    await screen.findByText('甲空间的故事');
    const registration = fetch.mock.calls.find(([path]) => path === '/api/auth/register');
    expect(JSON.parse(registration[1].body).tenant_name).toBe('小说团队');
    expect(registration[1].credentials).toBe('include');
    expect(JSON.stringify(localStorage)).not.toContain('session-csrf');
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    await screen.findByRole('button', { name: '登录工作空间' });
    expect(screen.queryByText('甲空间的故事')).not.toBeInTheDocument();
    const logout = fetch.mock.calls.find(([path]) => path === '/api/auth/logout');
    expect(logout[1].headers['X-CSRF-Token']).toBe('session-csrf');
  });

  it('switches tenant data and remembers selected projects under separate keys', async () => {
    render(<SessionApp />);
    await login();
    fireEvent.change(screen.getByLabelText('切换工作空间'), { target: { value: 'space-b' } });
    await screen.findByText('乙空间的故事');
    expect(screen.queryByText('甲空间的故事')).not.toBeInTheDocument();
    expect(localStorage.getItem('voice-smiths-project:reader:space-a')).toBe('space-a-project');
    expect(localStorage.getItem('voice-smiths-project:reader:space-b')).toBe('space-b-project');
    const calls = fetch.mock.calls.filter(([path, options]) => path === '/api/projects' && options.headers['X-Tenant-ID'] === 'space-b');
    expect(calls.length).toBeGreaterThan(0);
  });

  it('creates a tenant and switches directly to the new empty workspace', async () => {
    loggedIn = true;
    render(<SessionApp />);
    await screen.findByText('甲空间的故事');
    fireEvent.click(screen.getByRole('button', { name: /租户与成员/ }));
    fireEvent.change(screen.getByLabelText('新工作空间名称'), { target: { value: '新配音团队' } });
    fireEvent.click(screen.getByRole('button', { name: '创建工作空间' }));
    await waitFor(() => expect(screen.getByLabelText('切换工作空间')).toHaveValue('new-space'));
    expect(screen.queryByText('甲空间的故事')).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: '从一本小说开始' })).toBeVisible();
    const creation = fetch.mock.calls.find(([path, options]) => path === '/api/tenants' && options.method === 'POST');
    expect(creation[1].headers['X-CSRF-Token']).toBe('session-csrf');
  });

  it('adds and removes a registered member from the tenant management screen', async () => {
    loggedIn = true;
    render(<SessionApp />);
    await screen.findByText('甲空间的故事');
    fireEvent.click(screen.getByRole('button', { name: /租户与成员/ }));
    fireEvent.change(screen.getByLabelText('成员邮箱'), { target: { value: 'member@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: '添加成员' }));
    expect(await screen.findByText('member@example.com')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '移除成员' }));
    await waitFor(() => expect(screen.queryByText('member@example.com')).not.toBeInTheDocument());
    const removal = fetch.mock.calls.find(([, options]) => options.method === 'DELETE');
    expect(removal[1].headers['X-CSRF-Token']).toBe('session-csrf');
  });

  it('clears workspace content when a session expires', async () => {
    loggedIn = true;
    render(<SessionApp />);
    await screen.findByText('甲空间的故事');
    act(() => window.dispatchEvent(new Event('voice-smiths:unauthorized')));
    expect(await screen.findByRole('button', { name: '登录工作空间' })).toBeVisible();
    expect(screen.queryByText('甲空间的故事')).not.toBeInTheDocument();
  });
});
