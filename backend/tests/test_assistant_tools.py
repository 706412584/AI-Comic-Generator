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
from app.models.models import (
    Chapter,
    Character,
    CharacterRelationship,
    Project,
    SettingEntry,
    StoryboardItem,
    Task,
)
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
            "search_chapters",
            "get_setting",
            "get_character",
            "search_settings",
            "search_characters",
            "list_storyboard",
            "get_storyboard_item",
            "list_relationships",
            "update_project",
            "create_chapter",
            "update_chapter",
            "create_setting",
            "update_setting",
            "create_character",
            "update_character",
            "start_project_initialization",
            "start_generate_all_images",
            "start_generate_all_characters",
            "start_chapter_content",
            "start_chapter_storyboard",
            "start_source_analysis",
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

        with patch(
            "app.services.assistant_chat_runner.text_provider_supports_tools",
            return_value=(True, "openai_compatible"),
        ), patch("app.services.assistant_chat_runner.AIService.chat_completion", fake_chat):
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

    def test_start_project_initialization_dispatches(self):
        project_id = self.create_project("空项目初始化")
        enqueued = []

        with Session(engine) as session:
            with patch(
                "app.services.assistant_tools._enqueue_task",
                side_effect=lambda tid, ttype, payload: enqueued.append((tid, ttype, payload)),
            ):
                raw = execute_tool(
                    session,
                    project_id,
                    "start_project_initialization",
                    {"user_input": "赛博都市里的改造人少女"},
                )
            data = json.loads(raw)
            self.assertTrue(data["ok"])
            task_id = data["result"]["task_id"]
            self.assertEqual(data["result"]["task_type"], "project_initialization")

        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0][0], task_id)
        self.assertEqual(enqueued[0][1], "project_initialization")
        self.assertEqual(enqueued[0][2]["user_input"], "赛博都市里的改造人少女")

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertIsNotNone(task)
            self.assertEqual(task.type, "project_initialization")
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.input_payload["project_id"], project_id)
            project = session.get(Project, project_id)
            self.assertEqual(project.story_input, "赛博都市里的改造人少女")

    def test_start_project_initialization_rejects_non_empty(self):
        project_id = self.create_project("已有内容")
        with Session(engine) as session:
            session.add(Character(project_id=project_id, name="已有角色"))
            session.commit()

        with Session(engine) as session:
            with patch("app.services.assistant_tools._enqueue_task") as mock_enqueue:
                with self.assertRaises(ToolError) as ctx:
                    execute_tool(
                        session,
                        project_id,
                        "start_project_initialization",
                        {"user_input": "再初始化一次"},
                    )
                mock_enqueue.assert_not_called()
            self.assertIn("已有", str(ctx.exception))

    def test_start_generate_all_images_and_characters(self):
        project_id = self.create_project()
        enqueued = []

        with Session(engine) as session:
            with patch(
                "app.services.assistant_tools._enqueue_task",
                side_effect=lambda tid, ttype, payload: enqueued.append((tid, ttype, payload)),
            ):
                raw_img = execute_tool(session, project_id, "start_generate_all_images", {})
                raw_char = execute_tool(session, project_id, "start_generate_all_characters", {})

        img = json.loads(raw_img)
        char = json.loads(raw_char)
        self.assertTrue(img["ok"])
        self.assertTrue(char["ok"])
        self.assertEqual(img["result"]["task_type"], "image_generation")
        self.assertEqual(char["result"]["task_type"], "character_generation")
        types = {t for _, t, _ in enqueued}
        self.assertEqual(types, {"image_generation", "character_generation"})
        for _, t, p in enqueued:
            self.assertEqual(p.get("project_id"), project_id)

        # 运行中拒绝重复派发
        with Session(engine) as session:
            task = session.get(Task, img["result"]["task_id"])
            task.status = "processing"
            session.add(task)
            session.commit()

        with Session(engine) as session:
            with patch("app.services.assistant_tools._enqueue_task") as mock_enqueue:
                with self.assertRaises(ToolError) as ctx:
                    execute_tool(session, project_id, "start_generate_all_images", {})
                mock_enqueue.assert_not_called()
            self.assertIn("运行", str(ctx.exception))

    def test_start_chapter_content_and_storyboard(self):
        project_id = self.create_project()
        with Session(engine) as session:
            chapter = Chapter(project_id=project_id, sequence=1, title="第一章", content="草稿")
            session.add(chapter)
            session.commit()
            session.refresh(chapter)
            chapter_id = chapter.id

        enqueued = []
        with Session(engine) as session:
            with patch(
                "app.services.assistant_tools._enqueue_task",
                side_effect=lambda tid, ttype, payload: enqueued.append((tid, ttype, payload)),
            ):
                raw_c = execute_tool(
                    session,
                    project_id,
                    "start_chapter_content",
                    {"chapter_id": chapter_id, "user_input": "更紧张"},
                )
                raw_s = execute_tool(
                    session,
                    project_id,
                    "start_chapter_storyboard",
                    {"chapter_id": chapter_id},
                )

        content_data = json.loads(raw_c)
        storyboard_data = json.loads(raw_s)
        self.assertEqual(content_data["result"]["task_type"], "chapter_content_generation")
        self.assertEqual(storyboard_data["result"]["task_type"], "chapter_storyboard")
        self.assertEqual(content_data["result"]["chapter_id"], chapter_id)

        content_payload = next(p for _, t, p in enqueued if t == "chapter_content_generation")
        self.assertEqual(content_payload["chapter_id"], chapter_id)
        self.assertEqual(content_payload["user_input"], "更紧张")
        self.assertTrue(content_payload.get("save_version"))

        storyboard_payload = next(p for _, t, p in enqueued if t == "chapter_storyboard")
        self.assertEqual(storyboard_payload["chapter_id"], chapter_id)

        with Session(engine) as session:
            with self.assertRaises(ToolError):
                execute_tool(
                    session,
                    project_id,
                    "start_chapter_content",
                    {"chapter_id": 99999999},
                )

    def test_start_source_analysis_requires_import(self):
        project_id = self.create_project()
        with Session(engine) as session:
            with patch("app.services.assistant_tools._enqueue_task") as mock_enqueue:
                with self.assertRaises(ToolError) as ctx:
                    execute_tool(session, project_id, "start_source_analysis", {"mode": "continue"})
                mock_enqueue.assert_not_called()
            self.assertIn("导入", str(ctx.exception))

        from app.models.models import SourceImport

        with Session(engine) as session:
            session.add(
                SourceImport(
                    project_id=project_id,
                    file_name="novel.txt",
                    raw_text="第一章 开端\n正文",
                    text_length=20,
                )
            )
            session.commit()

        enqueued = []
        with Session(engine) as session:
            with patch(
                "app.services.assistant_tools._enqueue_task",
                side_effect=lambda tid, ttype, payload: enqueued.append((tid, ttype, payload)),
            ):
                raw = execute_tool(
                    session,
                    project_id,
                    "start_source_analysis",
                    {"mode": "all"},
                )
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["task_type"], "source_analysis")
        self.assertEqual(enqueued[0][1], "source_analysis")
        self.assertEqual(enqueued[0][2]["mode"], "all")
        self.assertIsNone(enqueued[0][2]["max_chapters"])

    def test_storyboard_and_relationship_tools(self):
        project_id = self.create_project()
        with Session(engine) as session:
            chapter = Chapter(project_id=project_id, sequence=1, title="第一章", content="正文")
            session.add(chapter)
            session.flush()
            c1 = Character(project_id=project_id, name="甲")
            c2 = Character(project_id=project_id, name="乙")
            session.add(c1)
            session.add(c2)
            session.flush()
            item = StoryboardItem(
                project_id=project_id,
                chapter_id=chapter.id,
                sequence=1,
                data={"description": "雨夜对峙", "characters": ["甲", "乙"], "prompt": "cinematic"},
            )
            session.add(item)
            rel = CharacterRelationship(
                project_id=project_id,
                source_character_id=c1.id,
                target_character_id=c2.id,
                relationship_type="宿敌",
                description="互相制衡",
            )
            session.add(rel)
            session.commit()
            chapter_id = chapter.id
            item_id = item.id
            c1_id = c1.id
            setting = SettingEntry(project_id=project_id, title="灵根", content="双灵根稀有")
            session.add(setting)
            session.commit()
            setting_id = setting.id

        with Session(engine) as session:
            raw = execute_tool(session, project_id, "list_storyboard", {"chapter_id": chapter_id})
            data = json.loads(raw)
            self.assertTrue(data["ok"])
            self.assertGreaterEqual(data["result"]["total"], 1)
            self.assertEqual(data["result"]["items"][0]["id"], item_id)

            raw = execute_tool(session, project_id, "get_storyboard_item", {"item_id": item_id})
            detail = json.loads(raw)["result"]
            self.assertEqual(detail["id"], item_id)
            self.assertIn("雨夜", detail["data"].get("description", ""))

            raw = execute_tool(session, project_id, "list_relationships", {"character_id": c1_id})
            rels = json.loads(raw)["result"]
            self.assertGreaterEqual(rels["count"], 1)
            self.assertEqual(rels["items"][0]["relationship_type"], "宿敌")

            raw = execute_tool(session, project_id, "get_character", {"character_id": c1_id})
            self.assertEqual(json.loads(raw)["result"]["name"], "甲")

            raw = execute_tool(session, project_id, "get_setting", {"setting_id": setting_id})
            self.assertEqual(json.loads(raw)["result"]["title"], "灵根")

    def test_search_chapters_and_get_chapter_modes(self):
        project_id = self.create_project()
        with Session(engine) as session:
            chapter = Chapter(
                project_id=project_id,
                sequence=1,
                title="雨夜对峙",
                summary="主角与宿敌在桥上对峙",
                content="开场：" + ("甲" * 100) + "关键冲突爆发" + ("乙" * 100) + "收束。",
            )
            session.add(chapter)
            session.commit()
            session.refresh(chapter)
            chapter_id = chapter.id

        with Session(engine) as session:
            raw = execute_tool(session, project_id, "search_chapters", {"query": "关键冲突"})
            data = json.loads(raw)
            self.assertTrue(data["ok"])
            self.assertGreaterEqual(data["result"]["count"], 1)
            self.assertEqual(data["result"]["items"][0]["id"], chapter_id)
            self.assertEqual(data["result"]["items"][0]["hit_field"], "content")
            self.assertIn("关键冲突", data["result"]["items"][0]["snippet"])

            summary = json.loads(
                execute_tool(
                    session,
                    project_id,
                    "get_chapter",
                    {"chapter_id": chapter_id, "mode": "summary"},
                )
            )["result"]
            self.assertEqual(summary["mode"], "summary")
            self.assertNotIn("content", summary)
            self.assertIn("preview", summary)

            segment = json.loads(
                execute_tool(
                    session,
                    project_id,
                    "get_chapter",
                    {"chapter_id": chapter_id, "mode": "segment", "offset": 0, "limit": 40},
                )
            )["result"]
            self.assertEqual(segment["mode"], "segment")
            self.assertEqual(segment["offset"], 0)
            self.assertLessEqual(len(segment["segment"]), 40)
            self.assertTrue(segment["has_more"])

            full = json.loads(
                execute_tool(
                    session,
                    project_id,
                    "get_chapter",
                    {"chapter_id": chapter_id, "include_content": True},
                )
            )["result"]
            self.assertEqual(full["mode"], "full")
            self.assertIn("content", full)


if __name__ == "__main__":
    unittest.main()
