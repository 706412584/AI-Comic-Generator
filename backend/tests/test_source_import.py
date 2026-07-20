import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from unittest.mock import patch

from app.core.database import engine, init_db
from app.main import app
from app.models.models import AgentRun, Chapter, ChapterVersion, SourceChapter, SourceImport, Task
from app.services.context_assembly_service import ContextAssemblyService
from app.services.source_import_service import split_novel_chapters


class SourceImportTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        project = self.client.post('/api/v1/projects/', json={'title': 'source import test'}).json()
        self.project_id = project['id']

    def test_split_novel_chapters_with_arabic_numbers(self):
        raw_text = '简介内容\n第1章 修仙可以，吃苦不行\n正文一\n第2章 山雨欲来\n正文二'
        chapters = split_novel_chapters(raw_text)
        self.assertEqual([chapter['title'] for chapter in chapters], ['序章', '第1章 修仙可以，吃苦不行', '第2章 山雨欲来'])
        self.assertIn('正文一', chapters[1]['raw_text'])

    def test_split_novel_chapters_with_chinese_numbers(self):
        raw_text = '第一章 初入山门\n正文一\n第十章 风起云涌\n正文十'
        chapters = split_novel_chapters(raw_text)
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]['title'], '第一章 初入山门')
        self.assertEqual(chapters[1]['title'], '第十章 风起云涌')

    def test_split_novel_chapters_falls_back_to_full_text(self):
        chapters = split_novel_chapters('没有章节标题的全文内容')
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]['title'], '全文')

    def test_create_source_import_splits_and_lists_chapters(self):
        raw_text = '『小说信息』\n第1章 修仙可以，吃苦不行\n第一章正文\n第2章 半日斩五王\n第二章正文'
        response = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': '我真不想修仙啊！.txt', 'raw_text': raw_text},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['file_name'], '我真不想修仙啊！.txt')
        self.assertEqual(data['chapter_count'], 3)
        self.assertEqual(data['analyzed_chapter_count'], 0)
        self.assertEqual(data['unanalyzed_chapter_count'], 3)
        self.assertEqual(data['text_length'], len(raw_text.strip()))

        chapters_response = self.client.get(f'/api/v1/projects/{self.project_id}/source-chapters')
        self.assertEqual(chapters_response.status_code, 200)
        chapters = chapters_response.json()
        self.assertEqual([chapter['title'] for chapter in chapters], ['序章', '第1章 修仙可以，吃苦不行', '第2章 半日斩五王'])

        detail_response = self.client.get(f'/api/v1/projects/{self.project_id}/source-chapters/{chapters[1]["id"]}')
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn('第一章正文', detail_response.json()['raw_text'])

        with Session(engine) as session:
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            source_chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id)).all()
            self.assertEqual(source_import.chapter_count, 3)
            self.assertEqual(len(source_chapters), 3)

    def test_update_source_chapter_recounts_text(self):
        raw_text = '第1章 旧标题\n旧正文'
        source_import = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': raw_text},
        ).json()
        chapter = self.client.get(
            f'/api/v1/projects/{self.project_id}/source-chapters?source_import_id={source_import["id"]}'
        ).json()[0]

        response = self.client.put(
            f'/api/v1/projects/{self.project_id}/source-chapters/{chapter["id"]}',
            json={'title': '第1章 新标题', 'raw_text': '第1章 新标题\n新正文'},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['title'], '第1章 新标题')
        self.assertEqual(data['raw_word_count'], len('第1章 新标题\n新正文'))

    def test_source_analysis_updates_chapter_and_book_summaries(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n许闲拒绝吃苦\n第2章 入门\n众人劝他修仙'},
        )
        responses = [
            '{"summary_short":"许闲拒绝吃苦。","summary_medium":"许闲面对修仙邀请。","key_characters":["许闲"],"key_locations":["后山"],"key_events":["拒绝吃苦"],"time_markers":["傍晚"]}',
            '{"summary_short":"众人劝许闲入门。","summary_medium":"许闲被带入修仙门槛。","key_characters":["许闲"],"key_locations":["山门"],"key_events":["入门"],"time_markers":["次日"]}',
            '{"book_summary":"许闲不想吃苦却卷入修仙。","world_summary":"修仙世界。","character_summary":"许闲是主角。","outline_summary":"从拒绝修仙到被迫入局。"}',
        ]
        with patch('app.routers.generation.AIService.generate_text', side_effect=responses):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}')

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id).order_by(SourceChapter.sequence)).all()
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertEqual(task.status, 'completed')
            self.assertIsNotNone(agent_run)
            self.assertEqual(agent_run.agent_name, 'source_analysis')
            self.assertEqual(agent_run.status, 'completed')
            self.assertEqual(agent_run.total_steps, 5)
            self.assertEqual(source_import.import_status, 'analyzed')
            self.assertEqual(source_import.book_summary, '许闲不想吃苦却卷入修仙。')
            self.assertEqual(chapters[0].summary_short, '许闲拒绝吃苦。')
            self.assertEqual(chapters[1].key_events, ['入门'])

    def test_source_analysis_continues_after_single_chapter_failure(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n正文一\n第2章 发展\n正文二\n第3章 结尾\n正文三'},
        )
        responses = [
            '{"summary_short":"第一章摘要","summary_medium":"第一章中摘要","key_characters":[],"key_locations":[],"key_events":[],"time_markers":[]}',
            '不是 JSON',
            '{"summary_short":"第三章摘要","summary_medium":"第三章中摘要","key_characters":[],"key_locations":[],"key_events":[],"time_markers":[]}',
            '{"book_summary":"全书","world_summary":"世界","character_summary":"角色","outline_summary":"大纲"}',
        ]
        with patch('app.routers.generation.AIService.generate_text', side_effect=responses):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}', json={'mode': 'all'})

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id).order_by(SourceChapter.sequence)).all()
            self.assertEqual(task.status, 'completed')
            self.assertEqual(task.result['failed_count'], 1)
            self.assertEqual(task.result['analyzed_this_run'], 2)
            self.assertEqual(sum(1 for chapter in chapters if chapter.analysis_status == 'analyzed'), 2)
            self.assertEqual(sum(1 for chapter in chapters if chapter.analysis_status == 'failed'), 1)
            self.assertEqual(chapters[1].analysis_attempts, 1)
            self.assertTrue(chapters[1].analysis_error)
            self.assertEqual(source_import.import_status, 'analyzed_with_errors')

    def test_source_analysis_fails_when_all_chapters_fail(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n正文一\n第2章 发展\n正文二'},
        )
        with patch('app.routers.generation.AIService.generate_text', side_effect=['坏 JSON', '仍然坏 JSON']):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}', json={'mode': 'all'})

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id).order_by(SourceChapter.sequence)).all()
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertEqual(task.status, 'failed')
            self.assertIn('全部失败', task.message)
            self.assertEqual(agent_run.status, 'failed')
            self.assertTrue(all(chapter.analysis_status == 'failed' for chapter in chapters))

    def test_source_analysis_model_config_error_fails_immediately(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n正文一\n第2章 发展\n正文二'},
        )
        with patch('app.routers.generation.AIService.generate_text', side_effect=ValueError('No active configuration found for text model.')):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}', json={'mode': 'all'})

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id).order_by(SourceChapter.sequence)).all()
            self.assertEqual(task.status, 'failed')
            self.assertIn('No active configuration found', task.message)
            self.assertEqual([chapter.analysis_attempts for chapter in chapters], [0, 0])
            self.assertEqual([chapter.analysis_status for chapter in chapters], ['pending', 'pending'])

    def test_source_chapter_search_and_custom_resplit_preview(self):
        source_import = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'custom.txt', 'raw_text': '卷一 开始\n正文A\n卷二 继续\n正文B'},
        ).json()

        preview = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports/{source_import["id"]}/resplit-preview',
            json={'split_pattern': r'^(卷[一二三四五六七八九十]+[^\n]*)'},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()['chapter_count'], 2)

        resplit = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports/{source_import["id"]}/resplit',
            json={'split_pattern': r'^(卷[一二三四五六七八九十]+[^\n]*)'},
        )
        self.assertEqual(resplit.status_code, 200)
        self.assertEqual(resplit.json()['chapter_count'], 2)

        search = self.client.get(f'/api/v1/projects/{self.project_id}/source-chapters?q=继续')
        self.assertEqual(search.status_code, 200)
        self.assertEqual(len(search.json()), 1)
        self.assertEqual(search.json()[0]['title'], '卷二 继续')

    def test_resplit_remaps_or_clears_bound_source_chapters(self):
        source_import = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n甲\n第2章 发展\n乙\n第3章 结尾\n丙'},
        ).json()
        source_chapters = self.client.get(f'/api/v1/projects/{self.project_id}/source-chapters').json()
        first_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '绑定第一章', 'source_chapter_id': source_chapters[0]['id']},
        ).json()
        third_chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 3, 'title': '绑定第三章', 'source_chapter_id': source_chapters[2]['id']},
        ).json()

        resplit = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports/{source_import["id"]}/resplit',
            json={'split_pattern': r'^(第[12]章[^\n]*)'},
        )

        self.assertEqual(resplit.status_code, 200)
        self.assertEqual(resplit.json()['chapter_count'], 2)
        new_source_chapters = self.client.get(f'/api/v1/projects/{self.project_id}/source-chapters').json()
        first_detail = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{first_chapter["id"]}').json()
        third_detail = self.client.get(f'/api/v1/projects/{self.project_id}/chapters/{third_chapter["id"]}').json()
        self.assertEqual(first_detail['source_chapter_id'], new_source_chapters[0]['id'])
        self.assertIsNone(third_detail['source_chapter_id'])

    def test_source_analysis_marks_large_partial_run_explicitly(self):
        raw_text = ''.join([f'第{i}章 标题{i}\n正文{i}\n' for i in range(1, 56)])
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'large.txt', 'raw_text': raw_text},
        )
        responses = [
            '{"summary_short":"短摘要","summary_medium":"中摘要","key_characters":[],"key_locations":[],"key_events":[],"time_markers":[]}'
        ] * 50
        responses.append('{"book_summary":"全书","world_summary":"世界","character_summary":"角色","outline_summary":"大纲"}')

        with patch('app.routers.generation.AIService.generate_text', side_effect=responses):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}')

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id)).all()
            self.assertEqual(task.status, 'completed')
            self.assertEqual(source_import.import_status, 'partially_analyzed')
            self.assertEqual(task.result['analyzed_chapters'], 50)
            self.assertEqual(task.result['total_chapters'], 55)
            self.assertTrue(task.result['partial'])
            self.assertEqual(sum(1 for chapter in chapters if chapter.summary_short), 50)

        continue_responses = [
            '{"summary_short":"续跑摘要","summary_medium":"续跑中摘要","key_characters":[],"key_locations":[],"key_events":[],"time_markers":[]}'
        ] * 5
        continue_responses.append('{"book_summary":"全书2","world_summary":"世界2","character_summary":"角色2","outline_summary":"大纲2"}')
        with patch('app.routers.generation.AIService.generate_text', side_effect=continue_responses):
            response = self.client.post(
                f'/api/v1/generate/source-analyze/{self.project_id}',
                json={'mode': 'continue', 'max_chapters': 50},
            )
        self.assertEqual(response.status_code, 200)
        with Session(engine) as session:
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            chapters = session.exec(select(SourceChapter).where(SourceChapter.source_import_id == source_import.id)).all()
            self.assertEqual(source_import.import_status, 'analyzed')
            self.assertEqual(sum(1 for chapter in chapters if chapter.summary_short), 55)

    def test_source_analysis_uses_layered_summary_for_long_books(self):
        raw_text = ''.join([f'第{i}章 标题{i}\n正文{i}\n' for i in range(1, 6)])
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'layered.txt', 'raw_text': raw_text},
        )
        chapter_response = '{"summary_short":"章节短摘要","summary_medium":"章节中摘要","key_characters":[],"key_locations":[],"key_events":[],"time_markers":[]}'
        responses = [chapter_response] * 5 + [
            '{"title":"开篇分组","summary":"第一到二章分组摘要","key_characters":["甲"],"key_events":["开端"],"key_locations":["甲地"]}',
            '{"title":"发展分组","summary":"第三到四章分组摘要","key_characters":["乙"],"key_events":["发展"],"key_locations":["乙地"]}',
            '{"title":"收束分组","summary":"第五章分组摘要","key_characters":["丙"],"key_events":["收束"],"key_locations":["丙地"]}',
            '{"book_summary":"分层全书摘要","world_summary":"分层世界","character_summary":"分层角色","outline_summary":"分层大纲"}',
        ]

        with patch('app.agents.source_analysis_agent.LAYERED_SUMMARY_THRESHOLD', 2), \
             patch('app.agents.source_analysis_agent.SOURCE_SUMMARY_CHUNK_SIZE', 2), \
             patch('app.routers.generation.AIService.generate_text', side_effect=responses):
            response = self.client.post(f'/api/v1/generate/source-analyze/{self.project_id}', json={'mode': 'all'})

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertEqual(task.status, 'completed')
            self.assertEqual(source_import.book_summary, '分层全书摘要')
            self.assertEqual(len(source_import.summary_layers['chunks']), 3)
            self.assertEqual(source_import.summary_layers['chunk_size'], 2)
            self.assertEqual(source_import.summary_layers['analyzed_chapter_count'], 5)
            self.assertTrue(task.result['layered_summary'])
            self.assertEqual(task.result['chunk_count'], 3)
            self.assertTrue(agent_run.result_payload['layered_summary'])
            self.assertEqual(agent_run.result_payload['chunk_count'], 3)

    def test_source_initialization_context_prefers_layered_summary(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'layered-init.txt', 'raw_text': '第1章 开端\n正文一\n第2章 发展\n正文二'},
        )
        with Session(engine) as session:
            source_import = session.exec(select(SourceImport).where(SourceImport.project_id == self.project_id)).first()
            source_import.book_summary = '分层全书'
            source_import.world_summary = '分层世界'
            source_import.character_summary = '分层角色'
            source_import.outline_summary = '分层大纲'
            source_import.summary_layers = {
                'chunk_size': 1,
                'threshold': 1,
                'analyzed_chapter_count': 2,
                'chunks': [
                    {'index': 1, 'start_sequence': 1, 'end_sequence': 1, 'title': '第一组', 'summary': '第一组摘要', 'key_characters': ['甲'], 'key_events': ['事件甲'], 'key_locations': ['地点甲']},
                    {'index': 2, 'start_sequence': 2, 'end_sequence': 2, 'title': '第二组', 'summary': '第二组摘要', 'key_characters': ['乙'], 'key_events': ['事件乙'], 'key_locations': ['地点乙']},
                ],
                'book': {'book_summary': '分层全书', 'world_summary': '分层世界', 'character_summary': '分层角色', 'outline_summary': '分层大纲'},
            }
            session.add(source_import)
            session.commit()

        captured_prompts = []
        ai_payloads = [
            '{"project":{"title":"分层项目","description":"基于分层摘要","theme":"长篇","language":"zh-CN"},"settings":[]}',
            '{"characters":[],"relationships":[]}',
            '{"outlines":[],"chapters":[]}',
            '{"memories":[],"progress":{}}',
        ]

        def fake_generate_text(system_prompt, prompt):
            captured_prompts.append(prompt)
            return ai_payloads.pop(0)

        with patch('app.routers.generation.AIService.generate_text', side_effect=fake_generate_text):
            response = self.client.post(f'/api/v1/generate/project-initialize-from-source/{self.project_id}')

        self.assertEqual(response.status_code, 200)
        joined_prompts = '\n'.join(captured_prompts)
        self.assertIn('上下文类型：分层摘要', joined_prompts)
        self.assertIn('分层摘要分组数：2', joined_prompts)
        self.assertIn('第一组摘要', joined_prompts)
        self.assertIn('第二组摘要', joined_prompts)
        self.assertNotIn('只覆盖开篇', joined_prompts)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertTrue(agent_run.state_payload['load_source_context']['layered_context'])

    def test_initialize_project_from_source_maps_chapters(self):
        self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n许闲拒绝吃苦\n第2章 入门\n众人劝他修仙'},
        )
        ai_payloads = [
            '{"project":{"title":"我真不想修仙啊","description":"许闲被迫修仙","theme":"轻松修仙","language":"zh-CN"},"settings":[{"category":"世界观","title":"吃苦修仙","content":"修仙必须吃苦","tags":["修仙"],"importance":5}]}',
            '{"characters":[{"name":"许闲","summary":"不想吃苦的主角","data":{"role":"主角"},"outfits":[{"name":"布衣","description":"普通村民衣服","is_default":true}]}],"relationships":[]}',
            '{"outlines":[{"scope":"project","title":"全书大纲","content":"许闲被迫修仙","sort_order":0}],"chapters":[{"sequence":1,"source_sequence":1,"title":"开端","summary":"许闲拒绝吃苦","tasks":[]},{"sequence":2,"source_sequence":2,"title":"入门","summary":"众人劝修仙","tasks":[]}]}',
            '{"memories":[{"scope":"project","content":"许闲不想吃苦","memory_type":"character","tags":["主角"],"importance":4}],"progress":{"current_arc":"开篇","notes":"原文初始化"}}',
        ]
        with patch('app.routers.generation.AIService.generate_text', side_effect=ai_payloads):
            response = self.client.post(f'/api/v1/generate/project-initialize-from-source/{self.project_id}')

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        agent_runs_response = self.client.get(f'/api/v1/tasks/{task_id}/agent-runs')
        self.assertEqual(agent_runs_response.status_code, 200)
        self.assertEqual(agent_runs_response.json()[0]['agent_name'], 'source_project_init')
        with Session(engine) as session:
            task = session.get(Task, task_id)
            chapters = session.exec(select(Chapter).where(Chapter.project_id == self.project_id).order_by(Chapter.sequence)).all()
            source_chapters = session.exec(select(SourceChapter).where(SourceChapter.project_id == self.project_id).order_by(SourceChapter.sequence)).all()
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertEqual(task.status, 'completed')
            self.assertIsNotNone(agent_run)
            self.assertEqual(agent_run.agent_name, 'source_project_init')
            self.assertEqual(agent_run.status, 'completed')
            self.assertEqual(agent_run.total_steps, 6)
            self.assertIn('generate_project_settings', agent_run.state_payload)
            self.assertEqual(len(chapters), 2)
            self.assertEqual(chapters[0].source_chapter_id, source_chapters[0].id)
            self.assertEqual(source_chapters[1].mapped_chapter_id, chapters[1].id)

    def test_chapter_content_task_runs_agent_and_saves_version(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '开端', 'summary': '主角入场'},
        ).json()

        with patch('app.agents.chapter_adaptation_agent.AIService.generate_chapter_content', return_value='这是 AI 生成的章节正文'):
            with patch('app.agents.chapter_adaptation_agent.extract_chapter_state_safely', return_value={'memories': 0, 'character_states': 0, 'progress_updated': False}):
                response = self.client.post(
                    f'/api/v1/generate/chapter-content-task/{chapter["id"]}',
                    json={'user_input': '写得紧张一点', 'save_version': True},
                )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        with Session(engine) as session:
            task = session.get(Task, task_id)
            updated_chapter = session.get(Chapter, chapter['id'])
            version = session.exec(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter['id'])).first()
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == task_id)).first()
            self.assertEqual(task.status, 'completed')
            self.assertIsNotNone(agent_run)
            self.assertEqual(agent_run.agent_name, 'chapter_adaptation')
            self.assertEqual(agent_run.status, 'completed')
            self.assertEqual(agent_run.total_steps, 5)
            self.assertIn('generate_content', agent_run.state_payload)
            self.assertEqual(updated_chapter.content, '这是 AI 生成的章节正文')
            self.assertEqual(updated_chapter.preview_text, '这是 AI 生成的章节正文')
            self.assertIsNotNone(version)
            self.assertEqual(version.content, '这是 AI 生成的章节正文')
            self.assertEqual(version.version_no, 1)

    def test_chapter_content_task_uses_chapter_scoped_inflight_lock(self):
        chapter1 = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '第一章', 'summary': '开端'},
        ).json()
        chapter2 = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 2, 'title': '第二章', 'summary': '发展'},
        ).json()

        with Session(engine) as session:
            running_task = Task(
                type='chapter_content_generation',
                status='processing',
                project_id=self.project_id,
                scope_type='chapter',
                scope_id=str(chapter1['id']),
            )
            session.add(running_task)
            session.commit()

        duplicate_response = self.client.post(
            f'/api/v1/generate/chapter-content-task/{chapter1["id"]}',
            json={'user_input': '重复生成', 'save_version': True},
        )
        self.assertEqual(duplicate_response.status_code, 400)

        with patch('app.agents.chapter_adaptation_agent.AIService.generate_chapter_content', return_value='第二章正文'), \
             patch('app.agents.chapter_adaptation_agent.extract_chapter_state_safely', return_value={'memories': 0, 'character_states': 0, 'progress_updated': False}):
            parallel_response = self.client.post(
                f'/api/v1/generate/chapter-content-task/{chapter2["id"]}',
                json={'user_input': '并行生成', 'save_version': False},
            )

        self.assertEqual(parallel_response.status_code, 200)
        task_id = parallel_response.json()['task_id']
        task_response = self.client.get(f'/api/v1/tasks/{task_id}')
        self.assertEqual(task_response.status_code, 200)
        task_data = task_response.json()
        self.assertEqual(task_data['scope_type'], 'chapter')
        self.assertEqual(task_data['scope_id'], str(chapter2['id']))
        self.assertEqual(task_data['input_payload']['chapter_id'], chapter2['id'])
        self.assertEqual(task_data['input_payload']['user_input'], '并行生成')
        self.assertFalse(task_data['input_payload']['save_version'])
        self.assertEqual(task_data['retry_count'], 0)
        self.assertIsNone(task_data['retry_of_task_id'])

    def test_retry_failed_chapter_content_task_creates_new_task_and_runs_agent(self):
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '重试章', 'summary': '需要重试'},
        ).json()
        with Session(engine) as session:
            failed_task = Task(
                type='chapter_content_generation',
                status='failed',
                project_id=self.project_id,
                name='生成章节正文：重试章',
                description='AI 正在基于章节上下文生成正文',
                scope_type='chapter',
                scope_id=str(chapter['id']),
                input_payload={
                    'chapter_id': chapter['id'],
                    'user_input': '重试输入',
                    'save_version': True,
                },
                retry_count=1,
            )
            session.add(failed_task)
            session.commit()
            session.refresh(failed_task)
            failed_task_id = failed_task.id

        with patch('app.agents.chapter_adaptation_agent.AIService.generate_chapter_content', return_value='重试后生成的正文'), \
             patch('app.agents.chapter_adaptation_agent.extract_chapter_state_safely', return_value={'memories': 0, 'character_states': 0, 'progress_updated': False}):
            response = self.client.post(f'/api/v1/tasks/{failed_task_id}/retry')

        self.assertEqual(response.status_code, 200)
        retry_data = response.json()
        self.assertNotEqual(retry_data['id'], failed_task_id)
        self.assertEqual(retry_data['retry_count'], 2)
        self.assertEqual(retry_data['retry_of_task_id'], failed_task_id)

        with Session(engine) as session:
            retry_task = session.get(Task, retry_data['id'])
            updated_chapter = session.get(Chapter, chapter['id'])
            agent_run = session.exec(select(AgentRun).where(AgentRun.task_id == retry_data['id'])).first()
            self.assertEqual(retry_task.status, 'completed')
            self.assertEqual(retry_task.scope_type, 'chapter')
            self.assertEqual(retry_task.scope_id, str(chapter['id']))
            self.assertEqual(retry_task.input_payload['user_input'], '重试输入')
            self.assertEqual(updated_chapter.content, '重试后生成的正文')
            self.assertIsNotNone(agent_run)
            self.assertEqual(agent_run.agent_name, 'chapter_adaptation')
            self.assertEqual(agent_run.status, 'completed')

    def test_retry_rejects_non_failed_and_unsupported_tasks(self):
        with Session(engine) as session:
            processing_task = Task(
                type='chapter_content_generation',
                status='processing',
                project_id=self.project_id,
                input_payload={'chapter_id': 1},
            )
            unsupported_task = Task(
                type='chapter_continuity_review',
                status='failed',
                project_id=self.project_id,
                input_payload={'project_id': self.project_id},
            )
            session.add(processing_task)
            session.add(unsupported_task)
            session.commit()
            session.refresh(processing_task)
            session.refresh(unsupported_task)
            processing_task_id = processing_task.id
            unsupported_task_id = unsupported_task.id

        non_failed_response = self.client.post(f'/api/v1/tasks/{processing_task_id}/retry')
        unsupported_response = self.client.post(f'/api/v1/tasks/{unsupported_task_id}/retry')

        self.assertEqual(non_failed_response.status_code, 400)
        self.assertEqual(unsupported_response.status_code, 400)

    def test_context_prompt_includes_mapped_source_chapter_text(self):
        source_import = self.client.post(
            f'/api/v1/projects/{self.project_id}/source-imports',
            json={'file_name': 'novel.txt', 'raw_text': '第1章 开端\n许闲拒绝吃苦\n第2章 入门\n众人劝他修仙'},
        ).json()
        source_chapter = self.client.get(
            f'/api/v1/projects/{self.project_id}/source-chapters?source_import_id={source_import["id"]}'
        ).json()[0]
        chapter = self.client.post(
            f'/api/v1/projects/{self.project_id}/chapters',
            json={'sequence': 1, 'title': '开端', 'source_chapter_id': source_chapter['id']},
        ).json()

        with Session(engine) as session:
            prompt = ContextAssemblyService(session).render_context_prompt(
                ContextAssemblyService(session).build_chapter_context(self.project_id, chapter['id'])
            )

        self.assertIn('【原文章节上下文】', prompt)
        self.assertIn('许闲拒绝吃苦', prompt)
        self.assertIn('原文章节标题：第1章 开端', prompt)


if __name__ == '__main__':
    unittest.main()
