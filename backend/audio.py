"""Combine ordered speech segments into one playable chapter MP3."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


logger = logging.getLogger(__name__)


def cleanup_chapter_intermediates(audio_path: Path) -> int:
    manifest_path = audio_path.parent / "manifest.json"
    removed = 0
    try:
        if not audio_path.is_file() or audio_path.stat().st_size == 0 or not manifest_path.is_file():
            return removed
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("audio") != audio_path.name:
            return removed
        segments = manifest.get("segments")
        if not isinstance(segments, list):
            return removed
        for segment in segments:
            name = segment.get("audio") if isinstance(segment, dict) else None
            if not isinstance(name, str) or Path(name).name != name or not re.fullmatch(r"\d{4,}_[^/\\]+\.mp3", name):
                continue
            path = audio_path.parent / name
            if path.name != audio_path.name and not path.is_symlink() and path.is_file():
                path.unlink()
                removed += 1
        manifest_path.unlink()
        return removed + 1
    except (OSError, ValueError, UnicodeError):
        logger.warning("无法清理章节中间文件：%s", manifest_path, exc_info=True)
        return removed


def get_ffmpeg_executable() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(
            f'章节音频合并组件不可用，请执行："{sys.executable}" -m pip install imageio-ffmpeg'
        ) from exc


def merge_audio_segments(paths: Sequence[Path], output_path: Path, *, executable: str | None = None) -> Path:
    if not paths:
        raise ValueError("章节没有可合并的音频片段")
    executable = executable or get_ffmpeg_executable()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="merge-", dir=output_path.parent) as directory:
        temporary_dir = Path(directory)
        playlist = temporary_dir / "segments.txt"
        entries = []
        for path in paths:
            escaped = path.resolve().as_posix().replace("'", "'\\''")
            entries.append(f"file '{escaped}'\n")
        playlist.write_text("".join(entries), encoding="utf-8")
        merged = temporary_dir / "chapter.mp3"
        result = subprocess.run(
            [
                executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "concat", "-safe", "0", "-i", str(playlist),
                "-map", "0:a:0", "-ar", "24000", "-ac", "1",
                "-c:a", "libmp3lame", "-b:a", "64k", str(merged),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"章节音频合并失败：{result.stderr.strip()}")
        merged.replace(output_path)
    return output_path
