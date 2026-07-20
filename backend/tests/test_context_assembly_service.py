import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.core.database import engine, init_db
from app.models.models import (
    Chapter,
    Character,
    CharacterOutfit,
    CharacterRelationship,
    CharacterState,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingCategory,
    SettingEntry,
)
from app.services.context_assembly_service import ContextAssemblyService


class ContextAssemblyServiceTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.project_id = None
        self.chapter_id = None
        self.character_a_id = None
        self.character_b_id = None
        self.outfit_id = None

        with Session(engine) as session:
            project = Project(
                title='苍穹回响',
                description='修真与遗迹并存的长篇故事',
                theme='成长与真相',
                language='zh-CN',
            )
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project_id = project.id

            chapter = Chapter(
                project_id=project.id,
                sequence=1,
                title='第一章 旧塔异响',
                summary='主角夜探古塔，发现异变。',
                goal='调查钟声来源',
                conflict='守塔人阻拦进入',
                current_location='青石镇古塔',
                current_time='夜半',
                pov_character='林澈',
                chapter_metadata={'mood': '紧张', 'weather': '暴雨'},
            )
            session.add(chapter)
            session.commit()
            session.refresh(chapter)
            self.chapter_id = chapter.id

            category = SettingCategory(project_id=project.id, name='世界规则', description='世界底层规则')
            session.add(category)
            session.commit()
            session.refresh(category)

            setting = SettingEntry(
                project_id=project.id,
                category_id=category.id,
                title='灵潮汐',
                content='每逢月蚀，塔内灵力会逆流。',
                tags=['灵力', '月蚀'],
                importance=5,
                is_active=True,
            )
            inactive_setting = SettingEntry(
                project_id=project.id,
                category_id=category.id,
                title='废弃设定',
                content='不应出现在上下文中',
                is_active=False,
            )
            session.add(setting)
            session.add(inactive_setting)

            project_outline = Outline(
                project_id=project.id,
                scope='project',
                title='主线大纲',
                content='主角逐步揭开古塔与身世关联。',
                sort_order=1,
            )
            chapter_outline = Outline(
                project_id=project.id,
                scope='chapter',
                title='第一章小纲',
                content='潜入、受阻、听见塔顶钟鸣。',
                chapter_id=chapter.id,
                sort_order=1,
            )
            other_chapter = Chapter(project_id=project.id, sequence=2, title='第二章')
            session.add(other_chapter)
            session.commit()
            session.refresh(other_chapter)
            other_outline = Outline(
                project_id=project.id,
                scope='chapter',
                title='第二章小纲',
                content='不应出现在第一章上下文中',
                chapter_id=other_chapter.id,
                sort_order=1,
            )
            session.add(project_outline)
            session.add(chapter_outline)
            session.add(other_outline)

            character_a = Character(
                project_id=project.id,
                name='林澈',
                summary='背负家族秘密的少年',
                aliases=['阿澈'],
                status='active',
                data={'role': 'protagonist'},
            )
            character_b = Character(
                project_id=project.id,
                name='沈砚',
                summary='守塔人',
                status='active',
                data={'role': 'guardian'},
            )
            session.add(character_a)
            session.add(character_b)
            session.commit()
            session.refresh(character_a)
            session.refresh(character_b)
            self.character_a_id = character_a.id
            self.character_b_id = character_b.id

            outfit = CharacterOutfit(
                project_id=project.id,
                character_id=character_a.id,
                name='巡夜斗篷',
                description='带雨痕的黑色斗篷',
                state='潮湿',
                is_default=True,
            )
            session.add(outfit)
            session.commit()
            session.refresh(outfit)
            self.outfit_id = outfit.id

            project_relationship = CharacterRelationship(
                project_id=project.id,
                source_character_id=character_a.id,
                target_character_id=character_b.id,
                relationship_type='mentor',
                description='表面冷淡，实则暗中引导',
                intensity=4,
            )
            chapter_relationship = CharacterRelationship(
                project_id=project.id,
                source_character_id=character_b.id,
                target_character_id=character_a.id,
                relationship_type='opposes',
                description='本章阻止林澈登塔',
                intensity=5,
                chapter_id=chapter.id,
            )
            session.add(project_relationship)
            session.add(chapter_relationship)

            project_state = CharacterState(
                project_id=project.id,
                character_id=character_a.id,
                physical_state='疲惫',
                emotional_state='戒备',
                location='青石镇',
                goal='查明真相',
                inventory=['铜铃'],
                notes='长期失眠',
            )
            chapter_state = CharacterState(
                project_id=project.id,
                character_id=character_a.id,
                chapter_id=chapter.id,
                outfit_id=outfit.id,
                physical_state='淋雨发冷',
                emotional_state='紧张',
                location='古塔门前',
                goal='潜入古塔',
                power_level='一阶',
                inventory=['铜铃', '短刀'],
                notes='听见塔顶异响',
            )
            session.add(project_state)
            session.add(chapter_state)

            progress = ProjectProgress(
                project_id=project.id,
                current_chapter_id=chapter.id,
                current_arc='古塔迷局',
                current_location='青石镇',
                current_time='夜半',
                main_conflict='是否进入古塔并揭开异响',
                active_threads=['钟声来源', '家族秘闻'],
                resolved_threads=['取得塔钥'],
                pending_hooks=['塔顶黑影'],
                notes='需要保持悬疑感',
            )
            session.add(progress)

            memory_project = MemoryEntry(
                project_id=project.id,
                scope='project',
                content='林澈幼时曾在塔下失踪半日。',
                memory_type='event',
                character_id=character_a.id,
                importance=5,
                is_active=True,
            )
            memory_chapter = MemoryEntry(
                project_id=project.id,
                scope='chapter',
                chapter_id=chapter.id,
                content='沈砚警告今夜绝不能敲响塔钟。',
                memory_type='warning',
                character_id=character_b.id,
                importance=4,
                is_active=True,
            )
            filtered_low_importance = MemoryEntry(
                project_id=project.id,
                scope='project',
                content='低重要度记忆',
                importance=2,
                is_active=True,
            )
            filtered_inactive = MemoryEntry(
                project_id=project.id,
                scope='project',
                content='停用记忆',
                importance=5,
                is_active=False,
            )
            filtered_other_chapter = MemoryEntry(
                project_id=project.id,
                scope='chapter',
                chapter_id=other_chapter.id,
                content='其他章节记忆',
                importance=5,
                is_active=True,
            )
            session.add(memory_project)
            session.add(memory_chapter)
            session.add(filtered_low_importance)
            session.add(filtered_inactive)
            session.add(filtered_other_chapter)

            session.commit()

    def test_build_chapter_context_and_render_prompt(self):
        with Session(engine) as session:
            service = ContextAssemblyService(session)
            context = service.build_chapter_context(self.project_id, self.chapter_id)

            self.assertEqual(context['project'].title, '苍穹回响')
            self.assertEqual(context['chapter'].title, '第一章 旧塔异响')
            self.assertEqual(context['progress'].current_arc, '古塔迷局')

            outline_titles = [item.title for item in context['outlines']]
            self.assertIn('主线大纲', outline_titles)
            self.assertIn('第一章小纲', outline_titles)
            self.assertNotIn('第二章小纲', outline_titles)

            setting_titles = [item.title for item in context['settings']]
            self.assertIn('灵潮汐', setting_titles)
            self.assertNotIn('废弃设定', setting_titles)

            self.assertEqual(len(context['characters']), 2)
            main_character = next(item for item in context['characters'] if item.name == '林澈')
            self.assertEqual(len(main_character.outfits), 1)
            self.assertEqual(main_character.outfits[0].name, '巡夜斗篷')

            relationship_types = [item.relationship_type for item in context['relationships']]
            self.assertIn('mentor', relationship_types)
            self.assertIn('opposes', relationship_types)

            state_notes = [item.notes for item in context['states']]
            self.assertIn('长期失眠', state_notes)
            self.assertIn('听见塔顶异响', state_notes)

            memory_contents = [item.content for item in context['memories']]
            self.assertIn('林澈幼时曾在塔下失踪半日。', memory_contents)
            self.assertIn('沈砚警告今夜绝不能敲响塔钟。', memory_contents)
            self.assertNotIn('低重要度记忆', memory_contents)
            self.assertNotIn('停用记忆', memory_contents)
            self.assertNotIn('其他章节记忆', memory_contents)

            prompt = service.render_context_prompt(context)
            self.assertIn('【项目】', prompt)
            self.assertIn('【当前进度】', prompt)
            self.assertIn('【当前章节】', prompt)
            self.assertIn('【大纲/小纲】', prompt)
            self.assertIn('【世界设定】', prompt)
            self.assertIn('【角色】', prompt)
            self.assertIn('【人物关系】', prompt)
            self.assertIn('【角色当前状态】', prompt)
            self.assertIn('【记忆与连续性约束】', prompt)
            self.assertIn('灵潮汐', prompt)
            self.assertIn('林澈', prompt)
            self.assertIn('mentor', prompt)
            self.assertIn('淋雨发冷', prompt)
            self.assertIn('林澈幼时曾在塔下失踪半日。', prompt)
            self.assertIn('巡夜斗篷', prompt)
            self.assertIn('mood=紧张', prompt)

    def test_get_progress_returns_none_when_missing(self):
        with Session(engine) as session:
            project = Project(title='无进度项目')
            session.add(project)
            session.commit()
            session.refresh(project)

            chapter = Chapter(project_id=project.id, sequence=1, title='空白章节')
            session.add(chapter)
            session.commit()
            session.refresh(chapter)

            service = ContextAssemblyService(session)
            self.assertIsNone(service.get_progress(project.id))

            context = service.build_chapter_context(project.id, chapter.id)
            self.assertIsNone(context['progress'])
            prompt = service.render_context_prompt(context)
            self.assertIn('暂无项目进度记录。', prompt)


if __name__ == '__main__':
    unittest.main()
