import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.core.database import engine, init_db
from app.models.models import Project, Task
from app.services.task_dispatch import RECOVERABLE_TASK_TYPES, recover_interrupted_tasks, run_task


class TaskRecoveryTest(unittest.TestCase):
    def setUp(self):
        init_db()
        with Session(engine) as session:
            project = Project(title="recovery test")
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project_id = project.id

    def create_task(self, task_type, status="processing", input_payload=None):
        with Session(engine) as session:
            task = Task(
                type=task_type,
                status=status,
                project_id=self.project_id,
                name="test task",
                input_payload=input_payload,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task.id

    def get_task(self, task_id):
        with Session(engine) as session:
            return session.get(Task, task_id)

    def test_recoverable_task_is_requeued_and_rerun(self):
        task_id = self.create_task(
            "chapter_content_generation",
            status="processing",
            input_payload={"chapter_id": 1, "user_input": ""},
        )
        executed = []

        def fake_run(run_id, run_type, payload=None):
            executed.append((run_id, run_type, payload))

        # 测试共用数据库中可能残留其他 pending 任务，只断言目标任务被执行
        with patch("app.services.task_dispatch.run_task", side_effect=fake_run):
            recover_interrupted_tasks()
            deadline = time.time() + 5
            while not any(item[0] == task_id for item in executed) and time.time() < deadline:
                time.sleep(0.05)

        matched = [item for item in executed if item[0] == task_id]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][1], "chapter_content_generation")
        task = self.get_task(task_id)
        self.assertEqual(task.status, "pending")
        self.assertIn("重新排队", task.message)

    def test_unrecoverable_task_is_marked_failed(self):
        # 无 input_payload 的旧任务无法重建执行参数
        task_id = self.create_task("image_generation", status="processing", input_payload=None)

        with patch("app.services.task_dispatch.run_task"):
            recover_interrupted_tasks()

        task = self.get_task(task_id)
        self.assertEqual(task.status, "failed")
        self.assertIn("无法自动恢复", task.message)

    def test_terminal_tasks_are_untouched(self):
        task_id = self.create_task("chapter_storyboard", status="completed", input_payload={"chapter_id": 1})

        with patch("app.services.task_dispatch.run_task"):
            recover_interrupted_tasks()

        task = self.get_task(task_id)
        self.assertEqual(task.status, "completed")

    def test_run_task_routes_by_payload_variant(self):
        calls = []
        with patch("app.routers.generation.generate_panel_task", lambda tid, item_id: calls.append(("panel", item_id))), \
             patch("app.routers.generation.generate_all_images_task", lambda tid, pid: calls.append(("all", pid))):
            run_task("t1", "image_generation", {"item_id": 5, "project_id": "p"})
            run_task("t2", "image_generation", {"project_id": "p"})
        self.assertEqual(calls, [("panel", 5), ("all", "p")])

    def test_run_task_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            run_task("t1", "unknown_type", {})

    def test_recoverable_types_cover_all_dispatchable_types(self):
        self.assertEqual(
            RECOVERABLE_TASK_TYPES,
            {
                "project_initialization",
                "source_analysis",
                "source_project_initialization",
                "chapter_content_generation",
                "chapter_storyboard",
                "storyboard",
                "image_generation",
                "character_generation",
            },
        )


if __name__ == "__main__":
    unittest.main()
