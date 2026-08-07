import os
import time

from django.core.exceptions import ValidationError
from django.core.files import File
from django.test import Client

from app.contexts.settings import load as load_settings
from app.boot import update_legacy_branding
from app.models import Setting
from app.models import Theme
from webodm import settings as webodm_settings
from .classes import BootTestCase

class TestSettings(BootTestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_settings(self):
        c = Client()

        # There should always be a Setting object
        self.assertTrue(Setting.objects.count() == 1, "There's a settings object")

        # There should be "default" Theme object
        self.assertTrue(Theme.objects.filter(name="Default").count() == 1, "Default theme found")

        # The default settings use the default theme
        self.assertTrue(Setting.objects.first().theme.id == Theme.objects.get(name="Default").id, "Default theme is associated to settings")

        # We can create a new theme object
        second_theme = Theme.objects.create(name="Second")

        # We cannot add another setting objects
        with self.assertRaises(ValidationError):
            Setting.objects.create(app_name="Test", theme=second_theme)

        # We can retrieve the settings
        settings = load_settings()['SETTINGS']
        self.assertTrue(settings is not None, "Can retrieve settings")
        self.assertEqual(settings.app_name, "智绘")
        self.assertEqual(os.path.basename(settings.app_logo.name), "zhihui-logo.png")
        self.assertEqual(settings.organization_name, "智绘")
        self.assertEqual(settings.organization_website, "")

        # The default logo has been created in the proper destination
        default_logo_path = os.path.join(webodm_settings.MEDIA_ROOT, settings.app_logo.name)
        self.assertTrue(os.path.exists(default_logo_path), "Default logo exists in MEDIA_ROOT/settings")

        legacy_logo = os.path.join('app', 'static', 'app', 'img', 'logo512.png')
        settings.app_name = "WebODM"
        settings.organization_name = "WebODM"
        settings.organization_website = "https://github.com/WebODM/WebODM/"
        settings.app_logo.save(os.path.basename(legacy_logo), File(open(legacy_logo, 'rb')))
        self.assertTrue(update_legacy_branding(settings))
        settings.refresh_from_db()
        self.assertEqual(settings.app_name, "智绘")
        self.assertEqual(os.path.basename(settings.app_logo.name), "zhihui-logo.png")
        self.assertEqual(settings.organization_name, "智绘")
        self.assertEqual(settings.organization_website, "")

        settings.app_logo.save('zhihui-logo.png', File(open(webodm_settings.APP_DEFAULT_LOGO, 'rb')))
        self.assertTrue(update_legacy_branding(settings))
        settings.refresh_from_db()
        self.assertEqual(os.path.basename(settings.app_logo.name), "zhihui-logo.png")

        # We can update the logo
        logo = os.path.join('app', 'static', 'app', 'img', 'favicon.png')
        settings.app_logo.save(os.path.basename(logo), File(open(logo, 'rb')))
        settings.save()

        # The main logo has been uploaded
        self.assertTrue("favicon" in settings.app_logo.name, "Logo has been updated")
        self.assertTrue(os.path.exists(os.path.join(webodm_settings.MEDIA_ROOT, settings.app_logo.name)),
                        "New logo exists in MEDIA_ROOT/settings")

        # The old logo does not exist anymore
        self.assertFalse(os.path.exists(default_logo_path),
                        "Old logo has been deleted")
