from __future__ import annotations

import asyncio
from pathlib import Path

from .audio import cleanup_chapter_intermediates
from .core import Chapter, Segment, TTSGenerator
from .storage import Storage


class JobManager:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []

    async def start(self) -> None:
        queued = self.storage.recover_jobs()
        for job in self.storage.list_jobs():
            if job["status"] == "done" and job["audio_path"]:
                audio = Path(job["audio_path"]).resolve()
                if audio.is_relative_to(self.storage.settings.audio_dir.resolve()):
                    await asyncio.to_thread(cleanup_chapter_intermediates, audio)
        for job_id in queued:
            self.queue.put_nowait(job_id)
        self.workers = [asyncio.create_task(self._worker()) for _ in range(self.storage.settings.workers)]

    async def stop(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def submit(self, project_id: str, chapter_index: int, chapter: dict) -> dict:
        job, created = self.storage.create_job(project_id, chapter_index, chapter)
        if created:
            self.queue.put_nowait(job["id"])
        return job

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                job = self.storage.get_job(job_id)
                if not job or job["status"] != "queued":
                    continue
                self.storage.update_job(job_id, status="running", error=None)
                source = job["payload"]
                chapter = Chapter(
                    number=source["number"], title=source["title"], text=source["text"],
                    segments=[Segment(**segment) for segment in source["segments"]],
                )
                settings = self.storage.settings
                generator = TTSGenerator(
                    settings.audio_dir / job["tenant_id"] / job_id,
                    connect_timeout=settings.connect_timeout,
                    receive_timeout=settings.receive_timeout,
                )

                def report(completed: int, total: int, stage: str) -> None:
                    self.storage.update_job(
                        job_id, completed=completed,
                        progress=95 if stage == "merging" else round(completed / max(total, 1) * 90),
                        status="merging" if stage == "merging" else "running",
                    )

                paths = await generator.generate_chapter(chapter, progress=report)
                audio = Path(paths[0]).resolve()
                if not audio.is_file() or not audio.is_relative_to(settings.audio_dir.resolve()):
                    raise RuntimeError("生成音频未保存到配置的音频目录")
                self.storage.update_job(job_id, status="done", progress=100, completed=job["total"], audio_path=str(audio))
            except asyncio.CancelledError:
                self.storage.update_job(job_id, status="interrupted", error="服务中断，请点击重试继续生成")
                raise
            except Exception as exc:
                self.storage.update_job(job_id, status="error", error=str(exc) or type(exc).__name__)
            finally:
                self.queue.task_done()
