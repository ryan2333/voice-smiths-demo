from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict

from .config import Settings
from .core import Segment, TTSGenerator, VoiceProfile


class VoicePreviews:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.directory = settings.audio_dir / "previews"
        self.pending: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(settings.workers)

    async def generate(self, profile: VoiceProfile, text: str) -> str:
        payload = json.dumps({**asdict(profile), "text": text}, ensure_ascii=False, sort_keys=True)
        preview_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if (self.directory / f"{preview_id}.mp3").is_file():
            return preview_id
        task = self.pending.get(preview_id)
        if task is None:
            task = asyncio.create_task(self._generate(preview_id, profile, text))
            self.pending[preview_id] = task
            task.add_done_callback(lambda completed: self._finished(preview_id, completed))
        await asyncio.shield(task)
        return preview_id

    def _finished(self, preview_id: str, task: asyncio.Task) -> None:
        self.pending.pop(preview_id, None)
        if not task.cancelled():
            task.exception()

    async def _generate(self, preview_id: str, profile: VoiceProfile, text: str) -> None:
        temporary = self.directory / f"{preview_id}.tmp.mp3"
        try:
            async with self.semaphore:
                generator = TTSGenerator(
                    self.directory, connect_timeout=self.settings.connect_timeout,
                    receive_timeout=self.settings.receive_timeout,
                )
                await generator.generate_segment(Segment(id=1, text=text, **asdict(profile)), temporary)
                if not temporary.is_file() or temporary.stat().st_size == 0:
                    raise RuntimeError("语音服务未返回试听音频，请重试")
                temporary.replace(self.directory / f"{preview_id}.mp3")
        finally:
            temporary.unlink(missing_ok=True)

    async def stop(self) -> None:
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
