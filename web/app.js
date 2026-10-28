const state = { chapters: [], activeIndex: 0, roleVoices: {}, voices: [] };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message) {
  const element = $('#toast');
  if (!element) return;
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 2800);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload?.error || `请求失败 (${response.status})`);
  return payload;
}

function activeChapter() { return state.chapters[state.activeIndex] || null; }
function voiceName(id) { return state.voices.find((voice) => voice.id === id)?.name || id || '自动声线'; }
function chapterLabel(chapter) { return `${String(chapter.number || 0).padStart(2, '0')} · ${chapter.title || '正文'}`; }
function chapterItems() { return $$('.chapter-item'); }

function estimateDuration(chapter) {
  const chars = (chapter?.segments || []).reduce((total, segment) => total + String(segment.text || '').length, 0);
  const seconds = Math.max(1, Math.round(chars / 4.2));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function renderScript(chapter) {
  const container = $('.script-lines');
  if (!container || !chapter) return;
  container.replaceChildren();
  (chapter.segments || []).forEach((segment, index) => {
    const row = document.createElement('div');
    row.className = 'script-line';
    row.innerHTML = `<span class="line-no">${String(index + 1).padStart(2, '0')}</span><span class="speaker"></span><p></p><button class="play-line">▶</button>`;
    row.querySelector('.speaker').textContent = segment.speaker || '旁白';
    row.querySelector('p').textContent = segment.text || '';
    row.querySelector('.play-line').addEventListener('click', () => toast(`正在试听「${segment.speaker || '旁白'}」这一句`));
    container.appendChild(row);
  });
}

function cycleVoice(button) {
  if (!state.voices.length) return toast('暂无可用声线');
  const role = button.dataset.role;
  const current = button.dataset.voice;
  const currentIndex = state.voices.findIndex((voice) => voice.id === current);
  const next = state.voices[(currentIndex + 1) % state.voices.length];
  button.dataset.voice = next.id;
  button.innerHTML = `${next.name} <span>⌄</span>`;
  state.roleVoices[role] = next.id;
  toast(`「${role}」已切换为${next.name}`);
}

function renderRoles(chapter) {
  const list = $('.cast-list');
  if (!list || !chapter) return;
  const roles = [...new Set((chapter.segments || []).map((segment) => segment.speaker || '旁白'))];
  list.replaceChildren();
  roles.forEach((role, index) => {
    const current = state.roleVoices[role] || chapter.segments.find((segment) => segment.speaker === role)?.voice || state.voices[index % Math.max(1, state.voices.length)]?.id;
    state.roleVoices[role] = current;
    const item = document.createElement('div');
    item.className = 'cast-item';
    item.innerHTML = `<div class="cast-avatar ${index % 3 === 1 ? 'lin-bg' : index % 3 === 2 ? 'su-bg' : 'narrator-bg'}"></div><div class="cast-copy"><strong></strong><small>已分配 · 可切换声线</small></div><button class="voice-select" type="button"><span></span> <span>⌄</span></button><button class="preview-btn" type="button">▶</button>`;
    item.querySelector('.cast-avatar').textContent = role.slice(0, 1);
    item.querySelector('.cast-copy strong').textContent = role;
    const select = item.querySelector('.voice-select');
    select.dataset.role = role;
    select.dataset.voice = current || '';
    select.querySelector('span').textContent = voiceName(current);
    select.addEventListener('click', () => cycleVoice(select));
    const preview = item.querySelector('.preview-btn');
    preview.dataset.name = role;
    preview.addEventListener('click', () => {
      preview.textContent = 'Ⅱ';
      toast(`试听「${role}」：生成章节后可播放音频`);
      setTimeout(() => { preview.textContent = '▶'; }, 1400);
    });
    list.appendChild(item);
  });
}

function selectChapter(index) {
  state.activeIndex = index;
  const chapter = activeChapter();
  chapterItems().forEach((item) => item.classList.toggle('selected', Number(item.dataset.index) === index));
  if (!chapter) return;
  $('#currentChapter').textContent = chapterLabel(chapter);
  $('#lineCount').textContent = `${chapter.segments?.length || 0} 段片段`;
  $('#duration').textContent = `约 ${estimateDuration(chapter)}`;
  renderScript(chapter);
  renderRoles(chapter);
}

function renderChapterList(chapters) {
  const list = $('#chapterList');
  if (!list) return;
  list.replaceChildren();
  chapters.forEach((chapter, index) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `chapter-item${index === 0 ? ' selected' : ''}`;
    item.dataset.index = index;
    item.innerHTML = `<span class="chapter-number">${String(chapter.number || index + 1).padStart(2, '0')}</span><span class="chapter-info"><strong></strong><small>${chapter.segments?.length || 0} 段片段 · 待处理</small></span><span class="chapter-status">—</span>`;
    item.querySelector('strong').textContent = chapter.title || '正文';
    item.addEventListener('click', () => selectChapter(index));
    list.appendChild(item);
  });
  selectChapter(0);
}

async function parseText(text, filename = '') {
  if (!text.trim()) return toast('请先选择文件或粘贴小说文本');
  toast(`正在解析${filename ? `《${filename}》` : '粘贴的文本'}…`);
  try {
    const data = await requestJson('/api/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    state.chapters = data.chapters || [];
    state.roleVoices = {};
    state.voices = data.voices || state.voices;
    renderChapterList(state.chapters);
    toast(`已解析 ${state.chapters.length} 个章节，识别 ${data.roles?.length || 0} 个角色`);
  } catch (error) {
    toast(error.message || '解析失败');
  }
}

function setupImport() {
  const trigger = $('#addChapterBtn');
  if (!trigger) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'import-dialog';
  dialog.innerHTML = `<form method="dialog"><div class="dialog-head"><div><span class="section-kicker">导入内容</span><h3>添加小说</h3></div><button class="dialog-close" value="cancel">×</button></div><label class="file-drop"><input type="file" accept=".txt,.md,text/plain,text/markdown" /><span><strong>选择小说文件</strong><small>支持 TXT、Markdown</small></span></label><div class="or-divider"><span>或粘贴文本</span></div><textarea placeholder="第一章 雾中来信\n林默：你终于还是来了。\n\n第二章 雨夜车站\n……"></textarea><div class="dialog-actions"><button class="outline-button" value="cancel">取消</button><button class="primary-button" id="parseTextBtn" value="default">解析并添加</button></div></form>`;
  document.body.appendChild(dialog);
  const input = dialog.querySelector('input');
  const textArea = dialog.querySelector('textarea');
  const openImport = () => {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  };
  trigger.addEventListener('click', openImport);
  $('#importTxtBtn')?.addEventListener('click', openImport);
  input.addEventListener('change', async () => { const file = input.files?.[0]; if (file) { await parseText(await file.text(), file.name); dialog.close(); input.value = ''; } });
  dialog.querySelector('#parseTextBtn').addEventListener('click', async (event) => { event.preventDefault(); await parseText(textArea.value); if (state.chapters.length) dialog.close(); textArea.value = ''; });
}

function setupNavigation() {
  const viewCopy = {
    workspace: ['创作台 / 配音工作区', '把文字，变成有温度的声音。', '为每一个角色匹配独特声线，让故事在耳边自然发生。'],
    chapters: ['章节管理 / 文本结构', '让每一章，都清清楚楚。', '搜索章节、检查片段，并从这里开始生成配音。'],
    cast: ['角色与声线 / 声音设计', '让每个角色拥有自己的声音。', '为旁白和角色分配声线，生成更连贯的听觉体验。'],
    exports: ['导出记录 / 音频文件', '你的声音作品，都在这里。', '查看已经生成的章节音频和下载记录。'],
    settings: ['设置 / 工作偏好', '把工作区调成你喜欢的样子。', '保存草稿、下载方式和默认语音设置。'],
  };
  const switchView = (view) => {
    const layout = $('#workspaceLayout');
    const hero = $('.hero-row');
    const exportsView = $('#exportsView');
    const settingsView = $('#settingsView');
    const copy = viewCopy[view] || viewCopy.workspace;
    $('#heroTitle').textContent = copy[1];
    $('#heroSubtitle').textContent = copy[2];
    $('.eyebrow').textContent = copy[0];
    layout?.classList.remove('view-chapters', 'view-cast');
    exportsView?.classList.remove('active');
    settingsView?.classList.remove('active');
    if (view === 'chapters') layout?.classList.add('view-chapters');
    if (view === 'cast') layout?.classList.add('view-cast');
    if (view === 'exports') exportsView?.classList.add('active');
    if (view === 'settings') settingsView?.classList.add('active');
    if (hero) hero.hidden = view === 'exports' || view === 'settings';
    if (layout) layout.hidden = view === 'exports' || view === 'settings';
    $$('.nav-item').forEach((navItem) => navItem.classList.toggle('active', navItem.dataset.view === view));
  };
  $$('.nav-item').forEach((item) => {
    item.addEventListener('click', (event) => {
      event.preventDefault();
      switchView(item.dataset.view || 'workspace');
    });
  });
  $('.workspace-switcher .icon-button')?.addEventListener('click', () => toast('当前作品：雾都来信'));
  $('#guideLink')?.addEventListener('click', (event) => {
    event.preventDefault();
    toast('先点击“导入 TXT”，再选择文件或粘贴小说文本。');
  });
  switchView('workspace');
}

function setupPanelActions() {
  $$('.toolbar-btn').forEach((button) => {
    button.addEventListener('click', () => {
      $$('.toolbar-btn').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      const mode = button.textContent.trim();
      $$('.script-line').forEach((line) => {
        const isNarration = line.querySelector('.speaker')?.textContent.trim() === '旁白';
        line.hidden = mode === '旁白' ? !isNarration : mode === '对白' ? isNarration : false;
      });
      toast(mode === '⚙' ? '片段显示设置已打开' : `已筛选：${mode}`);
    });
  });
  $('.load-more')?.addEventListener('click', () => toast(`当前已显示 ${state.chapters.length || 1} 个章节`));
  $('.add-line')?.addEventListener('click', () => toast('请重新导入文本，应用会自动拆分新的对白片段。'));
  $('.add-role')?.addEventListener('click', () => toast('角色会在导入文本后自动识别。'));
  $$('.editor-tools .icon-button').forEach((button) => button.addEventListener('click', () => toast('编辑历史功能将在下一版开放。')));
  $('.cast-panel .panel-header .icon-button')?.addEventListener('click', () => toast('角色声线可通过右侧声线按钮循环切换。'));
  $('.settings-title .icon-button')?.addEventListener('click', () => toast('声音设置已应用到当前章节。'));
}

async function renderCurrentChapter() {
  const chapter = activeChapter();
  if (!chapter) return toast('请先导入小说文本');
  const button = $('#generateBtn');
  const original = button?.innerHTML;
  if (button) { button.disabled = true; button.innerHTML = '<span class="spinner"></span> 正在生成…'; }
  try {
    const queued = await requestJson('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chapter, voice_map: state.roleVoices }) });
    let job = queued;
    for (let attempt = 0; attempt < 120 && (job.status === 'queued' || job.status === 'running'); attempt += 1) { await new Promise((resolve) => setTimeout(resolve, 700)); job = await requestJson(`/api/jobs/${encodeURIComponent(queued.job_id)}`); }
    if (job.status === 'error') throw new Error(job.error || '音频生成失败');
    if (job.status !== 'done') throw new Error('生成超时，请稍后重试');
    const item = chapterItems().find((candidate) => Number(candidate.dataset.index) === state.activeIndex);
    const status = item?.querySelector('.chapter-status');
    if (status) { status.textContent = '✓'; status.classList.add('done'); }
    toast('本章音频已生成，正在下载 ZIP');
    window.location.href = job.download_url;
  } catch (error) {
    toast(error.message || '生成失败；请确认已安装 edge-tts');
  } finally {
    if (button) { button.disabled = false; button.innerHTML = original; }
  }
}

function setupSearch() {
  const input = $('#chapterSearch');
  input?.addEventListener('input', () => { const query = input.value.trim().toLowerCase(); chapterItems().forEach((item) => { item.hidden = query && !item.textContent.toLowerCase().includes(query); }); });
  document.addEventListener('keydown', (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); input?.focus(); } });
}

function setupMisc() {
  $('#generateBtn')?.addEventListener('click', renderCurrentChapter);
  $('#exportBtn')?.addEventListener('click', renderCurrentChapter);
  $('#saveBtn')?.addEventListener('click', () => toast('草稿已保存在当前浏览器会话中'));
  $('#helpBtn')?.addEventListener('click', () => toast('导入 TXT 或粘贴文本，检查角色声线后即可生成章节音频。'));
  const emotion = $('#emotionRange');
  emotion?.addEventListener('input', () => { const output = $('#emotionValue'); if (output) output.textContent = `${emotion.value}%`; });
}

async function bootstrap() {
  try { state.voices = (await requestJson('/api/voices')).voices || []; } catch (error) { state.voices = [{ id: 'zh-CN-XiaoxiaoNeural', name: '晓晓' }, { id: 'zh-CN-YunxiNeural', name: '云希' }]; }
  setupImport();
  setupSearch();
  setupMisc();
  setupNavigation();
  setupPanelActions();
  const sampleLines = $$('.script-line').map((row, index) => ({ id: index + 1, speaker: row.querySelector('.speaker')?.textContent || '旁白', text: row.querySelector('p')?.textContent || '', is_dialogue: true, voice: state.voices[0]?.id }));
  state.chapters = [{ number: 1, title: '雾中来信', text: '', segments: sampleLines }];
  renderChapterList(state.chapters);
}

bootstrap();
