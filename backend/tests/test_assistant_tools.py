import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.database import engine, init_db
from app.main import app
from app.models.models import Chapter, Character, Project, SettingEntry, Task
from app.services.assistant_chat_runner import run_assistant_chat_task
from app.services.assistant_tools import ToolError, execute_tool, openai_tool_definitions


class AssistantToolsTest(unittest.TestCase):
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

    def create_project(self, title="工具测试项目"):
        response = self.client.post(
            "/api/v1/projects/",
            json={"title": title, "description": "desc", "theme": "仙侠"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        project_id = response.json()["id"]
        self.project_ids.append(project_id)
        return project_id

    def test_tool_definitions_cover_read_and_write(self):
        names = {item["function"]["name"] for item in openai_tool_definitions()}
        for required in (
            "get_project",
            "list_chapters",
            "get_chapter",
            "search_settings",
            "search_characters",
            "update_project",
            "create_chapter",
            "update_chapter",
            "create_setting",
            "update_setting",
            "create_character",
            "update_character",
        ):
            self.assertIn(required, names)

    def test_execute_read_and_write_tools(self):
        project_id = self.create_project()
        with Session(engine) as session:
            raw = execute_tool(session, project_id, "get_project", {})
            data = json.loads(raw)
            self.assertTrue(data["ok"])
            self.assertEqual(data["result"]["title"], "工具测试项目")

            raw = execute_tool(
                session,
                project_id,
                "create_chapter",
                {"title": "第一章", "summary": "开端", "content": "正文A"},
            )
            chapter_id = json.loads(raw)["result"]["id"]

            raw = execute_tool(
                session,
                project_id,
                "update_chapter",
                {"chapter_id": chapter_id, "title": "第一章·改", "content": "正文B"},
            )
            self.assertIn("title", json.loads(raw)["result"]["updated_fields"])

            raw = execute_tool(
                session,
                project_id,
                "create_setting",
                {"title": "灵气", "content": "灵气复苏", "category_name": "世界观"},
            )
            setting_id = json.loads(raw)["result"]["id"]

            raw = execute_tool(session, project_id, "search_settings", {"query": "灵气"})
            self.assertGreaterEqual(json.loads(raw)["result"]["count"], 1)

            raw = execute_tool(
                session,
                project_id,
                "create_character",
                {"name": "林远", "summary": "主角", "data": {"role": "主角"}},
            )
            character_id = json.loads(raw)["result"]["id"]
            raw = execute_tool(
                session,
                project_id,
                "update_character",
                {"character_id": character_id, "summary": "隐忍主角"},
            )
            self.assertTrue(json.loads(raw)["ok"])

            raw = execute_tool(session, project_id, "update_project", {"theme": "都市异能"})
            self.assertTrue(json.loads(raw)["ok"])

        with Session(engine) as session:
            chapter = session.get(Chapter, chapter_id)
            self.assertEqual(chapter.title, "第一章·改")
            self.assertEqual(chapter.content, "正文B")
            setting = session.get(SettingEntry, setting_id)
            self.assertEqual(setting.title, "灵气")
            character = session.get(Character, character_id)
            self.assertEqual(character.summary, "隐忍主角")
            project = session.get(Project, project_id)
            self.assertEqual(project.theme, "都市异能")

    def test_tool_rejects_cross_project_ids(self):
        project_a = self.create_project("A")
        project_b = self.create_project("B")
        with Session(engine) as session:
            chapter = Chapter(project_id=project_a, sequence=1, title="仅A可见")
            session.add(chapter)
            session.commit()
            session.refresh(chapter)
            chapter_id = chapter.id

        with Session(engine) as session:
            with self.assertRaises(ToolError):
                execute_tool(
                    session,
                    project_b,
                    "update_chapter",
                    {"chapter_id": chapter_id, "title": "劫持"},
                )

    def test_runner_tool_calling_loop(self):
        project_id = self.create_project()

        def _noop_run(task_id, task_type, payload=None):
            return None

        with patch("app.routers.assistant.run_task", side_effect=_noop_run):
            response = self.client.post(
                f"/api/v1/projects/{project_id}/assistant/messages",
                json={"content": "请把项目主题改成赛博朋克，并新建角色「零号」"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]

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
                                "arguments": json.dumps({"theme": "赛博朋克"}, ensure_ascii=False),
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "create_character",
                                "arguments": json.dumps(
                                    {"name": "零号", "summary": "改造人"},
                                    ensure_ascii=False,
                                ),
                            },
                        },
                    ],
                }
            return {
                "role": "assistant",
                "content": "已将主题改为赛博朋克，并创建角色「零号」。",
                "tool_calls": None,
            }

        with patch("app.services.assistant_chat_runner.AIService.chat_completion", fake_chat):
            run_assistant_chat_task(task_id)

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "completed", task.message)
            self.assertEqual(len(task.result.get("tool_calls") or []), 2)
            project = session.get(Project, project_id)
            self.assertEqual(project.theme, "赛博朋克")
            characters = session.exec(
                select(Character).where(Character.project_id == project_id)
            ).all()
            self.assertTrue(any(c.name == "零号" for c in characters))


if __name__ == "__main__":
    unittest.main()
