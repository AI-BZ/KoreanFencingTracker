"""
Auth Router tests
"""
import pytest

from services.account.app.auth.router import _is_safe_redirect


# ---------------------
# _is_safe_redirect unit tests
# ---------------------

class TestIsSafeRedirect:
    def test_allows_fencingmind_domain(self):
        assert _is_safe_redirect("https://data.fencingmind.ai/dashboard") is True

    def test_allows_fencingmind_subdomain(self):
        assert _is_safe_redirect("https://club.fencingmind.ai/roster") is True

    def test_allows_localhost(self):
        assert _is_safe_redirect("http://localhost:3000/callback") is True

    def test_allows_127(self):
        assert _is_safe_redirect("http://127.0.0.1:8080/home") is True

    def test_blocks_external_domain(self):
        assert _is_safe_redirect("https://evil.com/steal") is False

    def test_allows_relative_path(self):
        assert _is_safe_redirect("/account/me") is True

    def test_rejects_empty(self):
        assert _is_safe_redirect("") is False

    def test_rejects_none(self):
        assert _is_safe_redirect(None) is False


# ---------------------
# Endpoint tests
# ---------------------

class TestAuthProviders:
    def test_providers_returns_correct_format(self, app_client):
        resp = app_client.get("/auth/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "promotional_providers" in data
        assert "country_code" in data

    def test_providers_includes_kakao_for_kr(self, app_client):
        resp = app_client.get("/auth/providers")
        data = resp.json()
        assert "kakao" in data["providers"]

    def test_promotional_providers_includes_x(self, app_client):
        resp = app_client.get("/auth/providers")
        data = resp.json()
        assert "x" in data["promotional_providers"]


class TestLogout:
    def test_post_logout_redirects_and_clears_cookie(self, app_client):
        resp = app_client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 303
        set_cookie = resp.headers.get("set-cookie", "")
        assert "access_token" in set_cookie

    def test_get_logout_redirects_and_clears_cookie(self, app_client):
        resp = app_client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 303
        set_cookie = resp.headers.get("set-cookie", "")
        assert "access_token" in set_cookie


class TestHealthCheck:
    def test_health_check(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "account"
