import { useEffect, useRef, useState } from 'react';
import { apiUrl, request } from './api';
import AudioPlayer from './AudioPlayer';

export default function RoleCard({ role, index, configured, voices, text, onChange, playbackRate, onPlaybackRateChange }) {
  const profile = typeof configured === 'string' ? { voice: configured } : configured || {};
  const signature = JSON.stringify({ ...profile, text });
  const pending = useRef(null);
  const [sample, setSample] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setSample(null);
    setError('');
    setBusy(false);
    return () => pending.current?.abort();
  }, [signature]);

  async function preview() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setSample(null);
    setError('');
    try {
      const result = await request('/api/voices/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...profile, text }), signal: controller.signal,
      });
      if (!controller.signal.aborted) setSample(result.audio_url);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="role-card">
    <div className="role-main"><span className={`role-avatar tone-${index % 4}`}>{role.slice(0, 1)}</span>
      <div className="role-copy"><strong>{role}</strong><small>{voices.find((voice) => voice.id === profile.voice)?.description || '选择角色声线'}</small></div>
      <select aria-label={`${role}的声线`} value={profile.voice || ''} onChange={(event) => onChange(typeof configured === 'object' ? { ...configured, voice: event.target.value } : event.target.value)}>
        {voices.map((voice) => <option value={voice.id} key={voice.id}>{voice.name}</option>)}
      </select>
    </div>
    <div className="role-preview"><button className="button secondary" disabled={busy || !profile.voice} onClick={preview} aria-label={`试听${role}的声音`}>{busy ? '正在生成试听…' : '▷ 试听声音'}</button><span className="muted small">使用该角色的一小段原文</span></div>
    {sample && <AudioPlayer src={apiUrl(sample)} label={`${role}试听`} playbackRate={playbackRate} onPlaybackRateChange={onPlaybackRateChange} autoPlay />}
    {error && <p className="error-text" role="alert">{error}</p>}
  </div>;
}
