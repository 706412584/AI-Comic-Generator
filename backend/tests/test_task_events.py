import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import engine, init_db
from app.main import app
from app.models.models import Project, Task


class TaskEventsTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        with Session(engine) as session:
            project = Project(title="task events test")
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project_id = project.id

    def test_missing_task_events_returns_404(self):
        response = self.client.get("/api/v1/tasks/not-found/events")
        self.assertEqual(response.status_code, 404)

    def test_completed_task_events_outputs_state_and_done(self):
        with Session(engine) as session:
            task = Task(
                project_id=self.project_id,
                type="source_analysis",
                status="completed",
                progress=100,
                message="已完成",
                logs=["开始", {"step": "完成"}],
                result={"ok": True},
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id

        with self.client.stream("GET", f"/api/v1/tasks/{task_id}/events") as response:
            self.assertEqual(response.status_code, 200)
            body = "".join(response.iter_text())

        self.assertIn("event: task_state", body)
        self.assertIn("event: done", body)
        self.assertIn('"status": "completed"', body)
        self.assertIn('"logs"', body)


if __name__ == "__main__":
    unittest.main()
