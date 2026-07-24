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
        self.assertIn("tools_enabled", first.json())

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

    def test_concurrent_post_returns_409(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            first = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "第一条"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            second = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "第二条应被拒绝"},
            )
        self.assertEqual(second.status_code, 409, second.text)
        detail = second.json()["detail"]
        if isinstance(detail, dict):
            self.assertEqual(detail.get("task_id"), first.json()["task_id"])
            self.assertIn("回复中", detail.get("message", ""))
        else:
            self.assertIn("回复中", str(detail))

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

        def fake_stream(self, messages, temperature=0.7, on_delta=None):
            text = "建议标题：雨夜启程"
            if on_delta:
                on_delta(text)
            return text

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(True, "openai_compatible"),
        ), patch(
            "app.services.assistant_chat_runner.AIService.chat_completion",
            fake_chat,
        ), patch(
            "app.services.assistant_chat_runner.AIService.chat_completion_stream",
            fake_stream,
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

    def test_runner_streams_when_tools_disabled(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            response = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "随便聊聊"},
            )
        task_id = response.json()["task_id"]

        def fake_stream(self, messages, temperature=0.7, on_delta=None):
            if on_delta:
                on_delta("流")
                on_delta("流式回复")
            return "流式回复"

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(False, "google"),
        ), patch(
            "app.services.assistant_chat_runner.AIService.chat_completion_stream",
            fake_stream,
        ):
            run_assistant_chat_task(task_id)

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "completed")
            self.assertFalse(task.result.get("tools_enabled"))
            assistants = session.exec(
                select(AgentMessage)
                .where(AgentMessage.project_id == project_id)
                .where(AgentMessage.role == "assistant")
            ).all()
            self.assertEqual(assistants[0].content, "流式回复")

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
            active = session.exec(
                select(Task)
                .where(Task.project_id == project_id)
                .where(Task.type == "assistant_chat")
                .where(Task.status.in_(["pending", "processing"]))
            ).all()
            self.assertEqual(len(active), 0)

    def test_multi_conversation_list_and_create(self):
        project_id = self.create_project()
        default = self.client.get(f"/api/v1/projects/{project_id}/assistant/conversation")
        self.assertEqual(default.status_code, 200, default.text)
        created = self.client.post(
            f"/api/v1/projects/{project_id}/assistant/conversations",
            json={"title": "第二会话"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["title"], "第二会话")

        listed = self.client.get(f"/api/v1/projects/{project_id}/assistant/conversations")
        self.assertEqual(listed.status_code, 200, listed.text)
        titles = {item["title"] for item in listed.json()}
        self.assertIn("第二会话", titles)
        self.assertGreaterEqual(len(listed.json()), 2)

    def test_allow_writes_false_blocks_write_tools(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            response = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "把主题改成赛博", "allow_writes": False},
            )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertFalse(task.input_payload.get("allow_writes"))

        call_state = {"n": 0}

        def fake_chat(self, messages, tools=None, tool_choice="auto", temperature=0.7):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "update_project",
                                "arguments": '{"theme":"赛博"}',
                            },
                        }
                    ],
                }
            return {
                "role": "assistant",
                "content": "本轮无法写库。",
                "tool_calls": None,
            }

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(True, "openai_compatible"),
        ), patch("app.services.assistant_chat_runner.AIService.chat_completion", fake_chat):
            run_assistant_chat_task(task_id)

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "completed", task.message)
            traces = task.result.get("tool_calls") or []
            self.assertEqual(len(traces), 1)
            self.assertFalse(traces[0].get("ok"))
            self.assertTrue(traces[0].get("blocked"))
            project = session.get(Project, project_id)
            self.assertNotEqual(project.theme, "赛博")

    def test_regenerate_supersedes_old_assistant(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            first = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "给个标题"},
            )
        self.assertEqual(first.status_code, 200, first.text)
        task_id = first.json()["task_id"]

        def fake_chat(self, messages, tools=None, tool_choice="auto", temperature=0.7):
            return {
                "role": "assistant",
                "content": "旧回复",
                "tool_calls": None,
            }

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(True, "openai_compatible"),
        ), patch("app.services.assistant_chat_runner.AIService.chat_completion", fake_chat):
            run_assistant_chat_task(task_id)

        with Session(engine) as session:
            old_assistant = session.exec(
                select(AgentMessage)
                .where(AgentMessage.project_id == project_id)
                .where(AgentMessage.role == "assistant")
            ).first()
            old_id = old_assistant.id

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            regen = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages/{old_id}/regenerate",
                json={"allow_writes": True},
            )
        self.assertEqual(regen.status_code, 200, regen.text)
        new_task_id = regen.json()["task_id"]

        def fake_chat2(self, messages, tools=None, tool_choice="auto", temperature=0.7):
            return {
                "role": "assistant",
                "content": "新回复",
                "tool_calls": None,
            }

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(True, "openai_compatible"),
        ), patch("app.services.assistant_chat_runner.AIService.chat_completion", fake_chat2):
            run_assistant_chat_task(new_task_id)

        with Session(engine) as session:
            old = session.get(AgentMessage, old_id)
            self.assertTrue((old.payload or {}).get("superseded"))
            assistants = session.exec(
                select(AgentMessage)
                .where(AgentMessage.project_id == project_id)
                .where(AgentMessage.role == "assistant")
                .order_by(AgentMessage.id)
            ).all()
            self.assertEqual(len(assistants), 2)
            self.assertEqual(assistants[-1].content, "新回复")
            self.assertFalse((assistants[-1].payload or {}).get("superseded"))


if __name__ == "__main__":
    unittest.main()
