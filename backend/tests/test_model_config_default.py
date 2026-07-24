import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.database import engine, init_db
from app.cruds.crud_config import get_active_config
from app.main import app
from app.models.models import ModelConfig


class ModelConfigDefaultTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        with Session(engine) as session:
            for row in session.exec(select(ModelConfig)).all():
                session.delete(row)
            session.commit()

    def create(self, **kwargs):
        payload = {
            "provider": "openai_compatible",
            "api_key": "sk-test",
            "base_url": "https://example.com/v1",
            "model_name": "model-a",
            "model_type": "text",
            "is_active": True,
            "is_default": False,
        }
        payload.update(kwargs)
        response = self.client.post("/api/v1/configs/", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_first_active_becomes_default(self):
        first = self.create(model_name="first")
        self.assertTrue(first["is_default"])
        second = self.create(model_name="second", is_default=False)
        self.assertFalse(second["is_default"])

        with Session(engine) as session:
            active = get_active_config(session, "text")
            self.assertIsNotNone(active)
            self.assertEqual(active.model_name, "first")

    def test_set_default_switches_selection(self):
        first = self.create(model_name="first")
        second = self.create(model_name="second")
        response = self.client.post(f"/api/v1/configs/{second['id']}/set-default")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["is_default"])
        self.assertTrue(body["is_active"])
        self.assertEqual(body["model_name"], "second")

        listing = self.client.get("/api/v1/configs/").json()
        defaults = [row for row in listing if row["model_type"] == "text" and row["is_default"]]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0]["id"], second["id"])

        with Session(engine) as session:
            active = get_active_config(session, "text")
            self.assertEqual(active.id, second["id"])
            old = session.get(ModelConfig, first["id"])
            self.assertFalse(old.is_default)

    def test_deactivate_default_promotes_another(self):
        first = self.create(model_name="first")
        second = self.create(model_name="second")
        self.client.post(f"/api/v1/configs/{first['id']}/set-default")

        response = self.client.put(
            f"/api/v1/configs/{first['id']}",
            json={"is_active": False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["is_active"])
        self.assertFalse(response.json()["is_default"])

        with Session(engine) as session:
            active = get_active_config(session, "text")
            self.assertEqual(active.id, second["id"])
            self.assertTrue(active.is_default)

    def test_text_and_image_defaults_are_independent(self):
        text = self.create(model_name="text-model", model_type="text")
        image = self.create(model_name="image-model", model_type="image")
        self.assertTrue(text["is_default"])
        self.assertTrue(image["is_default"])
        with Session(engine) as session:
            self.assertEqual(get_active_config(session, "text").model_name, "text-model")
            self.assertEqual(get_active_config(session, "image").model_name, "image-model")

    def test_image_and_image_edit_defaults_are_independent(self):
        image = self.create(model_name="grok-imagine-image", model_type="image")
        edit = self.create(model_name="grok-imagine-edit", model_type="image_edit")
        self.assertTrue(image["is_default"])
        self.assertTrue(edit["is_default"])
        with Session(engine) as session:
            self.assertEqual(get_active_config(session, "image").model_name, "grok-imagine-image")
            self.assertEqual(get_active_config(session, "image_edit").model_name, "grok-imagine-edit")


if __name__ == "__main__":
    unittest.main()
