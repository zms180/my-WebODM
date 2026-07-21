import logging
import uuid

from django.dispatch import receiver
from django.utils import timezone

from app.models import Task
from app.plugins.functions import get_current_plugin
from app.plugins.signals import task_completed
from app.plugins.worker import run_function_async

from . import config
from .delivery import deliver_webhook


logger = logging.getLogger("app.logger")


@receiver(task_completed, dispatch_uid="taskwebhook_task_completed")
def handle_task_completed(sender, task_id, **kwargs):
    if get_current_plugin(only_active=True) is None:
        return

    if not config.WEBHOOK_ENABLED or not config.WEBHOOK_URL:
        logger.info("TaskWebhook: delivery is disabled")
        return

    try:
        task = Task.objects.select_related("project").get(id=task_id)
        event_id = str(uuid.uuid4())
        payload = {
            "payload_version": 1,
            "event": "task.completed",
            "event_id": event_id,
            "sent_at": timezone.now().isoformat(),
            "task": {
                "id": str(task.id),
                "project_id": task.project_id,
                "project_name": task.project.name,
                "name": task.name or "",
                "status": task.status,
                "processing_time": task.processing_time,
                "created_at": task.created_at.isoformat(),
                "available_assets": list(task.available_assets or []),
                "api_path": "/api/projects/{}/tasks/{}/".format(
                    task.project_id,
                    task.id,
                ),
            },
        }

        run_function_async(
            deliver_webhook,
            config.WEBHOOK_URL,
            config.WEBHOOK_SECRET,
            payload,
            config.WEBHOOK_CONNECT_TIMEOUT,
            config.WEBHOOK_READ_TIMEOUT,
            config.WEBHOOK_MAX_ATTEMPTS,
            config.WEBHOOK_RETRY_BASE_SECONDS,
        )
        logger.info(
            "TaskWebhook: queued event %s for task %s",
            event_id,
            task.id,
        )
    except Task.DoesNotExist:
        logger.warning("TaskWebhook: task %s no longer exists", task_id)
    except Exception:
        logger.exception("TaskWebhook: could not queue task %s", task_id)
