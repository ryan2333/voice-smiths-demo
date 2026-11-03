import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from backend.accounts import password_matches, token_hash
from backend.api import create_app
from backend.auth import COOKIE_NAME
from backend.config import Settings


PASSWORD = "test-password-12345"


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.settings = Settings(data_dir=root, upload_dir=root / "uploads", audio_dir=root / "audio")
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def register(self, email="owner@example.com", name="读者"):
        response = self.client.post("/api/auth/register", json={
            "email": email, "password": PASSWORD, "display_name": name, "tenant_name": f"{name}的空间",
        })
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        token = response.cookies[COOKIE_NAME]
        return {"user": data["user"], "tenant": data["tenants"][0], "token": token, "headers": {
            "Cookie": f"{COOKIE_NAME}={token}", "X-CSRF-Token": data["csrf_token"], "X-Tenant-ID": data["tenants"][0]["id"],
        }}

    def project(self, identity):
        response = self.client.post("/api/projects", headers=identity["headers"], json={"title": "私有小说", "text": "第一章 初见\n林默：你好。"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_anonymous_access_and_forged_headers_cannot_read_or_write(self):
        owner = self.register()
        project = self.project(owner)
        headers = {"Cookie": "", "X-Tenant-ID": owner["tenant"]["id"]}
        for path in ("/api/config", "/api/projects", f"/api/projects/{project['id']}", "/api/jobs", "/api/jobs/unknown/audio", "/api/tenants"):
            self.assertEqual(self.client.get(path, headers=headers).status_code, 401, path)
        response = self.client.post("/api/projects", headers=headers, json={"text": "盗用"})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(self.client.get("/api/health", headers=headers).json()["ok"])

    def test_registration_normalizes_email_and_stores_only_password_and_session_hashes(self):
        owner = self.register(" Owner@Example.com ")
        self.assertEqual(owner["user"]["email"], "owner@example.com")
        with self.app.state.storage.connect() as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            session = connection.execute("SELECT * FROM sessions").fetchone()
        self.assertNotEqual(user["password_hash"], PASSWORD)
        self.assertTrue(password_matches(PASSWORD, user["password_hash"]))
        self.assertEqual(session["token_hash"], token_hash(owner["token"]))
        response = self.client.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        duplicate = self.client.post("/api/auth/register", json={"email": "owner@example.com", "password": PASSWORD, "display_name": "重复"})
        self.assertEqual(duplicate.status_code, 409)
        invalid = self.client.post("/api/auth/register", json={"email": "bad", "password": "123", "display_name": ""})
        self.assertEqual(invalid.status_code, 422)

    def test_csrf_is_required_and_logout_revokes_the_session(self):
        owner = self.register()
        headers = {key: value for key, value in owner["headers"].items() if key != "X-CSRF-Token"}
        response = self.client.post("/api/projects", headers=headers, json={"text": "你好"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/auth/logout", headers=headers, json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers=owner["headers"], json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=owner["headers"]).status_code, 401)

    def test_expired_session_and_repeated_wrong_passwords(self):
        owner = self.register()
        with self.app.state.storage.connect() as connection:
            connection.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
        self.assertEqual(self.client.get("/api/auth/me", headers=owner["headers"]).status_code, 401)
        for attempt in range(10):
            response = self.client.post("/api/auth/login", json={"email": owner["user"]["email"], "password": "incorrect"})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login", json={"email": owner["user"]["email"], "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        with self.app.state.storage.connect() as connection:
            connection.execute("UPDATE login_attempts SET started_at=?", (time.time() - 901,))
        response = self.client.post("/api/auth/login", json={"email": owner["user"]["email"], "password": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def test_cross_tenant_projects_jobs_downloads_and_previews_are_inaccessible(self):
        owner = self.register()
        project = self.project(owner)
        job, _ = self.app.state.storage.create_job(project["id"], 0, project["chapters"][0])
        directory = self.settings.audio_dir / owner["tenant"]["id"] / job["id"]
        directory.mkdir(parents=True)
        audio = directory / "初见.mp3"
        audio.write_bytes(b"private-audio")
        self.app.state.storage.update_job(job["id"], status="done", audio_path=str(audio))
        preview_id = "a" * 64
        preview = self.settings.audio_dir / owner["tenant"]["id"] / "previews" / f"{preview_id}.mp3"
        preview.parent.mkdir()
        preview.write_bytes(b"private-preview")
        other = self.register("other@example.com", "另一位读者")
        self.assertEqual(self.client.get("/api/projects", headers=other["headers"]).json()["projects"], [])
        self.assertEqual(self.client.get("/api/jobs", headers=other["headers"]).json()["jobs"], [])
        for path in (f"/api/projects/{project['id']}", f"/api/jobs/{job['id']}", f"/api/jobs/{job['id']}/audio", f"/api/voices/previews/{preview_id}/audio"):
            self.assertEqual(self.client.get(path, headers=other["headers"]).status_code, 404, path)
        self.assertEqual(self.client.patch(f"/api/projects/{project['id']}", headers=other["headers"], json={"voice_map": {}}).status_code, 404)
        for path, payload in (("/api/jobs", {"project_id": project["id"], "chapter_index": 0}), ("/api/jobs/batch", {"project_id": project["id"], "chapter_indices": [0]}), (f"/api/jobs/{job['id']}/retry", {})):
            self.assertEqual(self.client.post(path, headers=other["headers"], json=payload).status_code, 404)
        stolen = {**other["headers"], "X-Tenant-ID": owner["tenant"]["id"]}
        self.assertEqual(self.client.get("/api/projects", headers=stolen).status_code, 404)
        cookie_only = {"Cookie": other["headers"]["Cookie"]}
        url = f"/api/jobs/{job['id']}/audio?tenant_id={owner['tenant']['id']}"
        self.assertEqual(self.client.get(url, headers=cookie_only).status_code, 404)
        self.assertEqual(self.client.get(url, headers={"Cookie": ""}).status_code, 401)
        self.assertEqual(self.client.get(url, headers={"Cookie": owner["headers"]["Cookie"]}).content, b"private-audio")
        self.assertTrue(Path(project["source_path"]).is_relative_to(self.settings.upload_dir / owner["tenant"]["id"]))

    def test_member_permissions_and_removal_take_effect_immediately(self):
        owner = self.register()
        project = self.project(owner)
        member = self.register("member@example.com", "成员")
        admin = self.register("admin@example.com", "管理员")
        base = f"/api/tenants/{owner['tenant']['id']}"
        for identity, role in ((member, "member"), (admin, "admin")):
            response = self.client.post(base + "/members", headers=owner["headers"], json={"email": identity["user"]["email"], "role": role})
            self.assertEqual(response.status_code, 201, response.text)
        member_headers = {**member["headers"], "X-Tenant-ID": owner["tenant"]["id"]}
        admin_headers = {**admin["headers"], "X-Tenant-ID": owner["tenant"]["id"]}
        self.assertEqual(self.client.get(f"/api/projects/{project['id']}", headers=member_headers).status_code, 200)
        self.assertEqual(self.client.patch(base, headers=member_headers, json={"name": "篡改"}).status_code, 403)
        self.assertEqual(self.client.post(base + "/members", headers=member_headers, json={"email": "third@example.com"}).status_code, 403)
        self.assertEqual(self.client.patch(base + f"/members/{member['user']['id']}", headers=admin_headers, json={"role": "admin"}).status_code, 403)
        self.assertEqual(self.client.delete(base + f"/members/{owner['user']['id']}", headers=admin_headers).status_code, 409)
        self.assertEqual(self.client.patch(base + f"/members/{owner['user']['id']}", headers=owner["headers"], json={"role": "member"}).status_code, 409)
        self.assertEqual(self.client.delete(base + f"/members/{member['user']['id']}", headers=admin_headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/projects/{project['id']}", headers=member_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/projects", headers=member["headers"]).status_code, 200)
        self.assertEqual(self.client.patch(base, headers=admin_headers, json={"name": "团队空间"}).status_code, 200)

    def test_one_user_can_switch_between_isolated_tenants_and_membership_persists(self):
        owner = self.register()
        self.project(owner)
        response = self.client.post("/api/tenants", headers=owner["headers"], json={"name": "第二个空间"})
        self.assertEqual(response.status_code, 201)
        second = response.json()
        headers = {**owner["headers"], "X-Tenant-ID": second["id"]}
        self.assertEqual(self.client.get("/api/projects", headers=headers).json()["projects"], [])
        self.assertEqual(len(self.client.get("/api/tenants", headers=headers).json()["tenants"]), 2)
        inconsistent = self.client.get(f"/api/projects?tenant_id={owner['tenant']['id']}", headers=headers)
        self.assertEqual(inconsistent.status_code, 400)

    def test_untrusted_origin_cannot_log_in_or_register(self):
        response = self.client.post("/api/auth/register", headers={"Origin": "https://untrusted.example"}, json={"email": "test@example.com", "password": PASSWORD, "display_name": "测试"})
        self.assertEqual(response.status_code, 403)
        response = self.client.options("/api/projects", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type,X-CSRF-Token,X-Tenant-ID"})
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        response = self.client.post("/api/auth/register", headers={"Origin": "http://127.0.0.1:4173"}, json={"email": "preview@example.com", "password": PASSWORD, "display_name": "预览用户"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:4173")


class LegacyMigrationTests(unittest.TestCase):
    def test_legacy_data_requires_explicit_admin_claim_and_old_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(data_dir=root, upload_dir=root / "uploads", audio_dir=root / "audio")
            source = root / "old-source.txt"
            source.write_text("历史小说", encoding="utf-8")
            project = {"id": "old-project", "title": "历史小说", "created_at": "2026-11-01", "source_path": str(source), "chapters": [], "voice_map": {}}
            with sqlite3.connect(root / "voice-smiths.sqlite3") as connection:
                connection.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT, created_at TEXT, payload TEXT)")
                connection.execute("INSERT INTO projects VALUES (?, ?, ?, ?)", (project["id"], project["title"], project["created_at"], json.dumps(project)))
            with TestClient(create_app(settings)) as client:
                response = client.post("/api/auth/register", json={"email": "first@example.com", "password": PASSWORD, "display_name": "首位注册者"})
                self.assertEqual(response.status_code, 201)
                self.assertNotIn("legacy", [tenant["id"] for tenant in response.json()["tenants"]])
                self.assertEqual(client.get("/api/projects").json()["projects"], [])
                self.assertEqual(client.get("/api/projects/old-project").status_code, 404)
            claimed = replace(settings, admin_email="operator@example.com", admin_password=PASSWORD)
            with TestClient(create_app(claimed)) as client:
                response = client.post("/api/auth/login", json={"email": "operator@example.com", "password": PASSWORD})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["tenants"][0]["id"], "legacy")
                self.assertEqual(client.get("/api/projects/old-project").json(), project)
            self.assertEqual(source.read_text(encoding="utf-8"), "历史小说")


if __name__ == "__main__":
    unittest.main()
