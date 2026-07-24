import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from nodeodm import status_codes

from app.models import Task
from coreplugins.taskwebhook import signals


class TestTaskWebhook(SimpleTestCase):
    def test_failed_task_queues_webhook_with_error(self):
        task_id = uuid.uuid4()
        task = SimpleNamespace(
            id=task_id,
            project_id=12,
            project=SimpleNamespace(name="Test project"),
            name="Test task",
            status=status_codes.FAILED,
            processing_time=1234,
            created_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            available_assets=[],
            last_error="Invalid zip file",
        )

        with patch.object(signals, "get_current_plugin", return_value=object()), \
                patch.object(signals.config, "WEBHOOK_ENABLED", True), \
                patch.object(signals.config, "WEBHOOK_URL", "http://example.test/webhook"), \
                patch.object(signals.Task.objects, "select_related") as select_related, \
                patch.object(signals, "run_function_async") as run_function_async:
            select_related.return_value.get.return_value = task

            signals.handle_task_failed(Task, task_id)

        payload = run_function_async.call_args.args[3]
        self.assertEqual(payload["event"], "task.failed")
        self.assertEqual(payload["task"]["status"], status_codes.FAILED)
        self.assertEqual(payload["task"]["last_error"], "Invalid zip file")
        self.assertEqual(payload["task"]["id"], str(task_id))

    def test_set_failure_emits_task_failed_signal(self):
        task_id = uuid.uuid4()
        task = Task(id=task_id)

        with patch.object(task, "save") as save, \
                patch("app.plugins.signals.task_failed.send_robust") as send_robust:
            task.set_failure("Download failed")

        self.assertEqual(task.status, status_codes.FAILED)
        self.assertEqual(task.last_error, "Download failed")
        save.assert_called_once_with()
        send_robust.assert_called_once_with(sender=Task, task_id=task_id)
