import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app


class DesktopAuthTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_open_when_token_unset(self):
        env = {k: v for k, v in os.environ.items() if k not in {"COMIC_APP_AUTH_TOKEN", "COMIC_APP_AUTH_REQUIRED"}}
        with patch.dict(os.environ, env, clear=True):
            response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("app"), "AI Comic Generator")

    def test_rejects_missing_token_when_configured(self):
        with patch.dict(os.environ, {"COMIC_APP_AUTH_TOKEN": "unit-test-token"}, clear=False):
            response = self.client.get("/api/v1/health")
            self.assertEqual(response.status_code, 401)
            response = self.client.get("/api/v1/projects/")
            self.assertEqual(response.status_code, 401)

    def test_accepts_matching_token(self):
        token = "unit-test-token"
        with patch.dict(os.environ, {"COMIC_APP_AUTH_TOKEN": token}, clear=False):
            response = self.client.get(
                "/api/v1/health",
                headers={"X-Comic-App-Token": token},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")

    def test_auth_required_without_token_returns_503(self):
        env = {k: v for k, v in os.environ.items() if k != "COMIC_APP_AUTH_TOKEN"}
        env["COMIC_APP_AUTH_REQUIRED"] = "1"
        with patch.dict(os.environ, env, clear=True):
            response = self.client.get("/api/v1/projects/")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
