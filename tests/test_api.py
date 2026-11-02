import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.core import TTSGenerator, VoiceProfile
from backend.preview import VoicePreviews
from backend.storage import Storage


TEXT = "第一章 初见\n林默：你好。\n苏晚：好久不见。\n\n第二章 重逢\n苏晚：再见。\n林默：晚安。"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.settings = Settings(data_dir=root / "metadata", upload_dir=root / "原稿", audio_dir=root / "音频", workers=1)

    def create_project(self, client):
        response = client.post("/api/projects", json={"title": "测试小说", "text": TEXT})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def wait_for_job(self, client, job_id):
        for _ in range(200):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"done", "error", "interrupted"}:
                return job
            time.sleep(0.01)
        self.fail("测试任务未完成")

    def test_original_gbk_file_and_project_are_persisted_in_custom_directory(self) -> None:
        original = TEXT.encode("gbk")
        with TestClient(create_app(self.settings)) as client:
            response = client.post("/api/projects/upload", files={"file": ("故事.txt", original, "text/plain")})
            self.assertEqual(response.status_code, 201, response.text)
            project = response.json()
            source = Path(project["source_path"])
            self.assertTrue(source.is_relative_to(self.settings.upload_dir))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(project["encoding"], "gb18030")
            self.assertEqual(project["chapter_count"], 2)
            self.assertEqual(project["chapters"][0]["segments"][0]["speaker"], "林默")
            self.assertEqual(project["chapters"][0]["segments"][0]["voice"], project["chapters"][1]["segments"][1]["voice"])
            self.assertEqual(client.get("/api/config").json()["audio_dir"], str(self.settings.audio_dir))
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get(f"/api/projects/{project['id']}").json(), project)
            self.assertEqual(len(client.get("/api/projects").json()["projects"]), 1)

    def test_upload_larger_than_five_megabytes(self) -> None:
        original = ("第一章\n" + "中文" * 900_000).encode("utf-8")
        self.assertGreater(len(original), 5 * 1024 * 1024)
        with TestClient(create_app(self.settings)) as client:
            response = client.post("/api/projects/upload", files={"file": ("large.txt", original)})
            self.assertEqual(response.status_code, 201, response.text[:200])
            self.assertEqual(Path(response.json()["source_path"]).read_bytes(), original)

    def test_invalid_encoding_does_not_replace_existing_project(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            project = self.create_project(client)
            response = client.post("/api/projects/upload", files={"file": ("bad.txt", b"\xb5")})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(len(client.get("/api/projects").json()["projects"]), 1)
            self.assertTrue(Path(project["source_path"]).is_file())

    def test_manual_big5_and_voice_settings_survive_reload(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            response = client.post("/api/projects/upload", files={"file": ("繁體.txt", "第一章\n角色：你好".encode("big5"))}, data={"encoding": "big5"})
            self.assertEqual(response.status_code, 201, response.text)
            project = response.json()
            response = client.patch(f"/api/projects/{project['id']}", json={"voice_map": {"角色": {"voice": "zh-CN-YunxiNeural", "rate": "-10%"}}})
            self.assertEqual(response.status_code, 200, response.text)
        with TestClient(create_app(self.settings)) as client:
            saved = client.get(f"/api/projects/{project['id']}").json()
            self.assertEqual(saved["chapters"][0]["segments"][0]["rate"], "-10%")
            self.assertEqual(saved["voice_map"]["角色"]["voice"], "zh-CN-YunxiNeural")

    def test_submission_is_async_deduplicated_and_download_survives_restart(self) -> None:
        release = threading.Event()

        async def generate(generator, chapter, progress=None):
            if progress:
                progress(1, len(chapter.segments), "synthesizing")
            while not release.is_set():
                await asyncio.sleep(0.005)
            directory = generator.output_dir / "chapter_001"
            directory.mkdir(parents=True)
            audio = directory / "初见.mp3"
            audio.write_bytes(b"test-audio")
            return [audio]

        with patch.object(TTSGenerator, "generate_chapter", new=generate):
            with TestClient(create_app(self.settings)) as client:
                project = self.create_project(client)
                payload = {"project_id": project["id"], "chapter_index": 0}
                response = client.post("/api/jobs", json=payload)
                self.assertEqual(response.status_code, 202, response.text)
                job = response.json()
                duplicate = client.post("/api/jobs", json=payload).json()
                self.assertEqual(job["id"], duplicate["id"])
                snapshot = client.get(f"/api/jobs/{job['id']}").json()
                self.assertIn(snapshot["status"], {"queued", "running"})
                self.assertNotIn("download_url", snapshot)
                self.assertEqual(client.get(f"/api/jobs/{job['id']}/audio").status_code, 409)
                release.set()
                complete = self.wait_for_job(client, job["id"])
                self.assertEqual(complete["status"], "done", complete)
                self.assertEqual(complete["progress"], 100)
                response = client.get(complete["download_url"])
                self.assertEqual(response.headers["content-type"], "audio/mpeg")
                self.assertEqual(response.content, b"test-audio")
                self.assertIn("attachment", response.headers["content-disposition"])
                self.assertIn("初见.mp3", unquote(response.headers["content-disposition"]))
                self.assertEqual(complete["filename"], "初见.mp3")
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get(f"/api/jobs/{job['id']}").json()["status"], "done")
            self.assertEqual(client.get(complete["audio_url"]).content, b"test-audio")

    def test_failures_are_visible_and_can_be_retried(self) -> None:
        async def fail(generator, chapter, progress=None):
            raise RuntimeError("语音服务连接失败")

        with patch.object(TTSGenerator, "generate_chapter", new=fail):
            with TestClient(create_app(self.settings)) as client:
                project = self.create_project(client)
                job = client.post("/api/jobs", json={"project_id": project["id"], "chapter_index": 0}).json()
                complete = self.wait_for_job(client, job["id"])
                self.assertEqual(complete["status"], "error")
                self.assertIn("连接失败", complete["error"])
                response = client.post(f"/api/jobs/{job['id']}/retry")
                self.assertEqual(response.status_code, 202)
                self.assertNotEqual(response.json()["id"], job["id"])

    def test_startup_marks_inflight_jobs_interrupted(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            project = self.create_project(client)
        storage = Storage(self.settings)
        job, created = storage.create_job(project["id"], 0, project["chapters"][0])
        storage.update_job(job["id"], status="running")
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get(f"/api/jobs/{job['id']}").json()["status"], "interrupted")

    def test_startup_resumes_persisted_queued_jobs(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            project = self.create_project(client)
        storage = Storage(self.settings)
        job, created = storage.create_job(project["id"], 0, project["chapters"][0])
        self.assertTrue(created)

        async def generate(generator, chapter, progress=None):
            generator.output_dir.mkdir(parents=True)
            audio = generator.output_dir / "recovered.mp3"
            audio.write_bytes(b"recovered-audio")
            return [audio]

        with patch.object(TTSGenerator, "generate_chapter", new=generate):
            with TestClient(create_app(self.settings)) as client:
                recovered = self.wait_for_job(client, job["id"])
                self.assertEqual(recovered["status"], "done", recovered)
                self.assertEqual(client.get(recovered["download_url"]).content, b"recovered-audio")

    def test_startup_cleans_completed_legacy_segments_and_keeps_download_and_source(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            project = self.create_project(client)
        storage = Storage(self.settings)
        job, created = storage.create_job(project["id"], 0, project["chapters"][0])
        self.assertTrue(created)
        target = self.settings.audio_dir / job["id"] / "chapter_001"
        target.mkdir(parents=True)
        audio = target / "chapter_001_初见.mp3"
        audio.write_bytes(b"complete-audio")
        segment = target / "0001_旁白.mp3"
        segment.write_bytes(b"segment")
        manifest = target / "manifest.json"
        manifest.write_text(json.dumps({"audio": audio.name, "segments": [{"audio": segment.name}]}), encoding="utf-8")
        storage.update_job(job["id"], status="done", audio_path=str(audio))
        with TestClient(create_app(self.settings)) as client:
            self.assertFalse(segment.exists())
            self.assertFalse(manifest.exists())
            self.assertEqual(client.get(f"/api/jobs/{job['id']}/audio").content, b"complete-audio")
            self.assertEqual(client.get(f"/api/projects/{project['id']}").json(), project)
            self.assertTrue(Path(project["source_path"]).is_file())

    def test_cors_and_unknown_resources(self) -> None:
        with TestClient(create_app(self.settings)) as client:
            response = client.options("/api/jobs", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
            self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
            self.assertEqual(client.get("/api/projects/missing").status_code, 404)
            self.assertEqual(client.get("/api/jobs/missing/audio").status_code, 404)

    def test_batch_validates_all_chapters_before_enqueuing_and_reuses_active_jobs(self) -> None:
        async def pending(generator, chapter, progress=None):
            await asyncio.sleep(30)

        application = create_app(self.settings)
        with patch.object(TTSGenerator, "generate_chapter", new=pending):
            with TestClient(application) as client:
                project = self.create_project(client)
                payload = {"project_id": project["id"], "chapter_indices": [0, 99]}
                self.assertEqual(client.post("/api/jobs/batch", json=payload).status_code, 404)
                self.assertEqual(client.get("/api/jobs").json()["jobs"], [])
                payload["chapter_indices"] = []
                self.assertEqual(client.post("/api/jobs/batch", json=payload).status_code, 422)
                payload["chapter_indices"] = [-1]
                self.assertEqual(client.post("/api/jobs/batch", json=payload).status_code, 404)
                payload.update(chapter_indices=[0, 1, 0], voice_map={"林默": "zh-CN-YunjianNeural"})
                response = client.post("/api/jobs/batch", json=payload)
                self.assertEqual(response.status_code, 202, response.text)
                jobs = response.json()["jobs"]
                self.assertEqual([job["chapter_index"] for job in jobs], [0, 1])
                repeated = client.post("/api/jobs/batch", json=payload).json()["jobs"]
                self.assertEqual([job["id"] for job in jobs], [job["id"] for job in repeated])
                stored = application.state.storage.get_job(jobs[0]["id"])
                self.assertEqual(stored["payload"]["segments"][0]["voice"], "zh-CN-YunjianNeural")

    def test_voice_preview_uses_profile_is_cached_and_survives_restart(self) -> None:
        calls = []

        async def generate(generator, segment, output_path):
            calls.append(segment)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"voice-preview")
            return output_path

        payload = {"voice": "zh-CN-YunxiNeural", "rate": "-10%", "pitch": "+5Hz", "text": "你好，欢迎试听。"}
        with patch.object(TTSGenerator, "generate_segment", new=generate):
            with TestClient(create_app(self.settings)) as client:
                response = client.post("/api/voices/preview", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                audio_url = response.json()["audio_url"]
                self.assertEqual(client.get(audio_url).content, b"voice-preview")
                self.assertEqual(client.post("/api/voices/preview", json=payload).json()["audio_url"], audio_url)
                self.assertEqual(len(calls), 1)
                self.assertEqual((calls[0].voice, calls[0].rate, calls[0].pitch), (payload["voice"], "-10%", "+5Hz"))
                self.assertEqual(client.get("/api/jobs").json()["jobs"], [])
                changed = client.post("/api/voices/preview", json={**payload, "voice": "zh-CN-XiaoxiaoNeural"})
                self.assertNotEqual(changed.json()["audio_url"], audio_url)
            with TestClient(create_app(self.settings)) as client:
                self.assertEqual(client.get(audio_url).content, b"voice-preview")
                client.post("/api/voices/preview", json=payload).raise_for_status()
                self.assertEqual(len(calls), 2)
        self.assertEqual(list((self.settings.audio_dir / "previews").glob("*.tmp.mp3")), [])

    def test_preview_failure_cleans_up_and_can_be_retried(self) -> None:
        async def fail(generator, segment, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"partial")
            raise RuntimeError("语音服务暂不可用")

        with patch.object(TTSGenerator, "generate_segment", new=fail):
            with TestClient(create_app(self.settings)) as client:
                payload = {"voice": "zh-CN-YunxiNeural", "text": "测试"}
                for attempt in range(2):
                    response = client.post("/api/voices/preview", json=payload)
                    self.assertEqual(response.status_code, 502)
                    self.assertIn("暂不可用", response.json()["detail"])
                self.assertEqual(client.post("/api/voices/preview", json={**payload, "text": "长" * 161}).status_code, 422)
                self.assertEqual(client.post("/api/voices/preview", json={**payload, "text": "  "}).status_code, 400)
                self.assertEqual(client.get("/api/voices/previews/invalid/audio").status_code, 404)
                self.assertEqual(client.get(f"/api/voices/previews/{'a' * 64}/audio").status_code, 404)
        self.assertEqual(list((self.settings.audio_dir / "previews").iterdir()), [])

    def test_concurrent_previews_share_the_same_generation(self) -> None:
        calls = []

        async def generate(generator, segment, output_path):
            calls.append(segment)
            await asyncio.sleep(0.01)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"shared-preview")
            return output_path

        async def check():
            previews = VoicePreviews(self.settings)
            profile = VoiceProfile("zh-CN-YunxiNeural")
            results = await asyncio.gather(*(previews.generate(profile, "你好") for attempt in range(4)))
            self.assertEqual(len(set(results)), 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(previews.pending, {})
            await previews.stop()

        with patch.object(TTSGenerator, "generate_segment", new=generate):
            asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
