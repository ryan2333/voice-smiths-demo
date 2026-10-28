"""Local web server for the 叙音工坊 novel voice-over app.

Run with ``python app.py`` and open http://127.0.0.1:8765.  The server keeps
the browser UI deliberately small and uses the framework-free parser in
``backend.core``.  ``edge-tts`` is loaded only when audio is requested, so
text parsing and voice assignment work without an internet connection.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.core import (
    DEFAULT_VOICES,
    Chapter,
    Segment,
    TTSGenerator,
    VoiceProfile,
    assign_voices,
    parse_chapters,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
EXPORT_ROOT = ROOT / "exports"
MAX_TEXT_BYTES = 5 * 1024 * 1024
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"Unsupported value: {type(value)!r}")


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("请求体长度无效") from exc
    if length <= 0 or length > MAX_TEXT_BYTES:
        raise ValueError("请求体为空或超过 5 MB 限制")
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("请求体必须是 UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def _segment_from_payload(payload: dict[str, Any], index: int) -> Segment:
    text = str(payload.get("text", "")).strip()
    speaker = str(payload.get("speaker", "旁白")).strip() or "旁白"
    return Segment(
        id=int(payload.get("id", index)),
        text=text,
        speaker=speaker,
        is_dialogue=bool(payload.get("is_dialogue", speaker != "旁白")),
        voice=str(payload.get("voice")) if payload.get("voice") else None,
        rate=str(payload.get("rate", "+0%")),
        pitch=str(payload.get("pitch", "+0Hz")),
        volume=str(payload.get("volume", "+0%")),
    )


def _chapter_from_payload(payload: dict[str, Any]) -> Chapter:
    if not isinstance(payload, dict):
        raise ValueError("章节数据格式无效")
    segments = [_segment_from_payload(item, index) for index, item in enumerate(payload.get("segments", []), 1)]
    return Chapter(
        number=int(payload.get("number", 1)),
        title=str(payload.get("title", "正文")),
        text=str(payload.get("text", "")),
        segments=segments,
    )


def _voice_map(payload: Any) -> dict[str, VoiceProfile | str]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("voice_map 必须是对象")
    result: dict[str, VoiceProfile | str] = {}
    for speaker, value in payload.items():
        if isinstance(value, str):
            result[str(speaker)] = value
        elif isinstance(value, dict):
            result[str(speaker)] = VoiceProfile(
                voice=str(value.get("voice", DEFAULT_VOICES[0])),
                rate=str(value.get("rate", "+0%")),
                pitch=str(value.get("pitch", "+0Hz")),
                volume=str(value.get("volume", "+0%")),
            )
    return result


def _voice_catalog() -> list[dict[str, str]]:
    labels = {
        "zh-CN-XiaoxiaoNeural": ("晓晓", "女声 · 清亮"),
        "zh-CN-YunxiNeural": ("云希", "男声 · 温柔"),
        "zh-CN-XiaoyiNeural": ("晓伊", "女声 · 沉静"),
        "zh-CN-YunjianNeural": ("云健", "男声 · 磁性"),
        "zh-CN-XiaoxuanNeural": ("晓萱", "女声 · 成熟"),
        "zh-CN-YunyangNeural": ("云扬", "男声 · 叙事"),
    }
    return [
        {"id": voice, "name": labels.get(voice, (voice, "中文"))[0], "description": labels.get(voice, (voice, "中文"))[1]}
        for voice in DEFAULT_VOICES
    ]


def _new_job() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{secrets.token_hex(4)}"


def _render_job(job_id: str, chapter: Chapter, voice_map: dict[str, VoiceProfile | str]) -> None:
    job_dir = EXPORT_ROOT / job_id
    try:
        assigned = assign_voices(chapter.segments, voice_map)
        chapter.segments = assigned
        generator = TTSGenerator(job_dir)
        paths = generator.generate_chapter_sync(chapter, segments=assigned)
        archive_path = EXPORT_ROOT / f"{job_id}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, path.relative_to(job_dir))
            manifest = job_dir / "manifest.json"
            if manifest.exists():
                archive.write(manifest, manifest.relative_to(job_dir))
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "done",
                "chapter": asdict(chapter),
                "archive": str(archive_path),
                "files": [path.name for path in paths],
            }
    except Exception as exc:  # keep errors available to the browser as JSON
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "error", "error": str(exc)}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "VoiceSmiths/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            _json_response(self, {"ok": True, "tts": _tts_available()})
            return
        if parsed.path == "/api/voices":
            _json_response(self, {"voices": _voice_catalog()})
            return
        if parsed.path.startswith("/api/jobs/"):
            self._get_job(parsed.path.removeprefix("/api/jobs/"))
            return
        if parsed.path == "/api/download":
            self._download(parse_qs(parsed.query).get("job", [""])[0])
            return
        self._serve_static(parsed.path)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        relative = unquote(parsed.path).lstrip("/") or "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.end_headers()
            return
        if not candidate.is_file():
            candidate = WEB_ROOT / "index.html"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        try:
            data = _read_json(self)
            if self.path == "/api/parse":
                self._parse(data)
            elif self.path == "/api/render":
                self._render(data)
            else:
                _json_response(self, {"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            _json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            _json_response(self, {"error": f"服务器错误：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _parse(self, data: dict[str, Any]) -> None:
        text = str(data.get("text", "")).strip()
        if not text:
            raise ValueError("请先粘贴或上传小说文本")
        chapters = parse_chapters(text)
        roles: list[str] = []
        for chapter in chapters:
            for segment in chapter.segments:
                if segment.speaker not in roles:
                    roles.append(segment.speaker)
            chapter.segments = assign_voices(chapter.segments)
        _json_response(self, {"chapters": chapters, "roles": roles, "voices": _voice_catalog()})

    def _render(self, data: dict[str, Any]) -> None:
        chapter = _chapter_from_payload(data.get("chapter", {}))
        if not chapter.segments:
            raise ValueError("章节没有可配音的片段")
        job_id = _new_job()
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "queued", "chapter": asdict(chapter)}
        thread = threading.Thread(target=_render_job, args=(job_id, chapter, _voice_map(data.get("voice_map"))), daemon=True)
        thread.start()
        _json_response(self, {"job_id": job_id, "status": "queued"}, HTTPStatus.ACCEPTED)

    def _get_job(self, job_id: str) -> None:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if job is None:
            _json_response(self, {"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
            return
        payload = dict(job)
        if payload.get("status") == "done":
            payload["download_url"] = f"/api/download?job={job_id}"
        _json_response(self, payload)

    def _download(self, job_id: str) -> None:
        if not job_id or any(part in {"", ".", ".."} for part in Path(job_id).parts):
            _json_response(self, {"error": "任务编号无效"}, HTTPStatus.BAD_REQUEST)
            return
        archive = EXPORT_ROOT / f"{job_id}.zip"
        if not archive.is_file():
            _json_response(self, {"error": "音频尚未生成"}, HTTPStatus.NOT_FOUND)
            return
        body = archive.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="voice-{job_id}.zip"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        relative = unquote(path).lstrip("/") or "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            _json_response(self, {"error": "文件路径无效"}, HTTPStatus.BAD_REQUEST)
            return
        if not candidate.is_file():
            candidate = WEB_ROOT / "index.html"
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def main() -> None:
    host = os.environ.get("VOICE_SMITHS_HOST", "127.0.0.1")
    port = int(os.environ.get("VOICE_SMITHS_PORT", "8765"))
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"叙音工坊已启动：http://{host}:{port}")
    print("提示：安装 edge-tts 后即可生成真实中文语音：pip install edge-tts")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
