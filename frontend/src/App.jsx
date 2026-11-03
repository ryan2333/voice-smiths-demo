import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiUrl, jsonRequest, request } from './api';
import AudioPlayer, { PLAYBACK_RATES } from './AudioPlayer';
import RoleCard from './RoleCard';
import TenantPanel, { ROLE_LABELS } from './TenantPanel';
import { ThemeSelect, ThemeSettings } from './Theme';

const NAVIGATION = [
  { id: 'workspace', label: '创作台', icon: '◫' },
  { id: 'chapters', label: '章节管理', icon: '☷' },
  { id: 'roles', label: '角色与声线', icon: '♬' },
  { id: 'jobs', label: '生成与音频', icon: '↗' },
  { id: 'settings', label: '存储与设置', icon: '⚙' },
  { id: 'tenants', label: '租户与成员', icon: '♧' },
];
const ACTIVE_STATUSES = ['queued', 'running', 'merging'];
const STATUS_LABELS = { queued: '等待生成', running: '正在配音', merging: '合并音频', done: '已完成', error: '生成失败', interrupted: '任务中断' };
const PAGE_COPY = {
  workspace: ['把文字，变成有温度的声音。', '按章节编排，为故事里的每一个角色找到声音。'],
  chapters: ['每个章节，都有自己的声音。', '管理小说章节，也可以将全书加入生成队列。'],
  roles: ['让人物，从文字中走出来。', '声线设置应用于整部小说，生成任务会保留提交时的声音配置。'],
  jobs: ['好故事，正在慢慢发声。', '可以离开页面或关闭浏览器，后台会继续生成；每章输出一个 MP3。'],
  settings: ['文件与声音，都有归处。', '原始小说、生成音频和任务记录分别保存在配置的目录中。'],
  tenants: ['让团队，一起为故事发声。', '管理工作空间和成员权限，每个租户的数据独立保存。'],
};

function ImportDialog({ onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [encoding, setEncoding] = useState('auto');
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    setError('');
    if (!file && !text.trim()) return setError('请选择 TXT 文件，或粘贴小说文本。');
    setBusy(true);
    try {
      let project;
      if (file) {
        const form = new FormData();
        form.append('file', file);
        form.append('encoding', encoding);
        project = await request('/api/projects/upload', { method: 'POST', body: form });
      } else {
        project = await jsonRequest('/api/projects', { text, title: title.trim() || '未命名小说' });
      }
      await onImported(project);
      onClose();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop" onClick={() => !busy && onClose()}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="import-heading" onClick={(event) => event.stopPropagation()}>
      <form onSubmit={submit}>
        <div className="panel-heading"><div><span className="kicker">一个故事的开始</span><h2 id="import-heading">导入小说</h2></div><button type="button" className="icon-button" onClick={onClose} disabled={busy} aria-label="关闭导入">×</button></div>
        <label className="file-drop"><span className="upload-icon">↑</span><strong>{file ? file.name : '选择 TXT 或 Markdown 文件'}</strong><small>原始文件会保存到上传目录，自动识别常见中文编码</small><input aria-label="小说文件" type="file" accept=".txt,.md" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] || null); setError(''); }} /></label>
        {file && <div className="selected-file"><span>{(file.size / 1024).toFixed(1)} KB</span><button type="button" className="link-button" onClick={() => setFile(null)}>改用粘贴文本</button></div>}
        <label className="field">文件编码<select value={encoding} onChange={(event) => setEncoding(event.target.value)}>
          <option value="auto">自动识别（UTF-8 / GBK / UTF-16）</option><option value="utf-8">UTF-8</option><option value="gb18030">GB18030 / GBK / GB2312</option><option value="big5">Big5 · 繁体中文</option><option value="utf-16le">UTF-16 LE</option><option value="utf-16be">UTF-16 BE</option>
        </select></label>
        {!file && <><div className="or-divider">或粘贴小说文本</div><label className="field">作品名称<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="为故事取一个名字" /></label><label className="field">小说正文<textarea value={text} onChange={(event) => setText(event.target.value)} placeholder={'第一章 初见\n林默：你终于来了。\n苏晚：我说过，会把答案带回来。'} rows={6} /></label></>}
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="button primary" disabled={busy}>{busy ? '正在保存与解析…' : '保存并解析'}</button></div>
      </form>
    </section>
  </div>;
}

function EmptyState({ title, description, onImport }) {
  return <div className="empty-state"><div className="empty-mark">文</div><h3>{title}</h3><p>{description}</p>{onImport && <button className="button primary" onClick={onImport}>＋ 导入 TXT 小说</button>}</div>;
}

function JobCard({ job, projectTitle, onRetry, playbackRate, onPlaybackRateChange }) {
  return <article className={`job-card ${job.status}`}>
    <div className="job-heading"><div className="job-mark">{job.status === 'done' ? '✓' : '♫'}</div><div className="job-copy"><strong>{job.chapter_title}</strong><small>{projectTitle} · {new Date(job.created_at).toLocaleString('zh-CN')}</small></div><span className={`badge ${job.status}`}>{STATUS_LABELS[job.status] || job.status}</span></div>
    {ACTIVE_STATUSES.includes(job.status) && <><div className="job-progress"><progress max="100" value={job.progress || 0} /><span>{job.progress || 0}%</span></div><p className="muted small">{job.status === 'merging' ? '正在合并为完整章节 MP3…' : `已完成 ${job.completed} / ${job.total} 个片段`}</p></>}
    {job.error && <p className="error-text">{job.error}</p>}
    {job.status === 'done' && <div className="audio-result"><AudioPlayer src={apiUrl(job.audio_url)} label={`${job.chapter_title}音频`} playbackRate={playbackRate} onPlaybackRateChange={onPlaybackRateChange} /><a className="button secondary" href={apiUrl(job.download_url)} download={job.filename}>↓ 下载 MP3</a><small className="audio-filename">{job.filename}</small></div>}
    {['error', 'interrupted'].includes(job.status) && <button className="button secondary" onClick={() => onRetry(job)}>重新生成</button>}
  </article>;
}

export default function App({ session, tenant, onSessionRefresh, onTenantChange, onLogout }) {
  const projectStorageKey = session && tenant ? `voice-smiths-project:${session.user.id}:${tenant.id}` : 'voice-smiths-project';
  const playbackStorageKey = session ? `voice-smiths-playback-rate:${session.user.id}` : 'voice-smiths-playback-rate';
  const [view, setView] = useState('workspace');
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);
  const [voices, setVoices] = useState([]);
  const [config, setConfig] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [voiceMap, setVoiceMap] = useState({});
  const [selectedChapters, setSelectedChapters] = useState([]);
  const [playbackRate, setPlaybackRate] = useState(() => {
    const saved = Number(localStorage.getItem(playbackStorageKey));
    return PLAYBACK_RATES.includes(saved) ? saved : 1;
  });
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [showImport, setShowImport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const roleSamples = useMemo(() => {
    const samples = new Map();
    for (const chapter of project?.chapters || []) {
      for (const segment of chapter.segments) {
        if (!samples.has(segment.speaker)) samples.set(segment.speaker, segment.text.slice(0, 120));
      }
    }
    return samples;
  }, [project]);

  const selectProject = useCallback(async (id) => {
    const selected = await request(`/api/projects/${id}`);
    setProject(selected);
    setVoiceMap(selected.voice_map || {});
    setChapterIndex(0);
    setSelectedChapters([]);
    setSearch('');
    localStorage.setItem(projectStorageKey, id);
  }, [projectStorageKey]);

  useEffect(() => {
    let disposed = false;
    let timer;
    async function initialize() {
      try {
        const [catalog, configuration, collection, tasks] = await Promise.all([
          request('/api/voices'), request('/api/config'), request('/api/projects'), request('/api/jobs'),
        ]);
        if (disposed) return;
        setVoices(catalog.voices);
        setConfig(configuration);
        setProjects(collection.projects);
        setJobs(tasks.jobs);
        const remembered = localStorage.getItem(projectStorageKey);
        const selected = collection.projects.find((item) => item.id === remembered) || collection.projects[0];
        if (selected) await selectProject(selected.id);
        if (disposed) return;
        setConnectionError('');
        setInitialized(true);
      } catch (failure) {
        if (!disposed) {
          setConnectionError(`无法连接后端：${failure.message}。请确认 API 服务已经启动，正在重新连接…`);
          timer = setTimeout(initialize, 1500);
        }
      } finally {
        if (!disposed) setLoading(false);
      }
    }
    initialize();
    return () => { disposed = true; clearTimeout(timer); };
  }, [selectProject]);

  useEffect(() => {
    if (!initialized) return;
    let disposed = false;
    let timer;
    async function refresh() {
      try {
        const data = await request('/api/jobs');
        if (!disposed) { setJobs(data.jobs); setConnectionError(''); }
      } catch (failure) {
        if (!disposed) setConnectionError('暂时无法查询进度，后台任务会继续运行，正在重新连接…');
      } finally {
        if (!disposed) timer = setTimeout(refresh, 1500);
      }
    }
    timer = setTimeout(refresh, 1500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [initialized]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(''), 4500);
    return () => clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    localStorage.setItem(playbackStorageKey, String(playbackRate));
  }, [playbackRate, playbackStorageKey]);

  const chapters = project?.chapters || [];
  const chapter = chapters[chapterIndex];
  const visibleChapters = chapters.map((item, index) => ({ item, index })).filter(({ item }) => item.title.toLowerCase().includes(search.toLowerCase()));
  const selectableChapters = visibleChapters.filter(({ item }) => item.segments.length).map(({ index }) => index);
  const allVisibleSelected = selectableChapters.length > 0 && selectableChapters.every((index) => selectedChapters.includes(index));
  const projectJobs = jobs.filter((job) => job.project_id === project?.id);
  const activeJobs = jobs.filter((job) => ACTIVE_STATUSES.includes(job.status));
  const completedChapters = new Set(projectJobs.filter((job) => job.status === 'done').map((job) => job.chapter_index)).size;
  const activeChapterJob = projectJobs.find((job) => job.chapter_index === chapterIndex && ACTIVE_STATUSES.includes(job.status));
  const completedChapterJob = projectJobs.find((job) => job.chapter_index === chapterIndex && job.status === 'done');
  const roles = project?.roles || [];
  const visibleSegments = (chapter?.segments || []).filter((segment) => filter === 'all' || (filter === 'narration' ? segment.speaker === '旁白' : segment.speaker !== '旁白'));

  async function imported(selected) {
    setProject(selected);
    setVoiceMap(selected.voice_map);
    setChapterIndex(0);
    setSelectedChapters([]);
    setSearch('');
    setView('workspace');
    localStorage.setItem(projectStorageKey, selected.id);
    const data = await request('/api/projects');
    setProjects(data.projects);
    setMessage(`《${selected.title}》已保存，解析出 ${selected.chapter_count} 个章节。`);
  }

  async function generate(indices) {
    if (!project) return;
    setBusy(true);
    setError('');
    try {
      if (indices.length === 1) {
        await jsonRequest('/api/jobs', { project_id: project.id, chapter_index: indices[0], voice_map: voiceMap });
      } else {
        await jsonRequest('/api/jobs/batch', { project_id: project.id, chapter_indices: indices, voice_map: voiceMap });
      }
      setJobs((await request('/api/jobs')).jobs);
      setMessage(`${indices.length} 个章节已提交到后台，可以继续编辑或关闭页面。`);
      setView('jobs');
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveVoices() {
    if (!project) return;
    setBusy(true);
    setError('');
    try {
      const saved = await jsonRequest(`/api/projects/${project.id}`, { voice_map: voiceMap }, 'PATCH');
      setProject(saved);
      setMessage('全书角色声线已保存。');
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  }

  async function retry(job) {
    try {
      await jsonRequest(`/api/jobs/${job.id}/retry`, {});
      setJobs((await request('/api/jobs')).jobs);
      setMessage('已重新加入生成队列。');
    } catch (failure) { setError(failure.message); }
  }

  function roleCards() {
    return roles.map((role, index) => <RoleCard key={`${project.id}-${role}`} role={role} index={index} voices={voices} configured={voiceMap[role]}
      text={roleSamples.get(role) || '你好，让我们一起听见故事里的声音。'}
      onChange={(value) => setVoiceMap((current) => ({ ...current, [role]: value }))}
      playbackRate={playbackRate} onPlaybackRateChange={setPlaybackRate} />);
  }

  function chapterList(expanded = false) {
    return <section className={`panel chapters-panel ${expanded ? 'expanded' : ''}`}><div className="panel-heading"><div><span className="kicker">01 / 文本</span><h2>章节列表</h2></div><span className="count-pill">{chapters.length} 章</span></div><label className="search-field"><span>⌕</span><input aria-label="搜索章节" placeholder="搜索章节名称" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {expanded && <div className="batch-toolbar"><label><input type="checkbox" aria-label="全选当前列表章节" checked={allVisibleSelected} disabled={!selectableChapters.length || busy} onChange={() => setSelectedChapters((current) => allVisibleSelected ? current.filter((index) => !selectableChapters.includes(index)) : [...new Set([...current, ...selectableChapters])])} />全选当前列表</label><span>已选 {selectedChapters.length} 章</span><button className="link-button" disabled={!selectedChapters.length || busy} onClick={() => setSelectedChapters([])}>清空选择</button></div>}
      <div className="chapter-list">{visibleChapters.map(({ item, index }) => {
        const latest = projectJobs.find((job) => job.chapter_index === index);
        return <div className="chapter-row" key={`${item.number}-${index}`}>{expanded && <input type="checkbox" aria-label={`选择章节：${item.title}`} checked={selectedChapters.includes(index)} disabled={!item.segments.length || busy} onChange={() => setSelectedChapters((current) => current.includes(index) ? current.filter((selected) => selected !== index) : [...current, index].sort((left, right) => left - right))} />}<button className={`chapter-item ${index === chapterIndex ? 'selected' : ''}`} onClick={() => { setChapterIndex(index); setFilter('all'); if (expanded) setView('workspace'); }}><span className="chapter-number">{String(item.number).padStart(2, '0')}</span><span className="chapter-copy"><strong>{item.title}</strong><small>{item.segments.length} 个片段{latest ? ` · ${STATUS_LABELS[latest.status]}` : ' · 尚未生成'}</small></span><span className={`chapter-symbol ${latest?.status === 'done' ? 'complete' : ''}`}>{latest?.status === 'done' ? '✓' : '›'}</span></button></div>;
      })}</div>
      {expanded && <div className="panel-footer"><button className="button primary" disabled={busy || !selectedChapters.length} onClick={() => generate(selectedChapters)}>✦ 批量生成所选章节（{selectedChapters.length}）</button><button className="button secondary" disabled={busy || !chapters.some((item) => item.segments.length)} onClick={() => generate(chapters.map((item, index) => item.segments.length ? index : null).filter((index) => index !== null))}>全书加入生成队列</button><span className="muted small">同时生成 {config?.workers || 2} 章，每章一个 MP3</span></div>}
    </section>;
  }

  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#workspace" onClick={(event) => { event.preventDefault(); setView('workspace'); }}><span className="brand-mark">声</span><span><strong>叙音工坊</strong><small>STORY VOICE LAB</small></span></a>
    {session && tenant && <div className="tenant-picker"><label>工作空间<select aria-label="切换工作空间" value={tenant.id} onChange={(event) => onTenantChange(event.target.value)}>{session.tenants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><small>{ROLE_LABELS[tenant.role]} · 数据按空间隔离</small></div>}
    {session && <div className="account-sidebar"><div><strong>{session.user.display_name}</strong><small>{session.user.email}</small></div><button className="link-button" onClick={() => onLogout().catch((failure) => setError(failure.message))}>退出登录</button></div>}
    <div className="workspace-picker"><span className="workspace-dot" /><label>当前作品<select aria-label="切换作品" value={project?.id || ''} onChange={(event) => selectProject(event.target.value).catch((failure) => setError(failure.message))}>{!projects.length && <option value="">还没有作品</option>}{projects.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label></div>
    <nav aria-label="主导航">{NAVIGATION.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} aria-current={view === item.id ? 'page' : undefined} onClick={() => { setView(item.id); setError(''); }}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === 'jobs' && activeJobs.length > 0 && <span className="nav-count">{activeJobs.length}</span>}</button>)}</nav>
    <div className="sidebar-note"><span className="small-label">让故事被听见</span><p>一字一句，<br />都值得拥有声音。</p><div className="note-wave">▂ ▄ ▆ █ ▅ ▃ ▆ ▄ ▂</div><small>原文与音频保存在本机</small></div><div className="sidebar-bottom"><span className="online-dot" />{connectionError ? '正在连接 API' : '本地工作空间'}<small>React + Python</small></div>
  </aside><main className="main-content"><header className="topbar"><div className="breadcrumbs">我的作品 <span>/</span> <strong>{project?.title || '开始新的创作'}</strong></div><div className="top-actions"><ThemeSelect /><button className="button secondary" onClick={() => setShowImport(true)}>↑ 导入 TXT</button><button className="button primary" onClick={() => project ? generate([chapterIndex]) : setShowImport(true)} disabled={busy || Boolean(activeChapterJob) || Boolean(chapter && !chapter.segments.length)}>{busy ? '正在提交…' : activeChapterJob ? '本章生成中' : '✦ 生成本章音频'}</button></div></header>
    <section className="hero"><div><span className="kicker">{NAVIGATION.find((item) => item.id === view)?.label} / 小说配音工作空间</span><h1>{PAGE_COPY[view][0]}</h1><p>{PAGE_COPY[view][1]}</p></div>{project && <div className="project-progress"><div><span>作品配音进度</span><strong>{completedChapters} / {chapters.length}</strong></div><progress max={Math.max(chapters.length, 1)} value={completedChapters} /><small>{activeJobs.length ? `${activeJobs.length} 个任务正在后台处理` : '每个章节，一个完整的声音故事'}</small></div>}</section>
    {connectionError && <div className="notice warning" role="alert">{connectionError}</div>}{error && <div className="notice danger" role="alert">{error}</div>}
    {loading ? <div className="panel"><EmptyState title="正在打开工作空间…" description="读取已保存的小说和生成记录" /></div> : <>
      {['workspace', 'chapters', 'roles'].includes(view) && !project && <div className="panel"><EmptyState title="从一本小说开始" description="上传 TXT 或 Markdown，系统会识别章节和角色，再为故事配上声音。" onImport={() => setShowImport(true)} /></div>}
      {view === 'workspace' && project && <div className="workspace-grid">{chapterList()}<section className="panel editor-panel"><div className="panel-heading"><div><span className="kicker">02 / 配音编排</span><h2>{chapter?.title || '选择章节'}</h2></div><span className="subtle-icon">♫</span></div><div className="editor-meta"><span className="online-dot" />已保存原始小说<span>·</span>{chapter?.segments.length || 0} 个片段<span>·</span>{project.encoding.toUpperCase()}</div><div className="script-card"><div className="script-toolbar"><strong>正文预览</strong><div className="filter-buttons">{[['all', '全部'], ['narration', '旁白'], ['dialogue', '对白']].map(([value, label]) => <button className={filter === value ? 'active' : ''} key={value} onClick={() => setFilter(value)}>{label}</button>)}</div></div><div className="script-lines">{visibleSegments.map((segment) => <div className="script-line" key={segment.id}><span className="line-number">{String(segment.id).padStart(2, '0')}</span><span className={`speaker tone-${Math.max(0, roles.indexOf(segment.speaker)) % 4}`}>{segment.speaker}</span><p>{segment.text}</p></div>)}{!visibleSegments.length && <p className="muted empty-filter">这里还没有对应的文本片段。</p>}</div></div><div className="generate-note"><div className="note-wave">▂ ▅ █ ▃ ▆ ▂</div><div><strong>{activeChapterJob ? `${STATUS_LABELS[activeChapterJob.status]} · ${activeChapterJob.progress}%` : '每章合成为一个完整 MP3'}</strong><small>保留各角色声线，按正文顺序自然衔接</small></div><button className="link-button" onClick={() => setView('jobs')}>查看任务 →</button></div>{completedChapterJob && <div className="current-audio"><AudioPlayer src={apiUrl(completedChapterJob.audio_url)} label="当前章节音频" playbackRate={playbackRate} onPlaybackRateChange={setPlaybackRate} /><a href={apiUrl(completedChapterJob.download_url)} className="link-button">下载 MP3</a></div>}</section><aside className="panel voices-panel"><div className="panel-heading"><div><span className="kicker">03 / 声音</span><h2>角色声线</h2></div><span className="count-pill">{roles.length}</span></div><p className="panel-hint">为每个角色选择声音，应用到整部作品。</p><div className="role-list">{roleCards()}</div><button className="button secondary full-width" onClick={saveVoices} disabled={busy}>保存全书声线</button></aside></div>}
      {view === 'chapters' && project && chapterList(true)}
      {view === 'tenants' && session && <TenantPanel session={session} tenant={tenant} onRefresh={onSessionRefresh} />}
      {view === 'settings' && <ThemeSettings />}
      {view === 'settings' && <section className="panel playback-settings"><div className="panel-heading"><div><span className="kicker">收听偏好</span><h2>播放速度</h2></div><label className="playback-control">默认播放速度<select aria-label="默认播放速度" value={playbackRate} onChange={(event) => setPlaybackRate(Number(event.target.value))}>{PLAYBACK_RATES.map((rate) => <option key={rate} value={rate}>{rate}×</option>)}</select></label></div><p className="muted small">应用于章节播放和角色试听，自动记住选择。下载的 MP3 保持原始语速。</p></section>}
      {view === 'roles' && project && <section className="panel"><div className="panel-heading"><div><span className="kicker">角色与声音</span><h2>全书角色声线</h2></div><button className="button primary" onClick={saveVoices} disabled={busy}>保存声线配置</button></div><div className="roles-grid">{roleCards()}</div><p className="muted small">角色设置会保存到本地，刷新页面后仍然保留。</p></section>}
      {view === 'jobs' && <section className="panel"><div className="panel-heading"><div><span className="kicker">后台生成 / 音频库</span><h2>生成任务</h2></div><span className="count-pill">{jobs.length} 个任务</span></div><div className="job-summary"><span><i className="online-dot" />{activeJobs.length} 个正在处理</span><span>{jobs.filter((job) => job.status === 'done').length} 个已完成</span><span>进度每 1.5 秒自动更新</span></div>{jobs.length ? <div className="job-list">{jobs.map((job) => <JobCard job={job} projectTitle={projects.find((item) => item.id === job.project_id)?.title || '小说配音'} key={job.id} onRetry={retry} playbackRate={playbackRate} onPlaybackRateChange={setPlaybackRate} />)}</div> : <EmptyState title="音频库，等待第一个故事" description="提交章节后会立即加入后台队列，完成的音频可在这里播放和下载。" />}</section>}
      {view === 'settings' && <section className="panel settings-panel"><div className="panel-heading"><div><span className="kicker">本地存储</span><h2>文件保存位置</h2></div><span className="badge done">本地保存</span></div>{config && <><div className="storage-row"><span className="storage-icon">文</span><div><strong>上传的小说原文件</strong><code>{config.upload_dir}</code><small>保留原始字节与文件编码；粘贴文本也会保存为 TXT。</small></div></div><div className="storage-row"><span className="storage-icon">♫</span><div><strong>生成的章节音频</strong><code>{config.audio_dir}</code><small>按任务编号分目录，每章一个 MP3，合成后自动清理中间片段。</small></div></div><div className="storage-row"><span className="storage-icon">☷</span><div><strong>作品与任务数据库</strong><code>{config.data_dir}/voice-smiths.sqlite3</code><small>任务、生成进度和作品配置保存在本机。</small></div></div><div className="settings-details"><div><span>同时生成章节</span><strong>{config.workers} 章</strong></div><div><span>语音连接超时</span><strong>{config.connect_timeout} 秒</strong></div><div><span>语音接收等待</span><strong>{config.receive_timeout} 秒</strong></div><div><span>整章等待时限</span><strong>持续后台处理</strong></div></div><p className="settings-help">自定义目录：启动后端前设置 <code>VOICE_SMITHS_UPLOAD_DIR</code> 和 <code>VOICE_SMITHS_AUDIO_DIR</code>。修改后重启后端即可生效。</p></>}</section>}
    </>}
    <footer className="page-footer"><span>叙音工坊 / Voice Smiths</span><span>文字在本地，故事在耳边。</span><button className="link-button" onClick={() => setView('settings')}>查看存储位置 ↗</button></footer>
  </main>{showImport && <ImportDialog onClose={() => setShowImport(false)} onImported={imported} />}{message && <div className="toast" role="status">✓ {message}</div>}</div>;
}
