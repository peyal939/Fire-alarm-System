from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from otp.models import PhoneOTP

User = get_user_model()


class AuthFlowTests(APITestCase):
    def test_register_login_me(self):
        resp = self.client.post(
            "/auth/register",
            {
                "email": "u1@example.com",
                "password": "Passw0rd!",
                "phone_number": "0123456789",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        resp = self.client.post(
            "/auth/login",
            {"email": "u1@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        session_id = resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        session.set_code("654321")
        session.save(update_fields=["code_hash"])
        verify = self.client.post(
            "/auth/login/verify",
            {"session_id": session_id, "code": "654321"},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        access = verify.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.get("/auth/me")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["email"], "u1@example.com")


class RegistrationOTPTests(APITestCase):
    def setUp(self):
        self.payload = {
            "email": "otpuser@example.com",
            "phone_number": "01700000000",
            "password": "Passw0rd!",
            "confirm_password": "Passw0rd!",
            "full_name": "OTP User",
        }

    def _force_code(self, session, code="123456"):
        session.set_code(code)
        session.save(update_fields=["code_hash"])
        return code

    def test_full_registration_flow(self):
        init_resp = self.client.post("/auth/register/init", self.payload, format="json")
        self.assertEqual(init_resp.status_code, status.HTTP_201_CREATED)
        session_id = init_resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        code = self._force_code(session)

        verify_resp = self.client.post(
            "/auth/register/verify",
            {"session_id": session_id, "code": code},
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", verify_resp.data)
        self.assertEqual(
            verify_resp.data["user"]["email"], self.payload["email"].lower()
        )

    def test_reject_invalid_code(self):
        init_resp = self.client.post("/auth/register/init", self.payload, format="json")
        self.assertEqual(init_resp.status_code, status.HTTP_201_CREATED)
        session_id = init_resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        self._force_code(session, code="999999")

        verify_resp = self.client.post(
            "/auth/register/verify",
            {"session_id": session_id, "code": "000000"},
            format="json",
        )
        self.assertEqual(verify_resp.status_code, status.HTTP_400_BAD_REQUEST)


class LoginOTPTests(APITestCase):
    def setUp(self):
        self.email = "loginotp@example.com"
        self.password = "Passw0rd!"
        resp = self.client.post(
            "/auth/register",
            {
                "email": self.email,
                "password": self.password,
                "phone_number": "+8801700000000",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def _get_session(self):
        resp = self.client.post(
            "/auth/login",
            {"email": self.email, "password": self.password},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        session_id = resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        session.set_code("111222")
        session.save(update_fields=["code_hash"])
        return session_id

    def test_login_with_phone_number_identifier(self):
        resp = self.client.post(
            "/auth/login",
            {"phone_number": "+8801700000000", "password": self.password},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        session_id = resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        session.set_code("222333")
        session.save(update_fields=["code_hash"])
        verify = self.client.post(
            "/auth/login/verify",
            {"session_id": session_id, "code": "222333"},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)

    def test_login_with_phone_without_country_code(self):
        resp = self.client.post(
            "/auth/login",
            {"phone_number": "01700000000", "password": self.password},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        session_id = resp.data["session_id"]
        session = PhoneOTP.objects.get(session_id=session_id)
        session.set_code("333444")
        session.save(update_fields=["code_hash"])
        verify = self.client.post(
            "/auth/login/verify",
            {"session_id": session_id, "code": "333444"},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)

    def test_login_success(self):
        session_id = self._get_session()
        verify = self.client.post(
            "/auth/login/verify",
            {"session_id": session_id, "code": "111222"},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        self.assertIn("access", verify.data)

    def test_login_wrong_code(self):
        session_id = self._get_session()
        verify = self.client.post(
            "/auth/login/verify",
            {"session_id": session_id, "code": "000000"},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_400_BAD_REQUEST)


class PasswordResetFlowTests(APITestCase):
    def setUp(self):
        self.email = "forgot@example.com"
        self.phone_number = "+8801700000000"
        resp = self.client.post(
            "/auth/register",
            {
                "email": self.email,
                "password": "OldPassw0rd!",
                "phone_number": self.phone_number,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        self.user = User.objects.get(email=self.email)

    def _initiate_reset(self, identifier):
        resp = self.client.post(
            "/auth/password/forgot/init",
            {"identifier": identifier},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        return resp.data["session_id"]

    def _set_code(self, session_id, code="456789"):
        session = PhoneOTP.objects.get(session_id=session_id)
        session.set_code(code)
        session.save(update_fields=["code_hash"])
        return code

    def _complete_reset(self, session_id, code, new_password="N3wPass!23"):
        resp = self.client.post(
            "/auth/password/forgot/complete",
            {
                "session_id": session_id,
                "code": code,
                "new_password": new_password,
                "confirm_password": new_password,
            },
            format="json",
        )
        return resp

    def test_reset_password_with_email_identifier(self):
        session_id = self._initiate_reset(self.email.upper())
        code = self._set_code(session_id)
        resp = self._complete_reset(session_id, code)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("N3wPass!23"))

    def test_reset_password_with_local_phone_identifier(self):
        session_id = self._initiate_reset("01700000000")
        code = self._set_code(session_id, code="112233")
        resp = self._complete_reset(session_id, code, new_password="AnotherP@ss1")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("AnotherP@ss1"))
