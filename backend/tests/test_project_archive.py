import io
import json
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.database import engine, init_db
from app.core.paths import static_dir
from app.main import app
from app.models.models import (
    AgentConversation,
    AgentMessage,
    Chapter,
    Character,
    CharacterOutfit,
    CharacterRelationship,
    Project,
    SettingCategory,
    SettingEntry,
    StoryboardItem,
)


class ProjectArchiveTest(unittest.TestCase):
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
        for project_id in self.project_ids:
            shutil.rmtree(static_dir() / project_id, ignore_errors=True)

    def create_archive_fixture(self):
        project = Project(title="ZIP 往返项目", description="导入导出测试", current_chapter_id=None)
        with Session(engine) as session:
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project_ids.append(project.id)

            category = SettingCategory(project_id=project.id, name="世界观", description="测试分类")
            session.add(category)
            session.flush()
            session.add(SettingEntry(project_id=project.id, category_id=category.id, title="灵气", content="灵气复苏"))

            chapter = Chapter(project_id=project.id, sequence=1, title="第一章", summary="开始")
            session.add(chapter)
            session.flush()

            character_a = Character(project_id=project.id, name="主角", data={"role": "主角"})
            character_b = Character(project_id=project.id, name="对手", data={"role": "反派"})
            session.add(character_a)
            session.add(character_b)
            session.flush()
            outfit = CharacterOutfit(
                project_id=project.id,
                character_id=character_a.id,
                name="默认服饰",
                description="黑色长袍",
                is_default=True,
            )
            session.add(outfit)
            session.flush()
            character_a.default_outfit_id = outfit.id
            character_a.image_url = f"/static/{project.id}/characters/hero.png"
            session.add(character_a)

            session.add(CharacterRelationship(
                project_id=project.id,
                source_character_id=character_a.id,
                target_character_id=character_b.id,
                chapter_id=chapter.id,
                relationship_type="宿敌",
            ))
            session.add(StoryboardItem(
                project_id=project.id,
                chapter_id=chapter.id,
                sequence=1,
                data={"scene": "相遇"},
                image_url=f"/static/{project.id}/panels/panel.png",
            ))
            project.current_chapter_id = chapter.id
            session.add(project)
            session.commit()
            project_id = project.id

        character_dir = static_dir() / project_id / "characters"
        panel_dir = static_dir() / project_id / "panels"
        character_dir.mkdir(parents=True, exist_ok=True)
        panel_dir.mkdir(parents=True, exist_ok=True)
        (character_dir / "hero.png").write_bytes(b"hero image")
        (panel_dir / "panel.png").write_bytes(b"panel image")
        temp_dir = static_dir() / project_id / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "ai_output_secret.txt").write_text("do not export", encoding="utf-8")
        return project_id

    def test_project_zip_export_and_import_round_trip(self):
        source_id = self.create_archive_fixture()
        export_response = self.client.get(f"/api/v1/projects/{source_id}/archive")
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.headers["content-type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(export_response.content)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("media/characters/hero.png", archive.namelist())
            self.assertIn("media/panels/panel.png", archive.namelist())
            self.assertNotIn("media/temp/ai_output_secret.txt", archive.namelist())

        import_response = self.client.post(
            "/api/v1/projects/import",
            content=export_response.content,
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(import_response.status_code, 200, import_response.text)
        imported_id = import_response.json()["id"]
        self.project_ids.append(imported_id)
        self.assertNotEqual(imported_id, source_id)

        with Session(engine) as session:
            imported = session.get(Project, imported_id)
            self.assertEqual(imported.title, "ZIP 往返项目")
            self.assertIsNotNone(imported.current_chapter_id)

            chapters = session.exec(select(Chapter).where(Chapter.project_id == imported_id)).all()
            characters = session.exec(select(Character).where(Character.project_id == imported_id)).all()
            relationships = session.exec(select(CharacterRelationship).where(CharacterRelationship.project_id == imported_id)).all()
            storyboards = session.exec(select(StoryboardItem).where(StoryboardItem.project_id == imported_id)).all()
            settings = session.exec(select(SettingEntry).where(SettingEntry.project_id == imported_id)).all()

            self.assertEqual(len(chapters), 1)
            self.assertEqual(len(characters), 2)
            self.assertEqual(len(relationships), 1)
            self.assertEqual(len(storyboards), 1)
            self.assertEqual(len(settings), 1)
            self.assertEqual(relationships[0].chapter_id, chapters[0].id)
            self.assertIn(relationships[0].source_character_id, {character.id for character in characters})
            self.assertEqual(storyboards[0].chapter_id, chapters[0].id)
            self.assertTrue(storyboards[0].image_url.startswith(f"/static/{imported_id}/"))
            hero = next(character for character in characters if character.name == "主角")
            self.assertIsNotNone(hero.default_outfit_id)
            self.assertTrue(hero.image_url.startswith(f"/static/{imported_id}/"))

        self.assertEqual((static_dir() / imported_id / "characters" / "hero.png").read_bytes(), b"hero image")
        self.assertEqual((static_dir() / imported_id / "panels" / "panel.png").read_bytes(), b"panel image")

    def test_project_import_rejects_windows_device_path(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("media/characters/CON.png", "unsafe")
            archive.writestr("manifest.json", '{"format":"ai-comic-project","version":1,"data":{"project":{"title":"x"}}}')
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("reserved Windows path", response.json()["detail"])

    def test_project_import_rejects_backslash_path(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("media/characters\\..\\outside.txt", "unsafe")
            archive.writestr("manifest.json", '{"format":"ai-comic-project","version":1,"data":{"project":{"title":"x"}}}')
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsafe path", response.json()["detail"])

    def test_project_import_rejects_unsafe_zip_path(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../outside.txt", "unsafe")
            archive.writestr("manifest.json", '{"format":"ai-comic-project","version":1,"data":{"project":{}}}')
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsafe path", response.json()["detail"])

    def test_project_import_rejects_invalid_zip(self):
        response = self.client.post(
            "/api/v1/projects/import",
            content=b"not a zip",
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("有效的 ZIP", response.json()["detail"])

    def test_project_import_rejects_non_project_zip(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("readme.txt", "not a project")
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("manifest.json", response.json()["detail"])

    def test_project_import_strips_external_media_urls(self):
        """External or out-of-whitelist image URLs must not be kept after import."""
        source_id = "src-project-id"
        manifest = {
            "format": "ai-comic-project",
            "version": 1,
            "source_project_id": source_id,
            "data": {
                "project": {"title": "外部 URL", "description": "", "current_chapter_id": None},
                "characters": [
                    {
                        "id": 1,
                        "name": "角色",
                        "data": {},
                        "image_url": "https://evil.example/steal.png",
                        "default_outfit_id": None,
                    }
                ],
                "storyboard_items": [
                    {
                        "id": 1,
                        "chapter_id": None,
                        "sequence": 1,
                        "data": {},
                        "image_url": f"/static/{source_id}/temp/escape.png",
                    }
                ],
            },
        }
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        imported_id = response.json()["id"]
        self.project_ids.append(imported_id)
        with Session(engine) as session:
            characters = session.exec(select(Character).where(Character.project_id == imported_id)).all()
            storyboards = session.exec(select(StoryboardItem).where(StoryboardItem.project_id == imported_id)).all()
            self.assertEqual(len(characters), 1)
            self.assertIsNone(characters[0].image_url)
            self.assertEqual(len(storyboards), 1)
            self.assertIsNone(storyboards[0].image_url)

    def test_project_zip_preserves_assistant_messages(self):
        source_id = self.create_archive_fixture()
        with Session(engine) as session:
            conversation = AgentConversation(project_id=source_id, title="创作助手", status="active")
            session.add(conversation)
            session.flush()
            session.add(AgentMessage(
                conversation_id=conversation.id,
                project_id=source_id,
                role="user",
                content="帮我总结主角弧线",
                task_id="task-should-drop",
            ))
            session.add(AgentMessage(
                conversation_id=conversation.id,
                project_id=source_id,
                role="assistant",
                content="主角从隐忍走向反抗。",
            ))
            session.commit()

        export_response = self.client.get(f"/api/v1/projects/{source_id}/archive")
        self.assertEqual(export_response.status_code, 200)
        import_response = self.client.post(
            "/api/v1/projects/import",
            content=export_response.content,
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(import_response.status_code, 200, import_response.text)
        imported_id = import_response.json()["id"]
        self.project_ids.append(imported_id)

        with Session(engine) as session:
            conversations = session.exec(
                select(AgentConversation).where(AgentConversation.project_id == imported_id)
            ).all()
            messages = session.exec(
                select(AgentMessage).where(AgentMessage.project_id == imported_id).order_by(AgentMessage.id)
            ).all()
            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].title, "创作助手")
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0].content, "帮我总结主角弧线")
            self.assertIsNone(messages[0].task_id)
            self.assertEqual(messages[1].role, "assistant")
            self.assertEqual(messages[1].content, "主角从隐忍走向反抗。")
            self.assertEqual(messages[0].conversation_id, conversations[0].id)

    def test_project_import_requires_media_member_for_url(self):
        """Declared media URL without matching ZIP member is dropped."""
        source_id = "src-project-id"
        manifest = {
            "format": "ai-comic-project",
            "version": 1,
            "source_project_id": source_id,
            "data": {
                "project": {"title": "缺媒体", "description": "", "current_chapter_id": None},
                "characters": [
                    {
                        "id": 1,
                        "name": "角色",
                        "data": {},
                        "image_url": f"/static/{source_id}/characters/missing.png",
                        "default_outfit_id": None,
                    }
                ],
            },
        }
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
        response = self.client.post(
            "/api/v1/projects/import",
            content=archive_bytes.getvalue(),
            headers={"content-type": "application/zip"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        imported_id = response.json()["id"]
        self.project_ids.append(imported_id)
        with Session(engine) as session:
            characters = session.exec(select(Character).where(Character.project_id == imported_id)).all()
            self.assertEqual(len(characters), 1)
            self.assertIsNone(characters[0].image_url)


if __name__ == "__main__":
    unittest.main()
