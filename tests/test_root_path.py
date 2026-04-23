# Copyright 2024-2026 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for ROOT_PATH configuration.

Verifies that the FastAPI app respects the ROOT_PATH setting so that
it works correctly behind a reverse proxy with a path prefix (e.g. /aura),
including FastUI prebuilt_html parameters for the React SPA.
"""

import pytest
from fastapi.testclient import TestClient

from aura.settings import Settings


@pytest.fixture()
def test_app():
    """Create the FastAPI app for testing."""
    from aura import app

    return app


@pytest.fixture()
def app_with_root_path(test_app):
    """Temporarily set root_path on the app and ROOT_PATH on settings."""
    from aura.settings import settings

    original_app_root = test_app.root_path
    original_settings_root = settings.ROOT_PATH
    test_app.root_path = "/aura"
    settings.ROOT_PATH = "/aura"
    # Reset cached OpenAPI schema so it regenerates with new root_path
    test_app.openapi_schema = None
    yield test_app
    test_app.root_path = original_app_root
    settings.ROOT_PATH = original_settings_root
    test_app.openapi_schema = None


class TestRootPathConfig:
    def test_default_root_path_is_empty(self):
        settings = Settings.model_construct()
        assert settings.ROOT_PATH == ""

    def test_root_path_from_env(self, monkeypatch):
        monkeypatch.setenv("ROOT_PATH", "/aura")
        settings = Settings()
        assert settings.ROOT_PATH == "/aura"


class TestRootPathOpenApi:
    def test_openapi_available_without_root_path(self, test_app):
        client = TestClient(test_app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["openapi"]

    def test_openapi_available_with_root_path(self, app_with_root_path):
        client = TestClient(app_with_root_path)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["openapi"]

    def test_openapi_servers_contains_root_path(self, app_with_root_path):
        client = TestClient(app_with_root_path)
        spec = client.get("/openapi.json").json()
        server_urls = [s["url"] for s in spec.get("servers", [])]
        assert "/aura" in server_urls


class TestRootPathRoutes:
    def test_routes_work_with_root_path(self, app_with_root_path):
        """root_path must not change route matching — API paths stay the same."""
        client = TestClient(app_with_root_path)
        assert client.get("/healthcheck").status_code == 200
        assert client.get("/api/").status_code == 200

    def test_healthcheck_works_without_root_path(self, test_app):
        client = TestClient(test_app)
        assert client.get("/healthcheck").status_code == 200


class TestRootPathPrebuiltHtml:
    def test_html_landing_without_root_path(self, test_app):
        """Without ROOT_PATH, prebuilt_html uses defaults."""
        client = TestClient(test_app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_html_landing_with_root_path(self, app_with_root_path):
        """With ROOT_PATH, prebuilt_html receives api_root_url and api_path_strip."""
        client = TestClient(app_with_root_path)
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        # The prebuilt HTML should reference the prefixed API URL
        assert "/aura/api" in html

    def test_html_landing_no_prefix_in_default(self, test_app):
        """Without ROOT_PATH, the HTML should not contain path prefix references."""
        client = TestClient(test_app)
        resp = client.get("/")
        html = resp.text
        # api_path_strip should not appear in the default case
        assert "api_path_strip" not in html
