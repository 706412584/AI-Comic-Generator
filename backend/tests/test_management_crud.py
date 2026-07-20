import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from unittest.mock import patch

from app.core.database import engine, init_db
from app.main import app
from app.models.models import Character, CharacterOutfit, CharacterRelationship, CharacterState, Chapter, ChapterTask, ChapterVersion, MemoryEntry, Outline, Project, ProjectProgress, SettingEntry, StoryboardItem, Task
from app.routers.generation import build_panel_outfit_prompt


class ManagementCrudTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        project = self.client.post('/api/v1/projects/', json={'title': 'management test'}).json()
        self.project_id = project['id']

    def create_character(self, name='角色'):
        with Session(engine) as session:
            character = Character(project_id=self.project_id, name=name, data={'name': name})
            session.add(character)
            session.commit()
            session.refresh(character)
            return character.id

    def create_outfit(self, character_id: int, name='服饰'):
        with Session(engine) as session:
            outfit = CharacterOutfit(project_id=self.project_id, character_id=character_id, name=name, description='描述')
            session.add(outfit)
            session.commit()
            session.refresh(outfit)
            return outfit.id

    def test_project_initialization_generates_project_skeleton_and_progress(self):
        ai_payload = '''
        {
          "project": {"title": "机械狐仙", "description": "少年与机械狐妖寻找天庭遗迹", "theme": "赛博修仙", "language": "zh-CN"},
          "settings": [{"category": "世界观", "title": "天庭遗迹", "content": "旧天庭坠入数据云海", "tags": ["世界观"], "importance": 5}],
          "characters": [{"name": "林烬", "summary": "失忆少年", "status": "active", "aliases": ["小烬"], "data": {"role": "主角"}, "outfits": [{"name": "破损校服", "description": "带有发光符纹的旧校服", "colors": "黑蓝", "is_default": true}]}, {"name": "阿狐", "summary": "机械狐妖", "data": {"role": "伙伴"}, "outfits": [{"name": "狐影斗篷", "description": "银白机械斗篷", "is_default": true}]}],
          "relationships": [{"source": "林烬", "target": "阿狐", "relationship_type": "同伴", "description": "共同寻找遗迹", "intensity": 4, "tags": ["主线"]}],
          "outlines": [{"scope": "project", "title": "全书大纲", "content": "寻找天庭遗迹并揭开失忆真相", "sort_order": 0}],
          "chapters": [{"sequence": 1, "title": "云海醒来", "summary": "林烬遇到阿狐", "goal": "建立主线", "conflict": "追兵出现", "current_location": "云海废墟", "current_time": "黄昏", "pov_character": "林烬", "tasks": [{"title": "写开场", "description": "完成第一章开场", "type": "writing", "sort_order": 0}]}],
          "memories": [{"scope": "project", "content": "林烬不知道自己来自天庭", "memory_type": "character", "tags": ["秘密"], "importance": 4}],
          "progress": {"current_arc": "遗迹篇", "current_location": "云海废墟", "current_time": "黄昏", "main_conflict": "寻找天庭遗迹", "active_threads": ["失忆真相"], "pending_hooks": ["阿狐身份"], "notes": "项目初始化"}
        }
        '''

        with patch('app.routers.generation.AIService.generate_text', return_value=ai_payload):
            response = self.client.post(
                f'/api/v1/generate/project-initialize/{self.project_id}',
                json={'user_input': '赛博修仙世界，一个失忆少年和机械狐妖寻找天庭遗迹'},
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, 'completed')
            self.assertEqual(task.progress, 100)
            self.assertIn('项目初始化完成', task.message)
            self.assertTrue(any('AI 正在理解一句话创意' in log for log in task.logs))

            project = session.get(Project, self.project_id)
            self.assertEqual(project.title, '机械狐仙')
            self.assertEqual(project.workflow_mode, 'novel_comic')
            self.assertEqual(project.setting_mode, 'advanced')

            settings = session.exec(select(SettingEntry).where(SettingEntry.project_id == self.project_id)).all()
            characters = session.exec(select(Character).where(Character.project_id == self.project_id)).all()
            relationships = session.exec(select(CharacterRelationship).where(CharacterRelationship.project_id == self.project_id)).all()
            outlines = session.exec(select(Outline).where(Outline.project_id == self.project_id)).all()
            chapters = session.exec(select(Chapter).where(Chapter.project_id == self.project_id)).all()
            chapter_tasks = session.exec(select(ChapterTask).where(ChapterTask.project_id == self.project_id)).all()
            memories = session.exec(select(MemoryEntry).where(MemoryEntry.project_id == self.project_id)).all()
            progress = session.exec(select(ProjectProgress).where(ProjectProgress.project_id == self.project_id)).first()

            self.assertEqual(len(settings), 1)
            self.assertEqual(len(characters), 2)
            self.assertEqual(len(relationships), 1)
            self.assertEqual(len(outlines), 1)
            self.assertEqual(len(chapters), 1)
            self.assertEqual(len(chapter_tasks), 1)
            self.assertEqual(len(memories), 1)
            self.assertEqual(progress.current_arc, '遗迹篇')
            self.assertEqual(progress.current_chapter_id, chapters[0].id)
            self.assertEqual(project.current_chapter_id, chapters[0].id)
            self.assertTrue(any(character.default_outfit_id for character in characters))

    def test_project_initialization_dedupes_settings_and_characters(self):
        ai_payload = '''
        {
          "project": {"title": "剑影孤城", "description": "少年剑客的复兴之路", "theme": "东方玄幻", "language": "zh-CN"},
          "settings": [
            {"category": "世界观", "title": "九州灵脉", "content": "灵气由祖脉滋养", "tags": ["世界观"], "importance": 5},
            {"category": "世界观", "title": "九州灵脉", "content": "重复的设定，应被去重", "tags": ["世界观"], "importance": 4},
            {"category": "力量体系", "title": "剑道境界", "content": "剑意剑骨剑心", "tags": ["体系"], "importance": 5}
          ],
          "characters": [
            {"name": "沈砚", "summary": "失灵根少年", "data": {"role": "主角"}, "outfits": [{"name": "青衫", "description": "旧青衫", "is_default": true}]},
            {"name": "沈砚", "summary": "重复的同名角色，应被去重", "data": {"role": "主角"}, "outfits": [{"name": "重复", "description": "重复", "is_default": true}]},
            {"name": "玄微真人", "summary": "宗门长老", "data": {"role": "反派"}, "outfits": [{"name": "道袍", "description": "玄色道袍", "is_default": true}]}
          ],
          "relationships": [{"source": "沈砚", "target": "玄微真人", "relationship_type": "宿敌", "description": "阴谋对立", "intensity": 5, "tags": ["主线"]}],
          "outlines": [{"scope": "project", "title": "全书大纲", "content": "复兴剑道", "sort_order": 0}],
          "chapters": [{"sequence": 1, "title": "废灵根", "summary": "开场", "tasks": []}],
          "memories": [{"scope": "project", "content": "沈砚灵根被废", "memory_type": "event", "tags": ["开端"], "importance": 4}],
          "progress": {"current_arc": "开篇", "notes": "初始化"}
        }
        '''

        with patch('app.routers.generation.AIService.generate_text', return_value=ai_payload):
            response = self.client.post(
                f'/api/v1/generate/project-initialize/{self.project_id}',
                json={'user_input': '东方玄幻世界，一个失灵根少年重建剑道'},
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']

        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, 'completed')

            settings = session.exec(select(SettingEntry).where(SettingEntry.project_id == self.project_id)).all()
            characters = session.exec(select(Character).where(Character.project_id == self.project_id)).all()

            setting_titles = [s.title for s in settings]
            self.assertEqual(len(setting_titles), 2)
            self.assertEqual(sorted(setting_titles), ['九州灵脉', '剑道境界'])

            character_names = [c.name for c in characters]
            self.assertEqual(len(character_names), 2)
            self.assertEqual(sorted(character_names), ['沈砚', '玄微真人'])

    def test_project_initialization_rejects_existing_content(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '已有章节'},
        )

        response = self.client.post(
            f'/api/v1/generate/project-initialize/{self.project_id}',
            json={'user_input': '赛博修仙'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('空项目', response.json()['detail'])

    def test_project_initialization_non_json_failure_writes_no_generated_content(self):
        with patch('app.routers.generation.AIService.generate_text', return_value='not json at all'):
            response = self.client.post(
                f'/api/v1/generate/project-initialize/{self.project_id}',
                json={'user_input': '测试失败'},
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']

        with Session(engine) as session:
            task = session.get(Task, task_id)
            project = session.get(Project, self.project_id)
            self.assertEqual(task.status, 'failed')
            self.assertIn('AI 未返回可解析', task.message)
            self.assertEqual(project.title, 'management test')
            self.assertEqual(len(session.exec(select(SettingEntry).where(SettingEntry.project_id == self.project_id)).all()), 0)
            self.assertEqual(len(session.exec(select(Character).where(Character.project_id == self.project_id)).all()), 0)
            self.assertEqual(len(session.exec(select(Chapter).where(Chapter.project_id == self.project_id)).all()), 0)
            self.assertEqual(len(session.exec(select(MemoryEntry).where(MemoryEntry.project_id == self.project_id)).all()), 0)

    def test_setting_chapter_outline_memory_and_task_crud(self):
        category = self.client.post(
            f'/api/v1/projects/{self.project_id}/setting-categories',
            json={'name': '世界观', 'description': '基础世界规则'},
        )
        self.assertEqual(category.status_code, 200)
        category_id = category.json()['id']

        setting = self.client.post(
            f'/api/v1/projects/{self.project_id}/settings',
            json={'category_id': category_id, 'title': '境界', 'content': '炼气到筑基', 'tags': ['境界']},
        )
        self.assertEqual(setting.status_code, 200)
        self.assertEqual(setting.json()['title'], '境界')

        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={
                'sequence': 1,
                'title': '第一章',
                'current_location': '青石镇',
                'current_time': '清晨',
                'pov_character': '主角',
                'chapter_metadata': {'mood': 'tense'},
            },
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']
        self.assertEqual(chapter.json()['chapter_metadata']['mood'], 'tense')

        outline = self.client.post(
            f'/api/v1/projects/{self.project_id}/outlines',
            json={'scope': 'chapter', 'title': '小纲', 'content': '开场冲突', 'chapter_id': chapter_id},
        )
        self.assertEqual(outline.status_code, 200)
        self.assertEqual(outline.json()['chapter_id'], chapter_id)

        memory = self.client.post(
            f'/api/v1/projects/{self.project_id}/memories',
            json={'content': '主角怕水', 'importance': 5, 'memory_type': 'trait', 'chapter_id': chapter_id},
        )
        self.assertEqual(memory.status_code, 200)
        self.assertEqual(memory.json()['importance'], 5)
        self.assertEqual(memory.json()['memory_type'], 'trait')

        task = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapter-tasks',
            json={'chapter_id': chapter_id, 'title': '生成分镜', 'status': 'todo'},
        )
        self.assertEqual(task.status_code, 200)
        self.assertEqual(task.json()['status'], 'todo')

    def test_rejects_invalid_chapter_and_task_inputs(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '第一章'},
        )
        self.assertEqual(chapter.status_code, 200)

        duplicate = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '重复章节'},
        )
        self.assertEqual(duplicate.status_code, 400)

        negative = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': -1, 'title': '负数章节'},
        )
        self.assertEqual(negative.status_code, 400)

        invalid_task = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapter-tasks',
            json={'chapter_id': chapter.json()['id'], 'title': '异常状态', 'status': 'nonsense'},
        )
        self.assertEqual(invalid_task.status_code, 400)

    def test_character_outfit_crud(self):
        character_id = self.create_character(name='主角')

        outfit = self.client.post(
            f'/api/v1/projects/{self.project_id}/characters/{character_id}/outfits',
            json={'name': '默认服饰', 'description': '蓝色长袍', 'is_default': True},
        )
        self.assertEqual(outfit.status_code, 200)
        outfit_data = outfit.json()
        self.assertTrue(outfit_data['is_default'])

        updated = self.client.put(
            f'/api/v1/projects/{self.project_id}/characters/{character_id}/outfits/{outfit_data["id"]}',
            json={'state': '战斗破损'},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['state'], '战斗破损')

        listed = self.client.get(f'/api/v1/projects/{self.project_id}/characters/{character_id}/outfits')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

    def test_chapter_content_preview_and_versions(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 2, 'title': '第二章'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        updated = self.client.put(
            f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/content',
            json={'content': '第一段\n第二段', 'preview_text': '第一段', 'change_note': '初稿'},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['preview_text'], '第一段')

        fetched = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}')
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()['content'], '第一段\n第二段')

        preview = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/preview')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()['preview_text'], '第一段')

        versions = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/versions')
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(len(versions.json()), 1)
        self.assertEqual(versions.json()[0]['version_no'], 1)
        self.assertEqual(versions.json()[0]['content'], '第一段\n第二段')

        version = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/versions',
            json={'change_note': '保存版本'},
        )
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()['version_no'], 2)

    def test_chapter_version_rollback_restores_content_and_creates_snapshot(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 9, 'title': '第九章'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        first = self.client.put(
            f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/content',
            json={'content': '旧正文 第一段', 'preview_text': '旧预览', 'change_note': '旧版'},
        )
        self.assertEqual(first.status_code, 200)
        second = self.client.put(
            f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/content',
            json={'content': '新正文内容', 'preview_text': '新正文', 'change_note': '新版'},
        )
        self.assertEqual(second.status_code, 200)

        versions = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/versions').json()
        old_version = next(item for item in versions if item['content'] == '旧正文 第一段')
        self.assertEqual(old_version['preview_text'], '旧预览')
        self.assertEqual(old_version['word_count'], 2)

        rollback = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/versions/{old_version["id"]}/rollback'
        )
        self.assertEqual(rollback.status_code, 200)
        self.assertEqual(rollback.json()['content'], '旧正文 第一段')
        self.assertEqual(rollback.json()['preview_text'], '旧预览')
        self.assertEqual(rollback.json()['word_count'], 2)

        versions_after = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{chapter_id}/versions').json()
        self.assertEqual(len(versions_after), 3)
        self.assertTrue(any(item['content'] == '新正文内容' and '回滚到版本' in item['change_note'] for item in versions_after))

    def test_chapter_version_rollback_rejects_cross_chapter_version(self):
        first_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 10, 'title': '第十章', 'content': '第一章正文'},
        ).json()
        second_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 11, 'title': '第十一章', 'content': '第二章正文'},
        ).json()
        version = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters/{first_chapter["id"]}/versions',
            json={'change_note': '第一章版本'},
        ).json()

        response = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters/{second_chapter["id"]}/versions/{version["id"]}/rollback'
        )
        self.assertEqual(response.status_code, 404)

    def test_chapter_storyboard_generation_replaces_only_current_chapter_items(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 7, 'title': '第七章', 'content': '主角进入遗迹。'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        other_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 8, 'title': '第八章'},
        )
        other_chapter_id = other_chapter.json()['id']

        with Session(engine) as session:
            old_current = StoryboardItem(project_id=self.project_id, chapter_id=chapter_id, sequence=1, data={'scene': '旧分镜'})
            old_other = StoryboardItem(project_id=self.project_id, chapter_id=other_chapter_id, sequence=1, data={'scene': '其他章节'})
            task = Task(type='chapter_storyboard', status='pending', project_id=self.project_id)
            session.add(old_current)
            session.add(old_other)
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id

        ai_output = '''```json
{"type":"storyboard","scene":"新场景1","action":"行动1","characters":["主角"],"prompt":"画面1"}
```
```json
{"type":"storyboard","scene":"新场景2","action":"行动2","characters":["主角"],"prompt":"画面2","selected_outfits":{"主角":"默认"}}
```'''
        with patch('app.routers.generation.AIService.generate_storyboard', return_value=ai_output) as generate_mock:
            from app.routers.generation import generate_chapter_storyboard_task
            generate_chapter_storyboard_task(task_id, chapter_id, '保持紧凑')

        self.assertTrue(generate_mock.called)
        with Session(engine) as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, 'completed')
            current_items = session.exec(select(StoryboardItem).where(StoryboardItem.project_id == self.project_id, StoryboardItem.chapter_id == chapter_id)).all()
            other_items = session.exec(select(StoryboardItem).where(StoryboardItem.project_id == self.project_id, StoryboardItem.chapter_id == other_chapter_id)).all()
            self.assertEqual(len(current_items), 2)
            self.assertEqual([item.data['scene'] for item in current_items], ['新场景1', '新场景2'])
            self.assertEqual(current_items[1].selected_outfits, {'主角': '默认'})
            self.assertEqual(len(other_items), 1)
            self.assertEqual(other_items[0].data['scene'], '其他章节')

    def test_panel_outfit_prompt_uses_selected_outfit_and_default_fallback(self):
        character_id = self.create_character(name='主角')
        with Session(engine) as session:
            character = session.get(Character, character_id)
            default_outfit = CharacterOutfit(
                project_id=self.project_id,
                character_id=character_id,
                name='常服',
                description='素色短衣',
                is_default=True,
            )
            battle_outfit = CharacterOutfit(
                project_id=self.project_id,
                character_id=character_id,
                name='战斗服',
                description='轻甲长袍',
                scene='战斗',
                colors='黑金',
                materials='皮革与金属',
                accessories='护腕',
                state='完好',
            )
            session.add(default_outfit)
            session.add(battle_outfit)
            session.commit()
            session.refresh(battle_outfit)

            item = StoryboardItem(
                project_id=self.project_id,
                sequence=1,
                data={'characters': ['主角'], 'selected_outfits': {'主角': '战斗服'}},
                selected_outfits={'主角': '战斗服'},
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.refresh(character)

            prompt = build_panel_outfit_prompt(character.project, item, ['主角'])
            self.assertIn('主角 服饰：战斗服', prompt)
            self.assertIn('描述：轻甲长袍', prompt)
            self.assertIn('颜色：黑金', prompt)

            item.selected_outfits = {}
            item.data = {'characters': ['主角']}
            fallback_prompt = build_panel_outfit_prompt(character.project, item, ['主角'])
            self.assertIn('主角 服饰：常服', fallback_prompt)

    def test_generate_chapter_content_saves_content_preview_and_version(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 3, 'title': '第三章', 'summary': '准备进入遗迹'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        captured = {}

        def fake_generate(self, context_prompt, user_input='', on_delta=None):
            captured['context_prompt'] = context_prompt
            captured['user_input'] = user_input
            return '这是 AI 生成的章节正文\n包含第二段内容。'

        extraction_json = '''```json
{"memories":[{"content":"主角进入遗迹","memory_type":"event","tags":["遗迹"],"importance":4}],"character_states":[],"progress":{"current_location":"遗迹入口","active_threads":["探索遗迹"],"pending_hooks":["未知机关"]}}
```'''
        with patch('app.routers.generation.AIService.generate_chapter_content', fake_generate), \
             patch('app.services.chapter_state_extraction_service.AIService.generate_text', return_value=extraction_json):
            response = self.client.post(
                f'/api/v1/generate/chapter-content/{chapter_id}',
                json={'user_input': '强调悬疑气氛', 'save_version': True},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['content'], '这是 AI 生成的章节正文\n包含第二段内容。')
        self.assertTrue(body['preview_text'])
        self.assertEqual(captured['user_input'], '强调悬疑气氛')
        self.assertIn('【当前章节】', captured['context_prompt'])
        self.assertIn('第三章', captured['context_prompt'])

        with Session(engine) as session:
            saved_chapter = session.exec(select(Chapter).where(Chapter.id == chapter_id)).one()
            self.assertEqual(saved_chapter.content, '这是 AI 生成的章节正文\n包含第二段内容。')
            self.assertTrue(saved_chapter.preview_text)

            versions = session.exec(
                select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)
            ).all()
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].content, '这是 AI 生成的章节正文\n包含第二段内容。')

            memories = session.exec(select(MemoryEntry).where(MemoryEntry.chapter_id == chapter_id)).all()
            self.assertEqual(len(memories), 1)
            self.assertEqual(memories[0].content, '主角进入遗迹')
            progress = session.exec(select(ProjectProgress).where(ProjectProgress.project_id == self.project_id)).one()
            self.assertEqual(progress.current_chapter_id, chapter_id)
            self.assertEqual(progress.current_location, '遗迹入口')
            self.assertEqual(progress.pending_hooks, ['未知机关'])

    def test_chapter_continuity_review_returns_structured_issues(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 5, 'title': '第五章', 'content': '主角无伤奔跑，但上一章受伤。'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        review_json = '''```json
{"summary":"发现 1 个连续性问题","issues":[{"severity":"high","category":"character_state","message":"伤势状态不一致","evidence":"上一章受伤，本章无伤奔跑","suggestion":"补充恢复说明"}]}
```'''
        with patch('app.services.chapter_continuity_review_service.AIService.generate_text', return_value=review_json):
            response = self.client.post(f'/api/v1/generate/chapter-continuity/{chapter_id}')

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['chapter_id'], chapter_id)
        self.assertEqual(body['summary'], '发现 1 个连续性问题')
        self.assertEqual(len(body['issues']), 1)
        self.assertEqual(body['issues'][0]['severity'], 'high')
        self.assertEqual(body['issues'][0]['category'], 'character_state')

    def test_chapter_continuity_review_requires_content_and_handles_non_json(self):
        empty_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 5, 'title': '空章节'},
        )
        self.assertEqual(empty_chapter.status_code, 200)
        empty_response = self.client.post(f'/api/v1/generate/chapter-continuity/{empty_chapter.json()["id"]}')
        self.assertEqual(empty_response.status_code, 400)

        blank_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 6, 'title': '空白章节', 'content': '   '},
        )
        self.assertEqual(blank_chapter.status_code, 200)
        blank_response = self.client.post(f'/api/v1/generate/chapter-continuity/{blank_chapter.json()["id"]}')
        self.assertEqual(blank_response.status_code, 400)

        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 7, 'title': '第七章', 'content': '已有正文'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        with patch('app.services.chapter_continuity_review_service.AIService.generate_text', return_value='无法输出结构化结果'):
            response = self.client.post(f'/api/v1/generate/chapter-continuity/{chapter_id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['issues'], [])
        self.assertIn('raw_output', response.json())

    def test_chapter_state_extraction_failure_does_not_block_content_generation(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 5, 'title': '第五章'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        with patch('app.routers.generation.AIService.generate_chapter_content', return_value='正文仍然保存'), \
             patch('app.services.chapter_state_extraction_service.AIService.generate_text', side_effect=RuntimeError('抽取失败')):
            response = self.client.post(
                f'/api/v1/generate/chapter-content/{chapter_id}',
                json={'user_input': '', 'save_version': True},
            )

        self.assertEqual(response.status_code, 200)
        with Session(engine) as session:
            saved_chapter = session.get(Chapter, chapter_id)
            self.assertEqual(saved_chapter.content, '正文仍然保存')
            versions = session.exec(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id)).all()
            self.assertEqual(len(versions), 1)
            memories = session.exec(select(MemoryEntry).where(MemoryEntry.chapter_id == chapter_id)).all()
            self.assertEqual(memories, [])

    def test_chapter_state_extraction_updates_character_state(self):
        character_id = self.create_character(name='主角')
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 6, 'title': '第六章'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        extraction_json = '''```json
{"memories":[],"character_states":[{"character_name":"主角","physical_state":"受伤","emotional_state":"警惕","location":"山洞","goal":"寻找出口","inventory":["火把"],"notes":"刚经历战斗"}],"progress":{}}
```'''
        with patch('app.routers.generation.AIService.generate_chapter_content', return_value='主角在山洞受伤，拿着火把寻找出口。'), \
             patch('app.services.chapter_state_extraction_service.AIService.generate_text', return_value=extraction_json):
            response = self.client.post(
                f'/api/v1/generate/chapter-content/{chapter_id}',
                json={'user_input': '', 'save_version': False},
            )

        self.assertEqual(response.status_code, 200)
        with Session(engine) as session:
            state = session.exec(
                select(CharacterState).where(CharacterState.chapter_id == chapter_id, CharacterState.character_id == character_id)
            ).one()
            self.assertEqual(state.physical_state, '受伤')
            self.assertEqual(state.emotional_state, '警惕')
            self.assertEqual(state.inventory, ['火把'])

    def test_relationship_character_state_progress_and_memory_filters(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 4, 'title': '第四章'},
        )
        self.assertEqual(chapter.status_code, 200)
        chapter_id = chapter.json()['id']

        source_id = self.create_character(name='甲')
        target_id = self.create_character(name='乙')
        outfit_id = self.create_outfit(source_id, name='战甲')

        relationship = self.client.post(
            f'/api/v1/projects/{self.project_id}/relationships',
            json={
                'source_character_id': source_id,
                'target_character_id': target_id,
                'relationship_type': 'ally',
                'intensity': 4,
                'chapter_id': chapter_id,
                'tags': ['初识'],
            },
        )
        self.assertEqual(relationship.status_code, 200)
        relationship_id = relationship.json()['id']

        relationship_update = self.client.put(
            f'/api/v1/projects/{self.project_id}/relationships/{relationship_id}',
            json={'status': 'strained', 'intensity': 5},
        )
        self.assertEqual(relationship_update.status_code, 200)
        self.assertEqual(relationship_update.json()['status'], 'strained')
        self.assertEqual(relationship_update.json()['intensity'], 5)

        invalid_relationship = self.client.post(
            f'/api/v1/projects/{self.project_id}/relationships',
            json={
                'source_character_id': source_id,
                'target_character_id': source_id,
                'relationship_type': 'self',
                'intensity': 3,
            },
        )
        self.assertEqual(invalid_relationship.status_code, 400)

        invalid_intensity = self.client.post(
            f'/api/v1/projects/{self.project_id}/relationships',
            json={
                'source_character_id': source_id,
                'target_character_id': target_id,
                'relationship_type': 'enemy',
                'intensity': 6,
            },
        )
        self.assertEqual(invalid_intensity.status_code, 400)

        state = self.client.post(
            f'/api/v1/projects/{self.project_id}/character-states',
            json={
                'character_id': source_id,
                'chapter_id': chapter_id,
                'outfit_id': outfit_id,
                'physical_state': '受伤',
                'emotional_state': '紧张',
                'inventory': ['短刀'],
            },
        )
        self.assertEqual(state.status_code, 200)
        state_id = state.json()['id']

        filtered_states = self.client.get(
            f'/api/v1/projects/{self.project_id}/character-states',
            params={'chapter_id': chapter_id, 'character_id': source_id},
        )
        self.assertEqual(filtered_states.status_code, 200)
        self.assertEqual(len(filtered_states.json()), 1)

        updated_state = self.client.put(
            f'/api/v1/projects/{self.project_id}/character-states/{state_id}',
            json={'notes': '准备迎战'},
        )
        self.assertEqual(updated_state.status_code, 200)
        self.assertEqual(updated_state.json()['notes'], '准备迎战')

        memory = self.client.post(
            f'/api/v1/projects/{self.project_id}/memories',
            json={
                'content': '甲在第三章受伤',
                'memory_type': 'event',
                'chapter_id': chapter_id,
                'character_id': source_id,
            },
        )
        self.assertEqual(memory.status_code, 200)

        filtered_memories = self.client.get(
            f'/api/v1/projects/{self.project_id}/memories',
            params={'memory_type': 'event', 'chapter_id': chapter_id, 'character_id': source_id},
        )
        self.assertEqual(filtered_memories.status_code, 200)
        self.assertEqual(len(filtered_memories.json()), 1)

        progress = self.client.get(f'/api/v1/projects/{self.project_id}/progress')
        self.assertEqual(progress.status_code, 200)
        self.assertIsNone(progress.json()['current_chapter_id'])

        updated_progress = self.client.put(
            f'/api/v1/projects/{self.project_id}/progress',
            json={
                'current_chapter_id': chapter_id,
                'current_arc': '第一幕',
                'active_threads': ['追查真相'],
            },
        )
        self.assertEqual(updated_progress.status_code, 200)
        self.assertEqual(updated_progress.json()['current_chapter_id'], chapter_id)
        self.assertEqual(updated_progress.json()['current_arc'], '第一幕')

    def test_rejects_cross_project_references(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 4, 'title': '第四章'},
        )
        self.assertEqual(chapter.status_code, 200)

        other_project = self.client.post('/api/v1/projects/', json={'title': 'other project'}).json()
        other_project_id = other_project['id']
        other_character_id = None
        with Session(engine) as session:
            other_character = Character(project_id=other_project_id, name='外部角色', data={'name': '外部角色'})
            session.add(other_character)
            session.commit()
            session.refresh(other_character)
            other_character_id = other_character.id

        invalid_memory = self.client.post(
            f'/api/v1/projects/{self.project_id}/memories',
            json={'content': '跨项目引用', 'character_id': other_character_id},
        )
        self.assertEqual(invalid_memory.status_code, 404)

        invalid_progress = self.client.put(
            f'/api/v1/projects/{self.project_id}/progress',
            json={'current_chapter_id': 999999},
        )
        self.assertEqual(invalid_progress.status_code, 404)


if __name__ == '__main__':
    unittest.main()
