import { useEffect, useState } from 'react';
import App from './App';
import TenantPanel from './TenantPanel';
import { ThemeProvider, ThemeSelect } from './Theme';
import { jsonRequest, request, setRequestContext } from './api';

function SignIn({ onAuthenticated }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [tenantName, setTenantName] = useState('我的工作空间');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const payload = { email, password };
      if (mode === 'register') Object.assign(payload, { display_name: name, tenant_name: tenantName });
      const session = await jsonRequest(`/api/auth/${mode}`, payload);
      onAuthenticated(session);
    } catch (failure) {
      setError(failure.message);
    } finally { setBusy(false); }
  }

  return <div className="account-page"><section className="panel account-card"><span className="brand-mark">声</span><span className="kicker">叙音工坊 / STORY VOICE LAB</span><h1>{mode === 'login' ? '欢迎回到你的声音世界' : '创建你的配音工作空间'}</h1><p className="muted small">登录后管理小说与声音，和团队一起完成故事。</p>
    <div className="account-tabs"><button className={mode === 'login' ? 'active' : ''} disabled={busy} onClick={() => { setMode('login'); setError(''); }}>登录</button><button className={mode === 'register' ? 'active' : ''} disabled={busy} onClick={() => { setMode('register'); setError(''); }}>注册账号</button></div>
    <form onSubmit={submit}>
      {mode === 'register' && <><label className="field">显示名称<input required maxLength={80} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field">工作空间名称<input required maxLength={80} value={tenantName} onChange={(event) => setTenantName(event.target.value)} /></label></>}
      <label className="field">邮箱<input type="email" required autoComplete="username" maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label className="field">密码<input type="password" required minLength={mode === 'register' ? 10 : 1} maxLength={128} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {mode === 'register' && <p className="muted small">密码需为 10–128 位。注册后自动创建由你拥有的工作空间。</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      <button type="submit" className="button primary full-width" disabled={busy}>{busy ? '正在处理…' : mode === 'login' ? '登录工作空间' : '注册并开始创作'}</button>
    </form>
  </section></div>;
}

export default function SessionApp() {
  const [session, setSession] = useState(null);
  const [tenantId, setTenantId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  function authenticated(data, preferredId) {
    const remembered = preferredId || localStorage.getItem(`voice-smiths-tenant:${data.user.id}`);
    const selected = data.tenants.find((tenant) => tenant.id === remembered) || data.tenants[0];
    setRequestContext(selected?.id || '', data.csrf_token);
    setTenantId(selected?.id || '');
    setSession(data);
    setError('');
    if (selected) localStorage.setItem(`voice-smiths-tenant:${data.user.id}`, selected.id);
  }

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    async function restore() {
      try {
        const data = await request('/api/auth/me');
        if (!disposed) authenticated(data);
      } catch (failure) {
        if (!disposed && failure.status !== 401) setError(`连接失败：${failure.message}`);
      } finally { if (!disposed) setLoading(false); }
    }
    restore();
    return () => { disposed = true; };
  }, [attempt]);

  useEffect(() => {
    function expired() { setRequestContext(); setSession(null); setTenantId(''); setError('登录已过期，请重新登录。'); }
    window.addEventListener('voice-smiths:unauthorized', expired);
    return () => window.removeEventListener('voice-smiths:unauthorized', expired);
  }, []);

  async function refresh(preferredId) {
    const data = await request('/api/auth/me');
    authenticated(data, preferredId || tenantId);
  }

  function switchTenant(id) {
    if (!session.tenants.some((tenant) => tenant.id === id)) return;
    setRequestContext(id, session.csrf_token);
    setTenantId(id);
    localStorage.setItem(`voice-smiths-tenant:${session.user.id}`, id);
  }

  async function logout() {
    try { await jsonRequest('/api/auth/logout', {}); }
    catch (failure) { if (failure.status !== 401) throw failure; }
    setRequestContext();
    setSession(null);
    setTenantId('');
    setError('');
  }

  const tenant = session?.tenants.find((item) => item.id === tenantId);
  let content;
  if (loading) content = <div className="account-page"><p>正在恢复登录状态…</p></div>;
  else if (!session) content = <>{error && <div className="session-notice notice warning" role="alert">{error}<button className="link-button" onClick={() => { setError(''); setAttempt((value) => value + 1); }}>重新连接</button></div>}<SignIn onAuthenticated={authenticated} /></>;
  else if (!tenant) content = <div className="account-page"><TenantPanel session={session} tenant={null} onRefresh={refresh} /></div>;
  else content = <App key={`${session.user.id}:${tenantId}`} session={session} tenant={tenant} onSessionRefresh={refresh} onTenantChange={switchTenant} onLogout={logout} />;
  return <ThemeProvider key={session?.user.id || 'guest'} userId={session?.user.id}>{!tenant && <div className="account-theme"><ThemeSelect /></div>}{content}</ThemeProvider>;
}
