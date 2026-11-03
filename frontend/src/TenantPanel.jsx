import { useEffect, useState } from 'react';
import { jsonRequest, request } from './api';

export const ROLE_LABELS = { owner: '所有者', admin: '管理员', member: '普通成员' };

export default function TenantPanel({ session, tenant, onRefresh }) {
  const [members, setMembers] = useState([]);
  const [newName, setNewName] = useState('');
  const [name, setName] = useState(tenant?.name || '');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('member');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const manager = ['owner', 'admin'].includes(tenant?.role);
  const base = tenant ? `/api/tenants/${tenant.id}` : '';

  useEffect(() => {
    const controller = new AbortController();
    if (tenant) request(`${base}/members`, { signal: controller.signal }).then((data) => setMembers(data.members)).catch((failure) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [base]);

  async function action(work) {
    setBusy(true); setError(''); setMessage('');
    try { await work(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  async function reloadMembers() {
    setMembers((await request(`${base}/members`)).members);
  }

  return <section className="panel tenant-panel"><div className="panel-heading"><div><span className="kicker">团队与权限</span><h2>租户与成员管理</h2></div><button className="button secondary" disabled={busy} onClick={() => action(async () => { await onRefresh(); if (tenant) await reloadMembers(); })}>刷新空间列表</button></div>
    {error && <p className="error-text" role="alert">{error}</p>}{message && <p role="status" className="muted small">{message}</p>}
    <p className="muted small">每个工作空间是一个独立租户。空间内共享小说、角色配置和音频，其他空间无法访问。</p>
    <form className="tenant-form" onSubmit={(event) => { event.preventDefault(); action(async () => { const created = await jsonRequest('/api/tenants', { name: newName }); await onRefresh(created.id); setNewName(''); }); }}>
      <label className="field">新工作空间名称<input required maxLength={80} value={newName} onChange={(event) => setNewName(event.target.value)} /></label><button className="button primary" disabled={busy}>创建工作空间</button>
    </form>
    {tenant && <><div className="tenant-heading"><h3>{tenant.name}</h3><span className="badge done">{ROLE_LABELS[tenant.role]}</span></div>
      {manager && <form className="tenant-form" onSubmit={(event) => { event.preventDefault(); action(async () => { await jsonRequest(base, { name }, 'PATCH'); await onRefresh(); setMessage('工作空间名称已保存。'); }); }}><label className="field">空间名称<input required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} /></label><button className="button secondary" disabled={busy}>保存空间名称</button></form>}
      {manager && <form className="tenant-form" onSubmit={(event) => { event.preventDefault(); action(async () => { await jsonRequest(`${base}/members`, { email, role }); await reloadMembers(); setEmail(''); setMessage('成员已加入工作空间。'); }); }}>
        <label className="field">成员邮箱<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="输入已注册账号的邮箱" /></label><label className="field">加入角色<select value={role} onChange={(event) => setRole(event.target.value)}><option value="member">普通成员</option>{tenant.role === 'owner' && <option value="admin">管理员</option>}</select></label><button className="button primary" disabled={busy}>添加成员</button>
      </form>}
      <div className="member-list">{members.map((member) => <div className="member-row" key={member.id}><div className="member-name"><strong>{member.display_name}{member.id === session.user.id ? '（我）' : ''}</strong><small>{member.email}</small></div>
        {tenant.role === 'owner' && member.role !== 'owner' ? <select aria-label={`${member.display_name}的权限`} value={member.role} disabled={busy} onChange={(event) => action(async () => { await jsonRequest(`${base}/members/${member.id}`, { role: event.target.value }, 'PATCH'); await reloadMembers(); })}><option value="member">普通成员</option><option value="admin">管理员</option></select> : <span className="badge">{ROLE_LABELS[member.role]}</span>}
        {member.role !== 'owner' && (member.id === session.user.id || tenant.role === 'owner' || (tenant.role === 'admin' && member.role === 'member')) && <button className="button secondary" disabled={busy} onClick={() => action(async () => { await request(`${base}/members/${member.id}`, { method: 'DELETE' }); if (member.id === session.user.id) await onRefresh(); else await reloadMembers(); })}>{member.id === session.user.id ? '退出空间' : '移除成员'}</button>}
      </div>)}</div>
      <p className="muted small">所有者管理管理员权限；管理员可添加、移除普通成员。所有者不能被移除或降级。</p>
    </>}
  </section>;
}
