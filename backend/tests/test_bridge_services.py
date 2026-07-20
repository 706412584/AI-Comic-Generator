import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.bridge.ai_bridge import app as ai_bridge_app
from app.bridge.mcp_http_server import app as mcp_http_app
from app.core.database import engine, init_db
from app.models.models import Character, CharacterState, Chapter, ChapterVersion, MemoryEntry, Project, ProjectProgress, SettingEntry


class BridgeServicesTest(unittest.TestCase):
    def setUp(self):
        init_db()
        with Session(engine) as session:
            project = Project(title="Bridge Test Project", description="bridge test")
            session.add(project)
            session.commit()
            session.refresh(project)
            chapter = Chapter(project_id=project.id, sequence=1, title="第一章", summary="开场", content="主角进入青石镇。", preview_text="主角进入青石镇。", word_count=1)
            character = Character(project_id=project.id, name="主角", data={"name": "主角"})
            setting = SettingEntry(project_id=project.id, title="世界规则", content="灵气复苏", importance=5)
            session.add(chapter)
            session.add(character)
            session.add(setting)
            session.commit()
            session.refresh(chapter)
            session.refresh(character)
            memory = MemoryEntry(project_id=project.id, chapter_id=chapter.id, character_id=character.id, content="主角怕水", memory_type="trait", importance=4)
            state = CharacterState(project_id=project.id, chapter_id=chapter.id, character_id=character.id, physical_state="健康", emotional_state="警惕")
            progress = ProjectProgress(project_id=project.id, current_chapter_id=chapter.id, current_location="青石镇", active_threads=["寻找线索"])
            session.add(memory)
            session.add(state)
            session.add(progress)
            session.commit()
            self.project_id = project.id
            self.chapter_id = chapter.id
            self.character_id = character.id

    def test_ai_bridge_health_and_context(self):
        client = TestClient(ai_bridge_app)
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["name"], "ai-comic-ai-bridge")
        self.assertEqual(health.json()["port"], 48721)

        context = client.post("/chapter/context", json={"project_id": self.project_id, "chapter_id": self.chapter_id})
        self.assertEqual(context.status_code, 200)
        self.assertIn("Bridge Test Project", context.json()["prompt"])
        self.assertIn("世界规则", context.json()["prompt"])

    def test_ai_bridge_chapter_generate_saves_content(self):
        client = TestClient(ai_bridge_app)
        with patch("app.bridge.ai_bridge.AIService.generate_chapter_content", return_value="AI Bridge 生成正文 三段"), \
             patch("app.services.chapter_state_extraction_service.AIService.generate_text", return_value='```json\n{"memories":[],"character_states":[],"progress":{}}\n```'):
            response = client.post("/chapter/generate", json={"chapter_id": self.chapter_id, "user_input": "写紧凑一点"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "AI Bridge 生成正文 三段")
        self.assertIsNotNone(response.json()["version_id"])

        with Session(engine) as session:
            chapter = session.get(Chapter, self.chapter_id)
            self.assertEqual(chapter.content, "AI Bridge 生成正文 三段")
            self.assertEqual(chapter.word_count, 4)
            version = session.exec(select(ChapterVersion).where(ChapterVersion.id == response.json()["version_id"])).one()
            self.assertEqual(version.word_count, 4)
            self.assertEqual(version.preview_text, "AI Bridge 生成正文 三段")

    def test_mcp_http_manifest_and_tool_calls(self):
        client = TestClient(mcp_http_app)
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["name"], "ai-comic-mcp-http-server")
        self.assertEqual(health.json()["port"], 48722)

        manifest = client.get("/mcp/manifest")
        self.assertEqual(manifest.status_code, 200)
        tool_names = [tool["name"] for tool in manifest.json()["tools"]]
        self.assertIn("list_projects", tool_names)
        self.assertIn("get_chapter_context", tool_names)
        self.assertIn("get_project_summary", tool_names)
        self.assertIn("get_chapter_detail", tool_names)
        self.assertIn("list_memories", tool_names)
        self.assertIn("list_character_states", tool_names)
        self.assertIn("review_chapter_continuity", tool_names)

        projects = client.post("/mcp/call", json={"name": "list_projects", "arguments": {}})
        self.assertEqual(projects.status_code, 200)
        self.assertTrue(any(item["id"] == self.project_id for item in projects.json()["content"]))

        chapters = client.post("/mcp/call", json={"name": "list_chapters", "arguments": {"project_id": self.project_id}})
        self.assertEqual(chapters.status_code, 200)
        self.assertTrue(any(item["id"] == self.chapter_id for item in chapters.json()["content"]))

        context = client.post(
            "/mcp/call",
            json={"name": "get_chapter_context", "arguments": {"project_id": self.project_id, "chapter_id": self.chapter_id}},
        )
        self.assertEqual(context.status_code, 200)
        self.assertIn("Bridge Test Project", context.json()["content"][0]["text"])

    def test_mcp_http_extended_read_tools(self):
        client = TestClient(mcp_http_app)

        summary = client.post("/mcp/call", json={"name": "get_project_summary", "arguments": {"project_id": self.project_id}})
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["content"]["project"]["id"], self.project_id)
        self.assertEqual(summary.json()["content"]["counts"]["chapters"], 1)
        self.assertEqual(summary.json()["content"]["progress"]["current_location"], "青石镇")

        detail = client.post("/mcp/call", json={"name": "get_chapter_detail", "arguments": {"project_id": self.project_id, "chapter_id": self.chapter_id}})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["content"]["chapter"]["content"], "主角进入青石镇。")

        memories = client.post(
            "/mcp/call",
            json={"name": "list_memories", "arguments": {"project_id": self.project_id, "memory_type": "trait", "chapter_id": self.chapter_id}},
        )
        self.assertEqual(memories.status_code, 200)
        self.assertEqual(len(memories.json()["content"]), 1)
        self.assertEqual(memories.json()["content"][0]["content"], "主角怕水")

        states = client.post(
            "/mcp/call",
            json={"name": "list_character_states", "arguments": {"project_id": self.project_id, "character_id": self.character_id}},
        )
        self.assertEqual(states.status_code, 200)
        self.assertEqual(states.json()["content"][0]["character_name"], "主角")
        self.assertEqual(states.json()["content"][0]["physical_state"], "健康")

    def test_mcp_http_review_chapter_continuity_tool(self):
        client = TestClient(mcp_http_app)
        review_json = '```json\n{"summary":"审查完成","issues":[{"severity":"low","category":"plot","message":"无明显问题"}]}\n```'
        with patch("app.services.chapter_continuity_review_service.AIService.generate_text", return_value=review_json):
            response = client.post(
                "/mcp/call",
                json={"name": "review_chapter_continuity", "arguments": {"project_id": self.project_id, "chapter_id": self.chapter_id}},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"]["summary"], "审查完成")
        self.assertEqual(response.json()["content"]["issues"][0]["severity"], "low")

    def test_mcp_http_rejects_malformed_numeric_arguments(self):
        client = TestClient(mcp_http_app)
        cases = [
            ("get_chapter_detail", {"project_id": self.project_id, "chapter_id": "abc"}, "chapter_id"),
            ("review_chapter_continuity", {"project_id": self.project_id, "chapter_id": "abc"}, "chapter_id"),
            ("list_memories", {"project_id": self.project_id, "chapter_id": "abc"}, "chapter_id"),
            ("list_character_states", {"project_id": self.project_id, "character_id": "abc"}, "character_id"),
        ]
        for name, arguments, field in cases:
            response = client.post("/mcp/call", json={"name": name, "arguments": arguments})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], f"Invalid argument: {field}")

    def test_mcp_http_rejects_unknown_tool(self):
        client = TestClient(mcp_http_app)
        response = client.post("/mcp/call", json={"name": "unknown", "arguments": {}})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
