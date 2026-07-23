import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.database import engine, init_db
from app.main import app
from app.models.models import AgentConversation, AgentMessage, Project, Task
from app.services.assistant_chat_runner import run_assistant_chat_task


class AssistantChatTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.project_ids = []

    def tearDown(self):
        with Session(engine) as session:
            for project_id in self.project_ids:
                project = session.get(Project, project_id)
                if project:
                    session.delete(project)
            session.commit()

    def create_project(self, title="助手测试项目"):
        response = self.client.post(
            "/api/v1/projects/",
            json={"title": title, "description": "用于聊天测试"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        project_id = response.json()["id"]
        self.project_ids.append(project_id)
        return project_id

    def test_get_conversation_is_idempotent(self):
        project_id = self.create_project()
        first = self.client.get(f"/api/v1/projects/{project_id}/assistant/conversation")
        second = self.client.get(f"/api/v1/projects/{project_id}/assistant/conversation")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["title"], "创作助手")
        self.assertEqual(first.json()["status"], "active")

    def test_post_message_creates_user_message_and_task(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            response = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "这个故事的主题是什么？"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("task_id", body)
        self.assertEqual(body["user_message"]["role"], "user")
        self.assertEqual(body["user_message"]["content"], "这个故事的主题是什么？")

        with Session(engine) as session:
            task = session.get(Task, body["task_id"])
            self.assertIsNotNone(task)
            self.assertEqual(task.type, "assistant_chat")
            self.assertEqual(task.input_payload["user_message_id"], body["user_message"]["id"])
            messages = session.exec(
                select(AgentMessage).where(AgentMessage.project_id == project_id)
            ).all()
            self.assertEqual(len(messages), 1)

    def test_runner_writes_assistant_message(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            response = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "请给第一章起个标题建议"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]

        def fake_chat(self, messages, tools=None, tool_choice="auto", temperature=0.7):
            return {
                "role": "assistant",
                "content": "建议标题：雨夜启程",
                "tool_calls": None,
            }

        with patch(
            "app.services.assistant_chat_runner.AIService.chat_completion",
            fake_chat,
        ):
            run_assistant_chat_task(task_id)

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "completed")
            assistants = session.exec(
                select(AgentMessage)
                .where(AgentMessage.project_id == project_id)
                .where(AgentMessage.role == "assistant")
            ).all()
            self.assertEqual(len(assistants), 1)
            self.assertEqual(assistants[0].content, "建议标题：雨夜启程")
            self.assertEqual(assistants[0].task_id, task_id)
            self.assertFalse((assistants[0].payload or {}).get("streaming"))

        messages = self.client.get(f"/api/v1/projects/{project_id}/assistant/messages")
        self.assertEqual(messages.status_code, 200)
        roles = [item["role"] for item in messages.json()]
        self.assertEqual(roles, ["user", "assistant"])

    def test_empty_content_rejected(self):
        project_id = self.create_project()
        response = self.client.post(
            f"/api/v1/projects/{project_id}/assistant/messages",
            json={"content": "   "},
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_project_returns_404(self):
        response = self.client.get("/api/v1/projects/not-exist/assistant/conversation")
        self.assertEqual(response.status_code, 404)

    def test_clear_conversation_archives_old(self):
        project_id = self.create_project()
        first = self.client.get(f"/api/v1/projects/{project_id}/assistant/conversation")
        first_id = first.json()["id"]

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "旧会话消息"},
            )

        cleared = self.client.post(f"/api/v1/projects/{project_id}/assistant/conversation/clear")
        self.assertEqual(cleared.status_code, 200, cleared.text)
        new_id = cleared.json()["id"]
        self.assertNotEqual(new_id, first_id)

        messages = self.client.get(f"/api/v1/projects/{project_id}/assistant/messages")
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.json(), [])

        with Session(engine) as session:
            old = session.get(AgentConversation, first_id)
            self.assertEqual(old.status, "archived")


if __name__ == "__main__":
    unittest.main()
