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
            project=SimpleNamespace(name="Test project", tags=""),
            name="Test task",
            tags="",
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

    def test_task_tag_selects_webhook_url_before_project_tag(self):
        task_id = uuid.uuid4()
        task = SimpleNamespace(
            id=task_id,
            project_id=12,
            project=SimpleNamespace(
                name="Test project",
                tags="webhook:other",
            ),
            name="Test task",
            tags="webhook:test",
            status=status_codes.COMPLETED,
            processing_time=1234,
            created_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            available_assets=[],
        )
        routes = {
            "webhook:test": "http://example.test:8890/webhook",
            "webhook:other": "http://example.test:8891/webhook",
        }

        with patch.object(signals, "get_current_plugin", return_value=object()), \
                patch.object(signals.config, "WEBHOOK_ENABLED", True), \
                patch.object(signals.config, "WEBHOOK_URLS_BY_TAG", routes), \
                patch.object(signals.Task.objects, "select_related") as select_related, \
                patch.object(signals, "run_function_async") as run_function_async:
            select_related.return_value.get.return_value = task

            signals.handle_task_completed(Task, task_id)

        self.assertEqual(
            run_function_async.call_args.args[1],
            "http://example.test:8890/webhook",
        )

    def test_configured_tag_without_url_does_not_fall_back(self):
        task_id = uuid.uuid4()
        task = SimpleNamespace(
            id=task_id,
            project=SimpleNamespace(tags=""),
            tags="webhook:test",
        )

        with patch.object(signals, "get_current_plugin", return_value=object()), \
                patch.object(signals.config, "WEBHOOK_ENABLED", True), \
                patch.object(signals.config, "WEBHOOK_URL", "http://example.test/default"), \
                patch.object(
                    signals.config,
                    "WEBHOOK_URLS_BY_TAG",
                    {"webhook:test": None},
                ), \
                patch.object(signals.Task.objects, "select_related") as select_related, \
                patch.object(signals, "run_function_async") as run_function_async:
            select_related.return_value.get.return_value = task

            signals.handle_task_completed(Task, task_id)

        run_function_async.assert_not_called()

    def test_project_tag_selects_webhook_url(self):
        task = SimpleNamespace(
            project=SimpleNamespace(tags="webhook:test"),
            tags="",
        )
        routes = {
            "webhook:test": "http://example.test:8890/webhook",
        }

        with patch.object(signals.config, "WEBHOOK_URLS_BY_TAG", routes):
            webhook_url, route_tag = signals.get_webhook_route(task)

        self.assertEqual(webhook_url, "http://example.test:8890/webhook")
        self.assertEqual(route_tag, "webhook:test")

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
