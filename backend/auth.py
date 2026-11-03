from __future__ import annotations

import hmac
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator


COOKIE_NAME = "voice_smiths_session"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    tenant_name: str = Field(default="我的工作空间", min_length=1, max_length=80)

    @field_validator("display_name", "tenant_name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class TenantName(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class MemberRole(BaseModel):
    role: Literal["admin", "member"] = "member"


class NewMember(MemberRole):
    email: str = Field(min_length=3, max_length=254)


def require_user(request: Request) -> dict:
    user = request.app.state.accounts.authenticate(request.cookies.get(COOKIE_NAME))
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(csrf.encode("utf-8"), user["csrf_token"].encode("utf-8")):
            raise HTTPException(403, "请求校验失败，请刷新页面后重试")
    return user


def require_tenant(request: Request, user: dict = Depends(require_user)) -> dict:
    header = request.headers.get("X-Tenant-ID")
    query = request.query_params.get("tenant_id")
    if header and query and header != query:
        raise HTTPException(400, "工作空间参数不一致")
    tenant_id = header or query
    accounts = request.app.state.accounts
    if not tenant_id:
        tenants = accounts.tenants(user["id"])
        if len(tenants) != 1:
            raise HTTPException(400, "请选择工作空间")
        tenant_id = tenants[0]["id"]
    return accounts.membership(tenant_id, user["id"])


def auth_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    def auth_payload(request: Request, user: dict, csrf: str) -> dict:
        accounts = request.app.state.accounts
        return {"user": accounts.public_user(user), "tenants": accounts.tenants(user["id"]), "csrf_token": csrf}

    def sign_in(request: Request, response: Response, user: dict) -> dict:
        settings = request.app.state.storage.settings
        token, csrf = request.app.state.accounts.create_session(user["id"])
        response.set_cookie(COOKIE_NAME, token, max_age=settings.session_hours * 3600,
                            httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
        return auth_payload(request, user, csrf)

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if not origin:
            return
        parsed = urlsplit(origin)
        if origin in request.app.state.storage.settings.cors_origins:
            return
        if parsed.scheme in {"http", "https"} and parsed.netloc == request.headers.get("host"):
            return
        raise HTTPException(403, "不允许的请求来源")

    @router.post("/auth/register", status_code=201)
    def register(data: Registration, request: Request, response: Response):
        check_origin(request)
        user = request.app.state.accounts.register(data.email, data.password, data.display_name, data.tenant_name)
        return sign_in(request, response, user)

    @router.post("/auth/login")
    def login(data: Credentials, request: Request, response: Response):
        check_origin(request)
        user = request.app.state.accounts.login(data.email, data.password)
        return sign_in(request, response, user)

    @router.get("/auth/me")
    def me(request: Request, user: dict = Depends(require_user)):
        return auth_payload(request, user, user["csrf_token"])

    @router.post("/auth/logout")
    def logout(request: Request, response: Response, user: dict = Depends(require_user)):
        request.app.state.accounts.logout(request.cookies[COOKIE_NAME])
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return {"ok": True}

    @router.get("/tenants")
    def tenants(request: Request, user: dict = Depends(require_user)):
        return {"tenants": request.app.state.accounts.tenants(user["id"])}

    @router.post("/tenants", status_code=201)
    def create_tenant(data: TenantName, request: Request, user: dict = Depends(require_user)):
        return request.app.state.accounts.create_tenant(user["id"], data.name)

    @router.patch("/tenants/{tenant_id}")
    def rename_tenant(tenant_id: str, data: TenantName, request: Request, user: dict = Depends(require_user)):
        return request.app.state.accounts.rename_tenant(tenant_id, user["id"], data.name)

    @router.get("/tenants/{tenant_id}/members")
    def members(tenant_id: str, request: Request, user: dict = Depends(require_user)):
        return {"members": request.app.state.accounts.members(tenant_id, user["id"])}

    @router.post("/tenants/{tenant_id}/members", status_code=201)
    def add_member(tenant_id: str, data: NewMember, request: Request, user: dict = Depends(require_user)):
        request.app.state.accounts.add_member(tenant_id, user["id"], data.email, data.role)
        return {"ok": True}

    @router.patch("/tenants/{tenant_id}/members/{user_id}")
    def change_member(tenant_id: str, user_id: str, data: MemberRole, request: Request, user: dict = Depends(require_user)):
        request.app.state.accounts.change_member(tenant_id, user["id"], user_id, data.role)
        return {"ok": True}

    @router.delete("/tenants/{tenant_id}/members/{user_id}")
    def remove_member(tenant_id: str, user_id: str, request: Request, user: dict = Depends(require_user)):
        request.app.state.accounts.change_member(tenant_id, user["id"], user_id, None)
        return {"ok": True}

    return router
