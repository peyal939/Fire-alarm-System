from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from devices.models import Device
from products.models import Order, Package
from unittest.mock import patch
from otp.models import PhoneOTP

User = get_user_model()

class CompanyAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company_admin = User.objects.create_user(
            email="admin@company.com",
            password="password123",
            role="company_admin",
            phone_number="+8801711111111"
        )
        # Force role update because create_user resets it
        self.company_admin.role = "company_admin"
        self.company_admin.save()
        self.user = User.objects.create_user(
            email="user@company.com",
            password="password123",
            role="user",
            phone_number="+8801722222222"
        )
        self.device = Device.objects.create(
            hardware_identifier="TEST_DEVICE_001",
            user=self.company_admin,
            device_role="master"
        )
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=100,
            mrf=10
        )
        # Link device to an order by company admin
        self.order = Order.objects.create(
            user=self.company_admin,
            package=self.package,
            quantity=1,
            amount=100
        )
        self.device.originating_order = self.order
        self.device.save()

    def test_company_admin_can_delegate_device(self):
        self.client.force_authenticate(user=self.company_admin)
        url = f"/devices/{self.device.id}/delegate_access/"
        data = {"phone_number": "01722222222"} # Normalized in serializer
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.user, self.user)

    def test_company_admin_can_see_delegated_device(self):
        # Delegate first
        self.device.user = self.user
        self.device.save()
        
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get("/devices/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check if device is in the list
        # The response structure depends on pagination. Assuming standard DRF pagination.
        results = response.data['results'] if 'results' in response.data else response.data
        device_ids = [d['id'] for d in results]
        self.assertIn(self.device.id, device_ids)

    def test_regular_user_cannot_delegate(self):
        self.client.force_authenticate(user=self.user)
        url = f"/devices/{self.device.id}/delegate_access/"
        data = {"phone_number": "01711111111"}
        
        response = self.client.post(url, data)
        # Expect 404 because regular user cannot see the device owned by company admin
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delegate_to_non_existent_user(self):
        self.client.force_authenticate(user=self.company_admin)
        url = f"/devices/{self.device.id}/delegate_access/"
        data = {"phone_number": "01799999999"}
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_registration_with_role(self):
        # Test init
        url_init = "/auth/register/init"
        data_init = {
            "email": "newadmin@company.com",
            "phone_number": "01733333333",
            "password": "Password123",
            "confirm_password": "Password123",
            "role": "company_admin"
        }
        # Mock OTP sending to avoid external calls
        with patch("notifications.sms.SMSClient.send_text") as mock_send:
             response = self.client.post(url_init, data_init)
             self.assertEqual(response.status_code, status.HTTP_201_CREATED)
             session_id = response.data['session_id']

        # Manually set OTP code
        otp_session = PhoneOTP.objects.get(session_id=session_id)
        otp_session.set_code("123456")
        otp_session.save()
        
        url_verify = "/auth/register/verify"
        data_verify = {
            "session_id": session_id,
            "code": "123456"
        }
        response = self.client.post(url_verify, data_verify)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        new_user = User.objects.get(email="newadmin@company.com")
        self.assertEqual(new_user.role, "company_admin")
