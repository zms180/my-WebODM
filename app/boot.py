import os
import sys

import kombu
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User, Group
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.core.files import File
from django.db.utils import ProgrammingError
from guardian.shortcuts import assign_perm

from worker import tasks as worker_tasks
from app.models import Preset
from app.models import Theme
from app.plugins import init_plugins
from nodeodm.models import ProcessingNode
# noinspection PyUnresolvedReferencesapp/boot.py#L20
from webodm.settings import MEDIA_ROOT
from . import signals
import logging
from .models import Task, Setting
from webodm import settings
from webodm.wsgi import booted


def get_default_logo_path():
    logo_path = settings.APP_DEFAULT_LOGO
    if os.path.isfile(logo_path):
        return logo_path

    logger = logging.getLogger('app.logger')
    logger.error("Default logo path is not a file: %s", logo_path)
    fallback_logo_path = os.path.join('app', 'static', 'app', 'img', 'logo512.png')
    if os.path.isfile(fallback_logo_path):
        logger.warning("Using fallback default logo: %s", fallback_logo_path)
        return fallback_logo_path

    return None


def _logo_matches(logo_name, ref_name):
    # Matches exact name or Django-renamed variant (e.g. logo512_TFAz34Z.png matches logo512.png)
    stem = os.path.splitext(ref_name)[0]
    return logo_name == ref_name or logo_name.startswith(stem + '_')


def update_legacy_branding(setting):
    logo_name = os.path.basename(setting.app_logo.name)
    default_logo_name = os.path.basename(settings.APP_DEFAULT_LOGO)
    legacy_brand_names = ("智绘",)
    legacy_brand_logo_names = ("zhuihui-logo.png", "logo512.png")
    uses_official_default = setting.app_name == "WebODM" and _logo_matches(logo_name, "logo512.png")
    uses_current_brand_default = setting.app_name == settings.APP_NAME and _logo_matches(logo_name, default_logo_name)
    uses_previous_brand_default = (
        (setting.app_name in legacy_brand_names and
         any(_logo_matches(logo_name, n) for n in legacy_brand_logo_names + (default_logo_name,))) or (
        setting.app_name == settings.APP_NAME and any(_logo_matches(logo_name, n) for n in legacy_brand_logo_names)))
    if not (uses_official_default or uses_current_brand_default or uses_previous_brand_default):
        return False

    if setting.app_name in ("WebODM",) + legacy_brand_names:
        setting.app_name = settings.APP_NAME
        if setting.organization_name in ("WebODM",) + legacy_brand_names:
            setting.organization_name = settings.APP_NAME
        if setting.organization_website == "https://github.com/WebODM/WebODM/":
            setting.organization_website = ""

    logo_path = os.path.join(settings.MEDIA_ROOT, setting.app_logo.name)
    if (uses_current_brand_default or uses_previous_brand_default or
            logo_name != default_logo_name or not os.path.isfile(logo_path)):
        default_logo_path = get_default_logo_path()
        if default_logo_path is None:
            return False

        default_media_logo_name = setting.app_logo.field.generate_filename(
            setting, default_logo_name)
        if (setting.app_logo.name != default_media_logo_name or uses_current_brand_default) and \
                setting.app_logo.storage.exists(default_media_logo_name):
            setting.app_logo.storage.delete(default_media_logo_name)

        with open(default_logo_path, 'rb') as default_logo_file:
            setting.app_logo.save(
                os.path.basename(default_logo_path),
                File(default_logo_file),
                save=False)
    setting.save()
    return True


def boot():
    # booted is a shared memory variable to keep track of boot status
    # as multiple gunicorn workers could trigger the boot sequence twice
    if (not settings.DEBUG and booted.value) or settings.MIGRATING or settings.FLUSHING: return

    booted.value = True
    logger = logging.getLogger('app.logger')

    logger.info("Booting WebODM {}".format(settings.VERSION))

    if settings.DEBUG:
        logger.warning("Debug mode is ON (for development this is OK)")

    # Silence django's "Warning: Session data corrupted" messages
    session_logger = logging.getLogger("django.SuspiciousOperation.SuspiciousSession")
    session_logger.disabled = True

    # Make sure our app/media/tmp folder exists
    if not os.path.exists(settings.MEDIA_TMP):
        os.makedirs(settings.MEDIA_TMP)

    # Check default group
    try:
        default_group, created = Group.objects.get_or_create(name='Default')
        if created:
            logger.info("Created default group")

            # Assign viewprocessing node object permission to default processing node (if present)
            # Otherwise non-root users will not be able to process
            try:
                pnode = ProcessingNode.objects.get(hostname="node-odx-1")
                assign_perm('view_processingnode', default_group, pnode)
                logger.info("Added view_processingnode permissions to default group")
            except ObjectDoesNotExist:
                pass


        # Add default permissions (view_project, change_project, delete_project, etc.)
        for permission in ('_project', '_task', '_preset'):
            default_group.permissions.add(
                *list(Permission.objects.filter(codename__endswith=permission))
            )

        # Add permission to view processing nodes
        default_group.permissions.add(Permission.objects.get(codename="view_processingnode"))

        add_default_presets()

        # Add settings
        default_theme, created = Theme.objects.get_or_create(name='Default')
        if created:
            logger.info("Created default theme")

            if settings.DEFAULT_THEME_CSS:
                default_theme.css = settings.DEFAULT_THEME_CSS
                default_theme.save()

        if not Setting.objects.exists():
            s = Setting.objects.create(
                    app_name=settings.APP_NAME,
                    organization_name=settings.APP_NAME,
                    organization_website="",
                    theme=default_theme)
            default_logo_path = get_default_logo_path()
            if default_logo_path is not None:
                with open(default_logo_path, 'rb') as default_logo_file:
                    s.app_logo.save(os.path.basename(default_logo_path), File(default_logo_file))
            else:
                logger.error("Created settings without a default logo")

            logger.info("Created settings")
        elif update_legacy_branding(Setting.objects.get()):
            logger.info("Updated default branding")
        
        init_plugins()

        if not settings.TESTING:
            try:
                worker_tasks.update_nodes_info.delay()
            except kombu.exceptions.OperationalError as e:
                logger.error("Cannot connect to celery broker at {}. Make sure that your redis-server is running at that address: {}".format(settings.CELERY_BROKER_URL, str(e)))


    except ProgrammingError:
        logger.warning("Could not touch the database. If running a migration, this is expected.")


def add_default_presets():
    try:
        Preset.objects.update_or_create(name='Multispectral', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'radiometric-calibration', 'value': 'camera'}]})
        Preset.objects.update_or_create(name='Volume Analysis', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dem-resolution', 'value': '2'},
                                                              {'name': 'pc-quality', 'value': 'high'}]})
        Preset.objects.update_or_create(name='3D Model', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'mesh-octree-depth', 'value': "12"},
                                                              {'name': 'use-3dmesh', 'value': True},
                                                              {'name': 'pc-quality', 'value': 'high'},
                                                              {'name': 'mesh-size', 'value': '300000'}]})
        Preset.objects.update_or_create(name='Buildings', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'mesh-size', 'value': '300000'},
                                                              {'name': 'feature-quality', 'value': 'high'},
                                                              {'name': 'pc-quality', 'value': 'high'}]})
        Preset.objects.update_or_create(name='Forest', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'min-num-features', 'value': '18000'},
                                                              {'name': 'use-3dmesh', 'value': True},
                                                              {'name': 'feature-quality', 'value': 'medium'}]})
        Preset.objects.update_or_create(name='DSM + DTM', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dtm', 'value': True}]})
        Preset.objects.update_or_create(name='Field', system=True,
                                        defaults={'options': [{'name': 'sfm-algorithm', 'value': 'planar'},
                                                              {'name': 'fast-orthophoto', 'value': True},
                                                              {'name': 'matcher-neighbors', 'value': 4}]})
        Preset.objects.update_or_create(name='Fast Orthophoto', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'fast-orthophoto', 'value': True}]})
        Preset.objects.update_or_create(name='High Resolution', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dem-resolution', 'value': "1.0"},
                                                              {'name': 'orthophoto-resolution', 'value': "1.0"}]})
        Preset.objects.update_or_create(name='Default', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True}]})

    except MultipleObjectsReturned:
        # Mostly to handle a legacy code problem where
        # multiple system presets with the same name were
        # created if we changed the options
        Preset.objects.filter(system=True).delete()
        add_default_presets()
