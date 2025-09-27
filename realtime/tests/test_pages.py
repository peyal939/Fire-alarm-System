from django.contrib.auth import get_user_model
from django.test import TestCase


User = get_user_model()


class PageRenderTests(TestCase):
    def setUp(self):
        self.password = "Passw0rd!"
        self.user = User.objects.create_user(
            email="user@example.com",
            password=self.password,
        )
        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password=self.password,
        )

    def test_login_required_redirects_on_root(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/login/"))
        # Ensure the redirect includes next=/ (normalize encoded slashes first)
        self.assertIn("next=/", resp.url.replace("%2F", "/"))

    def test_pages_render_for_authenticated_user(self):
        self.client.login(username=self.user.email, password=self.password)
        ok_urls = [
            "/",
            "/app/dashboard/",
            "/app/devices/",
            "/app/telemetry/",
            "/app/alerts/",
            "/app/products/",
        ]
        for u in ok_urls:
            with self.subTest(url=u):
                r = self.client.get(u)
                self.assertEqual(
                    r.status_code, 200, msg=f"GET {u} failed: {r.status_code}"
                )

    def test_admin_panel_forbidden_for_non_superadmin(self):
        self.client.login(username=self.user.email, password=self.password)
        r = self.client.get("/app/admin-panel/")
        self.assertEqual(r.status_code, 403)

    def test_admin_panel_renders_for_superadmin(self):
        self.client.login(username=self.superuser.email, password=self.password)
        r = self.client.get("/app/admin-panel/")
        self.assertEqual(r.status_code, 200)
