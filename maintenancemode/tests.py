import re
import os.path

from django.conf import settings
from django.core import management
from django.http import HttpResponse
from django.utils.six import StringIO
from django.contrib.auth.models import User
from django.template import TemplateDoesNotExist

from django.test import TestCase
from django.test.client import Client

try:
    from django.conf.urls import patterns, url
except ImportError:  # django < 1.4
    from django.conf.urls.defaults import patterns, url

from maintenancemode import utils
from maintenancemode import middleware as mw

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

TEMPLATE_DIRS = [
    os.path.join(PROJECT_ROOT, 'test_templates'),
]

# This file acts as a urlconf
urlpatterns = patterns('',
    url('^$', lambda r: HttpResponse('Rendered response page'), name='test'),
    url('^ignored/$', lambda r: HttpResponse('Rendered response page'), name='test'),
)


class MaintenanceModeMiddlewareTestCase(TestCase):
    urls = 'maintenancemode.tests'

    def setUp(self):
        # Reset config options adapted in the individual tests
        self.old_MAINTENANCE_MODE = getattr(settings, 'MAINTENANCE_MODE', False)
        settings.MAINTENANCE_MODE = False
        utils.deactivate()  # make sure maintenance mode is off

        settings.TEMPLATE_DIRS = ()
        settings.INTERNAL_IPS = ()

        self.user = User.objects.create_user(
            username='maintenance', email='maintenance@example.org', password='password')

    def tearDown(self):
        self.user.delete()
        settings.MAINTENANCE_MODE = self.old_MAINTENANCE_MODE
        
    def test_default_middleware(self):
        # Middleware should default to being disabled
        response = self.client.get('/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_disabled_middleware(self):
        # Explicitly disabling the ``MAINTENANCE_MODE`` should work
        with self.settings(MAINTENANCE_MODE=False):
            response = self.client.get('/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_enabled_middleware_without_template(self):
        # Enabling the middleware without a proper 503 template should
        # raise a template error
        with self.settings(MAINTENANCE_MODE=True):
            self.assertRaises(TemplateDoesNotExist, self.client.get, '/')

    def test_enabled_middleware_with_template(self):
        # Enabling the middleware having a ``503.html`` in any of the
        # template locations should return the rendered template"
        with self.settings(MAINTENANCE_MODE=True, TEMPLATE_DIRS=TEMPLATE_DIRS):
            response = self.client.get('/')
        self.assertContains(response, text='Temporary unavailable', count=1, status_code=503)
        self.assertContains(response, text='You requested: /', count=1, status_code=503)

    def test_middleware_with_non_staff_user(self):
        # A logged in user that is not a staff user should see the 503 message
        self.client.login(username='maintenance', password='password')

        with self.settings(MAINTENANCE_MODE=True, TEMPLATE_DIRS=TEMPLATE_DIRS):
            response = self.client.get('/')
        self.assertContains(response, text='Temporary unavailable', count=1, status_code=503)

    def test_middleware_with_staff_user(self):
        # A logged in user that _is_ a staff user should be able to
        # use the site normally
        User.objects.filter(pk=self.user.pk).update(is_staff=True)

        self.client.login(username='maintenance', password='password')

        with self.settings(MAINTENANCE_MODE=True, TEMPLATE_DIRS=TEMPLATE_DIRS):
            response = self.client.get('/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_middleware_with_internal_ips(self):
        # A user that visits the site from an IP in ``INTERNAL_IPS``
        # should be able to use the site normally

        # Use a new Client instance to be able to set the REMOTE_ADDR used by INTERNAL_IPS
        client = Client(REMOTE_ADDR='127.0.0.1')

        with self.settings(MAINTENANCE_MODE=True, INTERNAL_IPS=('127.0.0.1', )):
            response = client.get('/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_middleware_with_internal_ips_range(self):
        client = Client(REMOTE_ADDR='10.10.10.1')

        with self.settings(MAINTENANCE_MODE=True, INTERNAL_IPS=('10.10.10.0/24', )):
            response = client.get('/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_ignored_path(self):
        # A path is ignored when applying the maintanance mode and
        # should be reachable normally
        with self.settings(MAINTENANCE_MODE=True, TEMPLATE_DIRS=TEMPLATE_DIRS):
            with self.settings(IGNORE_URLS=(re.compile(r'^/ignored.*'),)):
                response = self.client.get('/ignored/')
        self.assertContains(response, text='Rendered response page', count=1, status_code=200)

    def test_management_command(self):
        out = StringIO()
        # Explicitly disabling the ``MAINTENANCE_MODE``
        with self.settings(MAINTENANCE_MODE=False):
            management.call_command('maintenance', 'on', stdout=out)
            self.assertRaises(TemplateDoesNotExist, self.client.get, '/')

            management.call_command('maintenance', 'off', stdout=out)
            self.assertContains(self.client.get('/'), text='Rendered response page', count=1, status_code=200)
