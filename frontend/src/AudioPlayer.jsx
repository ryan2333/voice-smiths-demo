import { useEffect, useRef } from 'react';

export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

export default function AudioPlayer({ src, label, playbackRate, onPlaybackRateChange, autoPlay = false }) {
  const player = useRef(null);

  useEffect(() => {
    if (player.current) {
      player.current.defaultPlaybackRate = playbackRate;
      player.current.playbackRate = playbackRate;
    }
  }, [playbackRate, src]);

  return <div className="audio-player">
    <audio ref={player} controls preload="none" src={src} aria-label={label} autoPlay={autoPlay}
      onLoadedMetadata={() => { player.current.playbackRate = playbackRate; }}
      onPlay={() => { document.querySelectorAll('audio').forEach((audio) => { if (audio !== player.current) audio.pause(); }); }} />
    <label className="playback-control">播放速度<select aria-label={`${label}播放速度`} value={playbackRate} onChange={(event) => onPlaybackRateChange(Number(event.target.value))}>
      {PLAYBACK_RATES.map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
    </select></label>
  </div>;
}
