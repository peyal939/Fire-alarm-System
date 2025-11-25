from django.test import TestCase, Client

class LoginStructureTest(TestCase):
    def test_login_page_structure(self):
        client = Client()
        response = client.get('/login/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check for key elements that were missing/misplaced
        self.assertIn('id="loginResendForm"', content)
        self.assertIn('id="forgotPasswordFlow"', content)
        self.assertIn('id="registerPane"', content)
        
        # Check that registerPane is NOT nested inside loginOtpStep
        # This is a simple string check, but effective enough for this specific regression
        otp_step_index = content.find('id="loginOtpStep"')
        forgot_flow_index = content.find('id="forgotPasswordFlow"')
        register_pane_index = content.find('id="registerPane"')
        
        # forgotPasswordFlow should be AFTER loginOtpStep
        self.assertLess(otp_step_index, forgot_flow_index)
        
        # registerPane should be AFTER forgotPasswordFlow (and outside loginFlow)
        self.assertLess(forgot_flow_index, register_pane_index)
