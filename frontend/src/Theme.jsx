import { createContext, useContext, useLayoutEffect, useState } from 'react';

export const THEMES = [
  { id: 'forest', name: '森林绿', description: '清浅绿意，熟悉的创作空间', colors: ['#f7f9f6', '#eef4ec', '#2f6d57'] },
  { id: 'sky', name: '晴空蓝', description: '明亮清爽，专注故事编排', colors: ['#f4f8fc', '#eaf1fa', '#285fa0'] },
  { id: 'paper', name: '暖纸色', description: '温润纸感，适合长时间阅读', colors: ['#faf6ed', '#f2e9da', '#8a5832'] },
  { id: 'midnight', name: '午夜深色', description: '柔和暗色，适合夜间创作', colors: ['#151c25', '#1b2531', '#85c8b0'] },
  { id: 'system', name: '跟随系统', description: '随系统切换森林绿与午夜深色', colors: ['#f7f9f6', '#151c25', '#85c8b0'] },
];

const ThemeContext = createContext(null);
const validTheme = (value) => THEMES.some((theme) => theme.id === value);

function savedTheme(storageKey) {
  try {
    const saved = localStorage.getItem(storageKey) || localStorage.getItem('voice-smiths-theme');
    return validTheme(saved) ? saved : 'forest';
  } catch { return 'forest'; }
}

export function ThemeProvider({ userId, children }) {
  const storageKey = userId ? `voice-smiths-theme:${userId}` : 'voice-smiths-theme';
  const [theme, setTheme] = useState(() => savedTheme(storageKey));

  useLayoutEffect(() => {
    const preference = window.matchMedia?.('(prefers-color-scheme: dark)');
    function apply() {
      const resolved = theme === 'system' ? (preference?.matches ? 'midnight' : 'forest') : theme;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved === 'midnight' ? 'dark' : 'light';
    }
    apply();
    if (theme !== 'system') return;
    preference?.addEventListener('change', apply);
    return () => preference?.removeEventListener('change', apply);
  }, [theme]);

  function changeTheme(value) {
    if (!validTheme(value)) return;
    setTheme(value);
    try { localStorage.setItem(storageKey, value); } catch {}
  }

  return <ThemeContext.Provider value={{ theme, changeTheme }}>{children}</ThemeContext.Provider>;
}

export function ThemeSelect() {
  const context = useContext(ThemeContext);
  if (!context) return null;
  return <label className="theme-switcher"><span>主题</span><select aria-label="界面主题" value={context.theme} onChange={(event) => context.changeTheme(event.target.value)}>{THEMES.map((theme) => <option key={theme.id} value={theme.id}>{theme.name}</option>)}</select></label>;
}

export function ThemeSettings() {
  const context = useContext(ThemeContext);
  if (!context) return null;
  return <section className="panel theme-settings"><div className="panel-heading"><div><span className="kicker">外观偏好</span><h2>界面主题</h2></div></div><p className="muted small">即时应用到所有页面。按账号在当前浏览器记住选择，切换工作空间时保持一致。</p>
    <fieldset className="theme-options"><legend className="visually-hidden">选择内置主题</legend>{THEMES.map((theme) => <label key={theme.id} className={`theme-option ${context.theme === theme.id ? 'selected' : ''}`}><input type="radio" name="interface-theme" aria-label={theme.name} value={theme.id} checked={context.theme === theme.id} onChange={() => context.changeTheme(theme.id)} /><span className="theme-swatches" aria-hidden="true">{theme.colors.map((color) => <span key={color} style={{ backgroundColor: color }} />)}</span><strong>{theme.name}</strong><small>{theme.description}</small></label>)}</fieldset>
  </section>;
}
