import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ThemeSelect, ThemeSettings } from './Theme';

let preference;
let listeners;

function Preferences({ userId }) {
  return <ThemeProvider key={userId || 'guest'} userId={userId}><ThemeSelect /><ThemeSettings /></ThemeProvider>;
}

beforeEach(() => {
  localStorage.clear();
  listeners = new Set();
  preference = {
    matches: false,
    addEventListener: vi.fn((event, listener) => listeners.add(listener)),
    removeEventListener: vi.fn((event, listener) => listeners.delete(listener)),
  };
  vi.stubGlobal('matchMedia', vi.fn(() => preference));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.removeProperty('color-scheme');
});

describe('built-in themes', () => {
  it('applies each palette, keeps both controls in sync, and restores the saved choice', () => {
    const first = render(<Preferences userId="reader" />);
    expect(document.documentElement).toHaveAttribute('data-theme', 'forest');
    for (const theme of ['sky', 'paper', 'midnight', 'forest']) {
      fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: theme } });
      expect(document.documentElement).toHaveAttribute('data-theme', theme);
      expect(screen.getByRole('radio', { name: new RegExp({ sky: '晴空蓝', paper: '暖纸色', midnight: '午夜深色', forest: '森林绿' }[theme]) })).toBeChecked();
    }
    fireEvent.click(screen.getByRole('radio', { name: /午夜深色/ }));
    expect(screen.getByLabelText('界面主题')).toHaveValue('midnight');
    expect(document.documentElement.style.colorScheme).toBe('dark');
    expect(localStorage.getItem('voice-smiths-theme:reader')).toBe('midnight');
    first.unmount();
    render(<Preferences userId="reader" />);
    expect(screen.getByLabelText('界面主题')).toHaveValue('midnight');
    expect(document.documentElement).toHaveAttribute('data-theme', 'midnight');
  });

  it('keeps account choices separate and preserves the guest preference after logout', () => {
    localStorage.setItem('voice-smiths-theme', 'paper');
    const page = render(<Preferences userId="first" />);
    expect(screen.getByLabelText('界面主题')).toHaveValue('paper');
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'midnight' } });
    page.rerender(<Preferences userId="second" />);
    expect(screen.getByLabelText('界面主题')).toHaveValue('paper');
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'sky' } });
    page.rerender(<Preferences userId="first" />);
    expect(screen.getByLabelText('界面主题')).toHaveValue('midnight');
    page.rerender(<Preferences />);
    expect(screen.getByLabelText('界面主题')).toHaveValue('paper');
  });

  it('follows system appearance changes and removes the listener when a fixed theme is chosen', () => {
    preference.matches = true;
    localStorage.setItem('voice-smiths-theme', 'system');
    const page = render(<Preferences />);
    expect(document.documentElement).toHaveAttribute('data-theme', 'midnight');
    act(() => { preference.matches = false; listeners.forEach((listener) => listener()); });
    expect(document.documentElement).toHaveAttribute('data-theme', 'forest');
    expect(document.documentElement.style.colorScheme).toBe('light');
    expect(screen.getByLabelText('界面主题')).toHaveValue('system');
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'sky' } });
    expect(listeners.size).toBe(0);
    expect(document.documentElement).toHaveAttribute('data-theme', 'sky');
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'system' } });
    expect(listeners.size).toBe(1);
    page.unmount();
    expect(listeners.size).toBe(0);
  });

  it('falls back for invalid preferences and still switches when browser storage is blocked', () => {
    localStorage.setItem('voice-smiths-theme', 'unavailable-theme');
    const page = render(<Preferences />);
    expect(document.documentElement).toHaveAttribute('data-theme', 'forest');
    page.unmount();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage blocked'); });
    render(<Preferences />);
    fireEvent.change(screen.getByLabelText('界面主题'), { target: { value: 'midnight' } });
    expect(document.documentElement).toHaveAttribute('data-theme', 'midnight');
  });
});
