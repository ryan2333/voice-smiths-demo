import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const project = {
  id: 'project-1', title: '雾中来信', encoding: 'gb18030', chapter_count: 1,
  roles: ['林默'], voice_map: { 林默: 'zh-CN-YunxiNeural' },
  chapters: [{ number: 1, title: '第一封信', segments: [{ id: 1, speaker: '林默', text: '你终于来了。' }] }],
};
const config = { upload_dir: '/novels/originals', audio_dir: '/novels/audio', data_dir: '/novels/metadata', workers: 2, connect_timeout: 10, receive_timeout: 60 };
const voices = [{ id: 'zh-CN-YunxiNeural', name: '云希', description: '男声 · 温柔' }, { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓', description: '女声 · 清亮' }];
let tasks;
let collection;

beforeEach(() => {
  localStorage.clear();
  tasks = [];
  collection = [project];
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    let data;
    if (path === '/api/voices') data = { voices };
    else if (path === '/api/config') data = config;
    else if (path === '/api/projects/upload') data = project;
    else if (path === '/api/projects') data = options.method === 'POST' ? project : { projects: collection };
    else if (path === '/api/projects/project-1') data = project;
    else if (path === '/api/voices/preview') data = { audio_url: '/api/voices/previews/sample/audio' };
    else if (path === '/api/jobs/batch') {
      tasks = JSON.parse(options.body).chapter_indices.map((index) => ({ id: `batch-${index}`, project_id: project.id, chapter_index: index, chapter_title: `章节${index}`, status: 'queued', total: 1, created_at: '2026-11-02T10:00:00Z' }));
      data = { jobs: tasks };
    }
    else if (path === '/api/jobs' && options.method === 'POST') {
      const task = { id: 'job-1', project_id: project.id, chapter_index: 0, chapter_title: '第一封信', status: 'queued', progress: 0, completed: 0, total: 1, created_at: '2026-11-02T10:00:00Z' };
      tasks = [task];
      data = task;
    } else if (path === '/api/jobs') data = { jobs: tasks };
    else throw new Error(`Unexpected request ${path}`);
    return { ok: true, json: async () => structuredClone(data) };
  }));
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('React workspace', () => {
  it('switches each menu to its corresponding content', async () => {
    render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.click(screen.getByRole('button', { name: /章节管理/ }));
    expect(screen.getByRole('button', { name: /全书加入生成队列/ })).toBeVisible();
    expect(screen.queryByText('正文预览')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /角色与声线/ }));
    expect(screen.getByRole('heading', { name: '全书角色声线' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /生成与音频/ }));
    expect(screen.getByRole('heading', { name: '生成任务' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /存储与设置/ }));
    expect(screen.getByText('/novels/originals')).toBeVisible();
    expect(screen.getByText('/novels/audio')).toBeVisible();
  });

  it('uploads original file bytes and selected encoding using multipart', async () => {
    render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.click(screen.getByRole('button', { name: /导入 TXT/ }));
    const file = new File([new Uint8Array([0xb5, 0xda, 0xd2, 0xbb, 0xd5, 0xc2])], '小说.txt', { type: 'text/plain' });
    fireEvent.change(screen.getByLabelText('小说文件'), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText('文件编码'), { target: { value: 'gb18030' } });
    fireEvent.click(screen.getByRole('button', { name: '保存并解析' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const upload = fetch.mock.calls.find(([path]) => path === '/api/projects/upload');
    expect(upload[1].body).toBeInstanceOf(FormData);
    expect(upload[1].body.get('file')).toBe(file);
    expect(upload[1].body.get('encoding')).toBe('gb18030');
    expect(localStorage.getItem('voice-smiths-project')).toBe(project.id);
  });

  it('keeps the import dialog and original selection on decode failure', async () => {
    render(<App />);
    await screen.findByText('你终于来了。');
    const originalFetch = fetch.getMockImplementation();
    fetch.mockImplementation(async (path, options) => path === '/api/projects/upload'
      ? { ok: false, json: async () => ({ detail: '请更换编码后重试' }) }
      : originalFetch(path, options));
    fireEvent.click(screen.getByRole('button', { name: /导入 TXT/ }));
    fireEvent.change(screen.getByLabelText('小说文件'), { target: { files: [new File(['bad'], '小说.txt')] } });
    fireEvent.click(screen.getByRole('button', { name: '保存并解析' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('请更换编码后重试');
    expect(screen.getByRole('dialog')).toBeVisible();
    expect(screen.getByText('小说.txt')).toBeVisible();
  });

  it('submits once and continues polling beyond the former 84-second limit', async () => {
    vi.useFakeTimers();
    await act(async () => { render(<App />); });
    expect(screen.getByText('你终于来了。')).toBeVisible();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /生成本章音频/ })); });
    expect(screen.getByRole('heading', { name: '生成任务' })).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(100_000); });
    expect(screen.queryByText(/生成超时/)).not.toBeInTheDocument();
    expect(screen.getByText('等待生成')).toBeVisible();
    const submissions = fetch.mock.calls.filter(([path, options]) => path === '/api/jobs' && options?.method === 'POST');
    expect(submissions).toHaveLength(1);
    tasks = tasks.map((task) => ({ ...task, status: 'done', progress: 100, audio_url: '/api/jobs/job-1/audio', download_url: '/api/jobs/job-1/audio?download=true' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole('link', { name: /下载 MP3/ })).toHaveAttribute('href', '/api/jobs/job-1/audio?download=true');
  });

  it('restores persisted jobs on a fresh page load', async () => {
    tasks = [{ id: 'existing', project_id: project.id, chapter_index: 0, chapter_title: '历史章节', status: 'done', progress: 100, total: 1, completed: 1, created_at: '2026-11-02T10:00:00Z', audio_url: '/api/jobs/existing/audio', download_url: '/api/jobs/existing/audio?download=true' }];
    render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.click(screen.getByRole('button', { name: /生成与音频/ }));
    expect(screen.getByText('历史章节')).toBeVisible();
    expect(screen.getByRole('link', { name: /下载 MP3/ })).toHaveAttribute('href', '/api/jobs/existing/audio?download=true');
  });

  it('reloads the complete workspace when the backend becomes available after startup', async () => {
    vi.useFakeTimers();
    const availableFetch = fetch.getMockImplementation();
    fetch.mockImplementation(async () => { throw new Error('offline'); });
    await act(async () => { render(<App />); });
    expect(screen.getByRole('alert')).toHaveTextContent('正在重新连接');
    fetch.mockImplementation(availableFetch);
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByText('你终于来了。')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /存储与设置/ }));
    expect(screen.getByText('/novels/originals')).toBeVisible();
  });

  it('submits only checked chapters in a single batch request', async () => {
    const originalFetch = fetch.getMockImplementation();
    const multiple = { ...project, chapter_count: 3, chapters: ['初见', '重逢', '归来'].map((title, index) => ({ ...project.chapters[0], title, number: index + 1 })) };
    fetch.mockImplementation(async (path, options) => path === '/api/projects/project-1'
      ? { ok: true, json: async () => structuredClone(multiple) }
      : originalFetch(path, options));
    render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.click(screen.getByRole('button', { name: /章节管理/ }));
    expect(screen.getByRole('button', { name: /批量生成所选章节/ })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('全选当前列表章节'));
    fireEvent.click(screen.getByLabelText('选择章节：重逢'));
    fireEvent.click(screen.getByRole('button', { name: /批量生成所选章节/ }));
    await screen.findByRole('heading', { name: '生成任务' });
    const batches = fetch.mock.calls.filter(([path]) => path === '/api/jobs/batch');
    expect(batches).toHaveLength(1);
    expect(JSON.parse(batches[0][1].body)).toEqual({ project_id: project.id, chapter_indices: [0, 2], voice_map: project.voice_map });
  });

  it('applies playback speed to audio and remembers it after a reload', async () => {
    tasks = [{ id: 'existing', project_id: project.id, chapter_index: 0, chapter_title: '历史章节', status: 'done', created_at: '2026-11-02T10:00:00Z', audio_url: '/api/jobs/existing/audio', download_url: '/api/jobs/existing/audio?download=true' }];
    const first = render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.change(screen.getByLabelText('当前章节音频播放速度'), { target: { value: '1.5' } });
    expect(screen.getByLabelText('当前章节音频').playbackRate).toBe(1.5);
    expect(localStorage.getItem('voice-smiths-playback-rate')).toBe('1.5');
    first.unmount();
    render(<App />);
    await screen.findByText('你终于来了。');
    expect(screen.getByLabelText('当前章节音频').playbackRate).toBe(1.5);
    fireEvent.click(screen.getByRole('button', { name: /生成与音频/ }));
    expect(screen.getByLabelText('历史章节音频').playbackRate).toBe(1.5);
    fireEvent.click(screen.getByRole('button', { name: /存储与设置/ }));
    expect(screen.getByLabelText('默认播放速度')).toHaveValue('1.5');
  });

  it('previews the selected role voice and clears the old sample when the voice changes', async () => {
    render(<App />);
    await screen.findByText('你终于来了。');
    fireEvent.click(screen.getByRole('button', { name: '试听林默的声音' }));
    expect(await screen.findByLabelText('林默试听')).toHaveAttribute('src', '/api/voices/previews/sample/audio');
    const preview = fetch.mock.calls.find(([path]) => path === '/api/voices/preview');
    expect(JSON.parse(preview[1].body)).toEqual({ voice: 'zh-CN-YunxiNeural', text: '你终于来了。' });
    fireEvent.change(screen.getByLabelText('林默的声线'), { target: { value: 'zh-CN-XiaoxiaoNeural' } });
    expect(screen.queryByLabelText('林默试听')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '试听林默的声音' }));
    await screen.findByLabelText('林默试听');
    const previews = fetch.mock.calls.filter(([path]) => path === '/api/voices/preview');
    expect(JSON.parse(previews[1][1].body).voice).toBe('zh-CN-XiaoxiaoNeural');
  });
});
