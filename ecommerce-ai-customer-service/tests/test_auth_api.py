"""鉴权 HTTP 接口测试：/auth/login、/auth/me、/auth/logout。"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------
def test_login_with_valid_credentials(client):
    resp = client.post(
        "/auth/login",
        json={"user_id": "u1001", "password": "demo123456"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body and body["token"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    assert body["user"]["user_id"] == "u1001"
    assert body["user"]["name"] == "张伟"
    # 脱敏：不应回传 salt / password_hash
    assert "salt" not in body["user"]
    assert "password_hash" not in body["user"]


def test_login_with_invalid_password(client):
    resp = client.post(
        "/auth/login",
        json={"user_id": "u1001", "password": "wrong"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_credentials"


def test_login_with_unknown_user(client):
    """不存在的 user 也应返回 401，但不区分"用户不存在"与"密码错误"。"""
    resp = client.post(
        "/auth/login",
        json={"user_id": "nobody", "password": "whatever"},
    )
    assert resp.status_code == 401


def test_login_with_missing_fields(client):
    """必填字段缺失应返回 422。"""
    resp = client.post("/auth/login", json={"user_id": "u1001"})
    assert resp.status_code == 422


def test_login_has_no_retry_limit_for_personal_mode(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "login_rate_limit_enabled", False)
    for _ in range(8):
        assert client.post("/auth/login", json={"user_id": "u1001", "password": "wrong"}).status_code == 401


def test_register_creates_user_and_logs_in(client, tmp_path, monkeypatch):
    """注册写入独立临时 users.json，避免污染演示数据。"""
    import shutil

    from app.auth.users import reload_users
    from app.config import settings

    with monkeypatch.context() as scoped:
        shutil.copy(settings.data_path / "users.json", tmp_path / "users.json")
        scoped.setattr(settings, "data_dir", str(tmp_path))
        reload_users()
        response = client.post(
            "/auth/register",
            json={"user_id": "personal_user", "password": "safe-pass-123", "name": "个人用户"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token"]
        assert body["user"]["user_id"] == "personal_user"
        assert "password_hash" not in body["user"]
        duplicate = client.post(
            "/auth/register",
            json={"user_id": "personal_user", "password": "safe-pass-123", "name": "个人用户"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "registration_invalid"
    reload_users()


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------
def test_me_with_valid_token(client, auth_headers):
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u1001"
    assert body["email"] == "u1001@demo.nora"


def test_me_without_token_returns_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"


def test_me_with_invalid_token_returns_401(client):
    resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not.a.valid.token"},
    )
    assert resp.status_code == 401


def test_me_with_malformed_header_returns_401(client):
    """非 Bearer scheme 也应返回 401。"""
    resp = client.get(
        "/auth/me",
        headers={"Authorization": "Basic abc123"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/logout
# ---------------------------------------------------------------------------
def test_logout_returns_204(client, auth_headers):
    resp = client.post("/auth/logout", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get("/auth/me", headers=auth_headers).status_code == 401


def test_logout_without_token_requires_authentication(client):
    resp = client.post("/auth/logout")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/users 持久层（不直接走 HTTP，但保证演示账号确实存在）
# ---------------------------------------------------------------------------
def test_demo_users_loaded():
    from app.auth.users import load_users, reload_users
    reload_users()
    users = load_users()
    assert len(users) >= 3
    user_ids = {u["user_id"] for u in users}
    assert {"u1001", "u1002", "u1003"}.issubset(user_ids)


def test_verify_user_returns_sanitized_dict():
    from app.auth.users import verify_user
    user = verify_user("u1001", "demo123456")
    assert user is not None
    assert user["user_id"] == "u1001"
    assert "password_hash" not in user
    assert "salt" not in user


def test_verify_user_wrong_password_returns_none():
    from app.auth.users import verify_user
    assert verify_user("u1001", "wrong") is None


def test_verify_user_unknown_user_returns_none():
    from app.auth.users import verify_user
    assert verify_user("ghost", "demo123456") is None
