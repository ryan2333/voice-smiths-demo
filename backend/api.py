from __future__ import annotations

import re
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .accounts import Accounts
from .auth import auth_router, require_tenant
from .config import Settings
from .core import DEFAULT_VOICES, VoiceProfile, assign_voices, chapter_audio_filename, parse_chapters
from .jobs import JobManager
from .preview import VoicePreviews
from .storage import Storage, timestamp
from .text import decode_novel_bytes


class TextProject(BaseModel):
    text: str = Field(min_length=1)
    title: str = "未命名小说"


class VoiceSettings(BaseModel):
    voice: str
    rate: str = Field(default="+0%", pattern=r"^[+-]\d+%$")
    pitch: str = Field(default="+0Hz", pattern=r"^[+-]\d+Hz$")
    volume: str = Field(default="+0%", pattern=r"^[+-]\d+%$")


class VoiceUpdate(BaseModel):
    voice_map: dict[str, str | VoiceSettings] = Field(default_factory=dict)


class RenderRequest(VoiceUpdate):
    project_id: str
    chapter_index: int = Field(ge=0)


class BatchRenderRequest(VoiceUpdate):
    project_id: str
    chapter_indices: list[int] = Field(min_length=1)


class PreviewRequest(VoiceSettings):
    text: str = Field(default="你好，欢迎来到故事的世界。让我们一起，听见文字里的温度。", min_length=1, max_length=160)


def voice_catalog() -> list[dict[str, str]]:
    labels = [("晓晓", "女声 · 清亮"), ("云希", "男声 · 温柔"), ("晓伊", "女声 · 沉静"),
              ("云健", "男声 · 磁性"), ("晓萱", "女声 · 成熟"), ("云扬", "男声 · 叙事")]
    return [{"id": voice, "name": name, "description": description}
            for voice, (name, description) in zip(DEFAULT_VOICES, labels)]


def voice_profiles(values: dict[str, str | VoiceSettings]) -> dict[str, str | VoiceProfile]:
    return {role: VoiceProfile(**value.model_dump()) if isinstance(value, VoiceSettings) else value
            for role, value in values.items()}


def public_job(job: dict) -> dict:
    result = {key: value for key, value in job.items() if key not in {"payload", "audio_path"}}
    if job["status"] == "done":
        result["audio_url"] = f"/api/jobs/{job['id']}/audio?tenant_id={job['tenant_id']}"
        result["download_url"] = f"/api/jobs/{job['id']}/audio?tenant_id={job['tenant_id']}&download=true"
        result["filename"] = chapter_audio_filename(job["chapter_title"])
    return result


def build_project(project_id: str, title: str, text: str, filename: str, encoding: str, source: Path) -> dict:
    if not text.strip():
        raise ValueError("小说文本为空")
    chapters = parse_chapters(text)
    role_voices = {}
    for segment in assign_voices([segment for chapter in chapters for segment in chapter.segments]):
        role_voices[segment.speaker] = segment.voice
    for chapter in chapters:
        chapter.segments = assign_voices(chapter.segments, role_voices)
    return {
        "id": project_id, "title": title.strip() or "未命名小说", "filename": filename,
        "encoding": encoding, "source_path": str(source), "created_at": timestamp(),
        "chapters": [asdict(chapter) for chapter in chapters], "chapter_count": len(chapters),
        "segment_count": sum(len(chapter.segments) for chapter in chapters),
        "roles": list(role_voices), "voice_map": role_voices,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        storage = Storage(settings)
        manager = JobManager(storage)
        application.state.storage = storage
        application.state.accounts = Accounts(storage)
        application.state.manager = manager
        application.state.previews = VoicePreviews(settings)
        await manager.start()
        try:
            yield
        finally:
            await application.state.previews.stop()
            await manager.stop()

    application = FastAPI(title="叙音工坊 API", version="1.0.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Tenant-ID"],
    )
    application.include_router(auth_router())

    @application.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ValueError)
    async def value_error_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def project_or_404(project_id: str, tenant_id: str) -> dict:
        project = application.state.storage.get_project(project_id, tenant_id)
        if project is None:
            raise HTTPException(404, "作品不存在")
        return project

    def job_or_404(job_id: str, tenant_id: str) -> dict:
        job = application.state.storage.get_job(job_id, tenant_id)
        if job is None:
            raise HTTPException(404, "生成任务不存在")
        return job

    @application.get("/api/health")
    def health():
        try:
            import edge_tts

            tts_available = True
        except ImportError:
            tts_available = False
        return {"ok": True, "tts": tts_available}

    @application.get("/api/config")
    def configuration(tenant: dict = Depends(require_tenant)):
        return {
            "upload_dir": str(settings.upload_dir / tenant["id"]), "audio_dir": str(settings.audio_dir / tenant["id"]),
            "data_dir": str(settings.data_dir), "workers": settings.workers,
            "connect_timeout": settings.connect_timeout, "receive_timeout": settings.receive_timeout,
        }

    @application.get("/api/voices")
    def voices():
        return {"voices": voice_catalog()}

    @application.post("/api/voices/preview")
    async def preview_voice(data: PreviewRequest, tenant: dict = Depends(require_tenant)):
        text = data.text.strip()
        if not text:
            raise ValueError("试听文本为空")
        try:
            preview_id = await application.state.previews.generate(
                VoiceProfile(**data.model_dump(exclude={"text"})), text, tenant_id=tenant["id"],
            )
        except Exception as exc:
            raise HTTPException(502, f"声线试听生成失败：{exc}") from exc
        return {"audio_url": f"/api/voices/previews/{preview_id}/audio?tenant_id={tenant['id']}"}

    @application.get("/api/voices/previews/{preview_id}/audio")
    def preview_audio(preview_id: str, tenant: dict = Depends(require_tenant)):
        if not re.fullmatch(r"[0-9a-f]{64}", preview_id):
            raise HTTPException(404, "试听音频不存在")
        path = settings.audio_dir / tenant["id"] / "previews" / f"{preview_id}.mp3"
        if not path.is_file():
            raise HTTPException(404, "试听音频不存在")
        return FileResponse(path, media_type="audio/mpeg")

    @application.get("/api/projects")
    def list_projects(tenant: dict = Depends(require_tenant)):
        return {"projects": application.state.storage.list_projects(tenant["id"])}

    @application.post("/api/projects", status_code=201)
    def create_text_project(data: TextProject, tenant: dict = Depends(require_tenant)):
        if not data.text.strip():
            raise ValueError("小说文本为空")
        project_id = uuid.uuid4().hex
        directory = settings.upload_dir / tenant["id"] / project_id
        directory.mkdir(parents=True)
        source = directory / "source.txt"
        source.write_text(data.text, encoding="utf-8")
        project = build_project(project_id, data.title, data.text, source.name, "utf-8", source)
        return application.state.storage.save_project(project, tenant["id"])

    @application.post("/api/projects/upload", status_code=201)
    def upload_project(file: UploadFile = File(...), encoding: str = Form("auto"), tenant: dict = Depends(require_tenant)):
        original_name = Path((file.filename or "novel.txt").replace("\\", "/")).name
        filename = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", original_name)
        if Path(filename).suffix.lower() not in {".txt", ".md"}:
            raise ValueError("请上传 TXT 或 Markdown 文件")
        project_id = uuid.uuid4().hex
        directory = settings.upload_dir / tenant["id"] / project_id
        directory.mkdir(parents=True)
        source = directory / filename
        try:
            with source.open("wb") as target:
                shutil.copyfileobj(file.file, target)
            text, detected_encoding = decode_novel_bytes(source.read_bytes(), encoding)
            project = build_project(project_id, Path(original_name).stem, text, original_name, detected_encoding, source)
            return application.state.storage.save_project(project, tenant["id"])
        except Exception:
            source.unlink(missing_ok=True)
            directory.rmdir()
            raise

    @application.get("/api/projects/{project_id}")
    def get_project(project_id: str, tenant: dict = Depends(require_tenant)):
        return project_or_404(project_id, tenant["id"])

    @application.patch("/api/projects/{project_id}")
    def update_project(project_id: str, data: VoiceUpdate, tenant: dict = Depends(require_tenant)):
        project = project_or_404(project_id, tenant["id"])
        profiles = voice_profiles(data.voice_map)
        for chapter in project["chapters"]:
            for segment in chapter["segments"]:
                if segment["speaker"] in profiles:
                    profile = profiles[segment["speaker"]]
                    profile = VoiceProfile(profile) if isinstance(profile, str) else profile
                    segment.update(asdict(profile))
        project["voice_map"].update({role: value.model_dump() if isinstance(value, VoiceSettings) else value
                                     for role, value in data.voice_map.items()})
        return application.state.storage.save_project(project, tenant["id"])

    @application.get("/api/jobs")
    def list_jobs(project_id: str | None = None, tenant: dict = Depends(require_tenant)):
        return {"jobs": [public_job(job) for job in application.state.storage.list_jobs(tenant["id"])
                         if project_id is None or job["project_id"] == project_id]}

    @application.post("/api/jobs", status_code=202)
    async def submit_job(data: RenderRequest, tenant: dict = Depends(require_tenant)):
        return submit_chapters(data.project_id, [data.chapter_index], data.voice_map, tenant["id"])[0]

    def submit_chapters(project_id: str, indices: list[int], values: dict[str, str | VoiceSettings], tenant_id: str) -> list[dict]:
        project = project_or_404(project_id, tenant_id)
        indices = list(dict.fromkeys(indices))
        for index in indices:
            if index < 0 or index >= len(project["chapters"]):
                raise HTTPException(404, "章节不存在")
            if not project["chapters"][index]["segments"]:
                raise ValueError(f"章节“{project['chapters'][index]['title']}”没有可配音的片段")
        profiles = voice_profiles(values)
        jobs = []
        for index in indices:
            chapter = project["chapters"][index]
            for segment in chapter["segments"]:
                if segment["speaker"] in profiles:
                    profile = profiles[segment["speaker"]]
                    profile = VoiceProfile(profile) if isinstance(profile, str) else profile
                    segment.update(asdict(profile))
            jobs.append(public_job(application.state.manager.submit(project_id, index, chapter)))
        return jobs

    @application.post("/api/jobs/batch", status_code=202)
    async def submit_batch(data: BatchRenderRequest, tenant: dict = Depends(require_tenant)):
        return {"jobs": submit_chapters(data.project_id, data.chapter_indices, data.voice_map, tenant["id"])}

    @application.get("/api/jobs/{job_id}")
    def get_job(job_id: str, tenant: dict = Depends(require_tenant)):
        return public_job(job_or_404(job_id, tenant["id"]))

    @application.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str, tenant: dict = Depends(require_tenant)):
        job = job_or_404(job_id, tenant["id"])
        if job["status"] not in {"error", "interrupted"}:
            raise HTTPException(409, "只有失败或中断的任务可以重试")
        return public_job(application.state.manager.submit(job["project_id"], job["chapter_index"], job["payload"]))

    @application.get("/api/jobs/{job_id}/audio")
    def get_audio(job_id: str, download: bool = False, tenant: dict = Depends(require_tenant)):
        job = job_or_404(job_id, tenant["id"])
        if job["status"] != "done":
            raise HTTPException(409, "音频尚未生成完成")
        path = Path(job["audio_path"]).resolve()
        if not path.is_relative_to(settings.audio_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "音频文件不存在")
        return FileResponse(
            path, media_type="audio/mpeg", filename=chapter_audio_filename(job["chapter_title"]),
            content_disposition_type="attachment" if download else "inline",
        )

    return application
