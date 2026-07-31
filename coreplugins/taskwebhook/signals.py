import logging
import uuid

from django.dispatch import receiver
from django.utils import timezone

from app.models import Task
from app.plugins.functions import get_current_plugin
from app.plugins.signals import task_completed, task_failed
from app.plugins.worker import run_function_async

from . import config
from .delivery import deliver_webhook


logger = logging.getLogger("app.logger")


def get_webhook_route(task):
    routes = config.WEBHOOK_URLS_BY_TAG
    task_tags = set((getattr(task, "tags", "") or "").split())
    project_tags = set((getattr(task.project, "tags", "") or "").split())

    for tag, webhook_url in routes.items():
        if tag in task_tags:
            return webhook_url, tag

    for tag, webhook_url in routes.items():
        if tag in project_tags:
            return webhook_url, tag

    return config.WEBHOOK_URL, None


def queue_task_event(task_id, event):
    if get_current_plugin(only_active=True) is None:
        return

    if not config.WEBHOOK_ENABLED:
        logger.info("TaskWebhook: delivery is disabled")
        return

    try:
        task = Task.objects.select_related("project").get(id=task_id)
        webhook_url, route_tag = get_webhook_route(task)
        if not webhook_url:
            logger.warning(
                "TaskWebhook: no URL configured for route %s; task %s was not queued",
                route_tag or "default",
                task.id,
            )
            return

        event_id = str(uuid.uuid4())
        task_payload = {
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
        }
        if event == "task.failed":
            task_payload["last_error"] = task.last_error or ""

        payload = {
            "payload_version": 1,
            "event": event,
            "event_id": event_id,
            "sent_at": timezone.now().isoformat(),
            "task": task_payload,
        }

        run_function_async(
            deliver_webhook,
            webhook_url,
            config.WEBHOOK_SECRET,
            payload,
            config.WEBHOOK_CONNECT_TIMEOUT,
            config.WEBHOOK_READ_TIMEOUT,
            config.WEBHOOK_MAX_ATTEMPTS,
            config.WEBHOOK_RETRY_BASE_SECONDS,
        )
        logger.info(
            "TaskWebhook: queued %s event %s for task %s using route %s",
            event,
            event_id,
            task.id,
            route_tag or "default",
        )
    except Task.DoesNotExist:
        logger.warning("TaskWebhook: task %s no longer exists", task_id)
    except Exception:
        logger.exception("TaskWebhook: could not queue task %s", task_id)


@receiver(task_completed, dispatch_uid="taskwebhook_task_completed")
def handle_task_completed(sender, task_id, **kwargs):
    queue_task_event(task_id, "task.completed")


@receiver(task_failed, dispatch_uid="taskwebhook_task_failed")
def handle_task_failed(sender, task_id, **kwargs):
    queue_task_event(task_id, "task.failed")
