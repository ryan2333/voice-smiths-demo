from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid

from fastapi import HTTPException

from .storage import Storage, timestamp


def normalize_email(email: str) -> str:
    email = email.strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("请输入有效的邮箱地址")
    return email


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        _, salt, _ = encoded.split("$")
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except (ValueError, TypeError):
        return False


DUMMY_PASSWORD_HASH = password_hash("unavailable-user", "00" * 16)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Accounts:
    def __init__(self, storage: Storage):
        self.storage = storage
        with storage.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memberships (
                    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, user_id), CHECK (role IN ('owner', 'admin', 'member'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    email TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_owner ON memberships(tenant_id) WHERE role='owner';
            """)
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
            connection.execute("DELETE FROM login_attempts WHERE started_at<?", (time.time() - 900,))
            if connection.execute("SELECT 1 FROM projects WHERE tenant_id='legacy' LIMIT 1").fetchone():
                connection.execute("INSERT OR IGNORE INTO tenants VALUES ('legacy', '历史工作空间', ?)", (timestamp(),))
        self._bootstrap()

    @staticmethod
    def public_user(user) -> dict:
        return {key: user[key] for key in ("id", "email", "display_name")}

    def register(self, email: str, password: str, display_name: str, tenant_name: str) -> dict:
        email = normalize_email(email)
        user_id, tenant_id = uuid.uuid4().hex, uuid.uuid4().hex
        encoded = password_hash(password)
        try:
            with self.storage.connect() as connection:
                connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)", (user_id, email, display_name, encoded, timestamp()))
                connection.execute("INSERT INTO tenants VALUES (?, ?, ?)", (tenant_id, tenant_name, timestamp()))
                connection.execute("INSERT INTO memberships VALUES (?, ?, 'owner')", (tenant_id, user_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "该邮箱已注册") from exc
        return {"id": user_id, "email": email, "display_name": display_name}

    def login(self, email: str, password: str) -> dict:
        email = normalize_email(email)
        now = time.time()
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = connection.execute("SELECT * FROM login_attempts WHERE email=?", (email,)).fetchone()
            if attempt and attempt["started_at"] > now - 900 and attempt["attempts"] >= 10:
                raise HTTPException(429, "登录尝试过多，请 15 分钟后重试")
            connection.execute(
                "INSERT INTO login_attempts VALUES (?, 1, ?) ON CONFLICT(email) DO UPDATE SET "
                "attempts=CASE WHEN started_at<? THEN 1 ELSE attempts+1 END, "
                "started_at=CASE WHEN started_at<? THEN excluded.started_at ELSE started_at END",
                (email, now, now - 900, now - 900),
            )
            user = connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        encoded = user["password_hash"] if user else DUMMY_PASSWORD_HASH
        valid = password_matches(password, encoded)
        if not user or not valid:
            raise HTTPException(401, "邮箱或密码不正确")
        with self.storage.connect() as connection:
            connection.execute("DELETE FROM login_attempts WHERE email=?", (email,))
        return self.public_user(user)

    def create_session(self, user_id: str) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.storage.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                               (token_hash(token), user_id, csrf, time.time() + self.storage.settings.session_hours * 3600))
        return token, csrf

    def authenticate(self, token: str | None) -> dict:
        if not token or len(token) > 128:
            raise HTTPException(401, "请先登录")
        with self.storage.connect() as connection:
            row = connection.execute(
                "SELECT users.id, users.email, users.display_name, sessions.csrf_token FROM sessions "
                "JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND sessions.expires_at>?",
                (token_hash(token), time.time()),
            ).fetchone()
        if row is None:
            raise HTTPException(401, "登录已过期，请重新登录")
        return dict(row)

    def logout(self, token: str) -> None:
        with self.storage.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    def tenants(self, user_id: str) -> list[dict]:
        with self.storage.connect() as connection:
            rows = connection.execute(
                "SELECT tenants.*, memberships.role FROM tenants JOIN memberships ON tenants.id=memberships.tenant_id "
                "WHERE memberships.user_id=? ORDER BY tenants.created_at, tenants.id", (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def membership(self, tenant_id: str, user_id: str) -> dict:
        with self.storage.connect() as connection:
            row = connection.execute(
                "SELECT tenants.*, memberships.role FROM tenants JOIN memberships ON tenants.id=memberships.tenant_id "
                "WHERE tenants.id=? AND memberships.user_id=?", (tenant_id, user_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "工作空间不存在或你没有访问权限")
        return dict(row)

    def create_tenant(self, user_id: str, name: str) -> dict:
        tenant_id = uuid.uuid4().hex
        with self.storage.connect() as connection:
            connection.execute("INSERT INTO tenants VALUES (?, ?, ?)", (tenant_id, name, timestamp()))
            connection.execute("INSERT INTO memberships VALUES (?, ?, 'owner')", (tenant_id, user_id))
        return self.membership(tenant_id, user_id)

    def rename_tenant(self, tenant_id: str, user_id: str, name: str) -> dict:
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._manager(connection, tenant_id, user_id)
            connection.execute("UPDATE tenants SET name=? WHERE id=?", (name, tenant_id))
        return self.membership(tenant_id, user_id)

    def members(self, tenant_id: str, user_id: str) -> list[dict]:
        self.membership(tenant_id, user_id)
        with self.storage.connect() as connection:
            rows = connection.execute(
                "SELECT users.id, users.email, users.display_name, memberships.role FROM memberships "
                "JOIN users ON users.id=memberships.user_id WHERE memberships.tenant_id=? "
                "ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, users.created_at", (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _manager(connection, tenant_id: str, user_id: str):
        row = connection.execute("SELECT role FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, user_id)).fetchone()
        if not row or row["role"] not in {"owner", "admin"}:
            raise HTTPException(403, "需要工作空间所有者或管理员权限")
        return row["role"]

    def add_member(self, tenant_id: str, user_id: str, email: str, role: str) -> None:
        email = normalize_email(email)
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            manager_role = self._manager(connection, tenant_id, user_id)
            if role == "admin" and manager_role != "owner":
                raise HTTPException(403, "只有所有者可以任命管理员")
            target = connection.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not target:
                raise HTTPException(404, "该邮箱尚未注册，请先让成员注册账号")
            try:
                connection.execute("INSERT INTO memberships VALUES (?, ?, ?)", (tenant_id, target["id"], role))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "该用户已在工作空间中") from exc

    def change_member(self, tenant_id: str, user_id: str, target_id: str, role: str | None) -> None:
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            caller = connection.execute("SELECT role FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, user_id)).fetchone()
            target = connection.execute("SELECT role FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, target_id)).fetchone()
            if not caller:
                raise HTTPException(404, "工作空间不存在")
            if not target:
                raise HTTPException(404, "成员不存在")
            if target["role"] == "owner":
                raise HTTPException(409, "所有者不能被移除或降级")
            if role is not None:
                if caller["role"] != "owner":
                    raise HTTPException(403, "只有所有者可以修改角色")
                connection.execute("UPDATE memberships SET role=? WHERE tenant_id=? AND user_id=?", (role, tenant_id, target_id))
            else:
                allowed = user_id == target_id or caller["role"] == "owner" or (caller["role"] == "admin" and target["role"] == "member")
                if not allowed:
                    raise HTTPException(403, "没有移除该成员的权限")
                connection.execute("DELETE FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, target_id))

    def _bootstrap(self) -> None:
        settings = self.storage.settings
        if not settings.admin_email and not settings.admin_password:
            return
        if not settings.admin_email or len(settings.admin_password) < 10 or len(settings.admin_password) > 128:
            raise ValueError("初始化管理员需要同时设置邮箱和 10–128 位密码")
        email = normalize_email(settings.admin_email)
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user and not password_matches(settings.admin_password, user["password_hash"]):
                raise ValueError("初始化管理员密码与现有账号不匹配，请检查配置")
            user_id = user["id"] if user else uuid.uuid4().hex
            if not user:
                connection.execute("INSERT INTO users VALUES (?, ?, '管理员', ?, ?)",
                                   (user_id, email, password_hash(settings.admin_password), timestamp()))
            legacy = connection.execute("SELECT id FROM tenants WHERE id='legacy'").fetchone()
            owner = connection.execute("SELECT user_id FROM memberships WHERE tenant_id='legacy' AND role='owner'").fetchone()
            if legacy and not owner:
                connection.execute("INSERT INTO memberships VALUES ('legacy', ?, 'owner')", (user_id,))
            if not connection.execute("SELECT 1 FROM memberships WHERE user_id=?", (user_id,)).fetchone():
                tenant_id = uuid.uuid4().hex
                connection.execute("INSERT INTO tenants VALUES (?, '管理员工作空间', ?)", (tenant_id, timestamp()))
                connection.execute("INSERT INTO memberships VALUES (?, ?, 'owner')", (tenant_id, user_id))
