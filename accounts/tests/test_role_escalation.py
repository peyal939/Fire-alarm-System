from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


User = get_user_model()


class RoleEscalationPreventionTests(APITestCase):
    def test_api_register_cannot_set_superadmin_or_staff(self):
        # Try to escalate via payload fields (which register ignores anyway)
        r = self.client.post(
            "/auth/register",
            {
                "email": "elevate@example.com",
                "password": "Passw0rd!",
                "role": "superadmin",
                "is_staff": True,
                "is_superuser": True,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(email="elevate@example.com")
        self.assertEqual(u.role, getattr(User.Role, "USER", "user"))
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)
