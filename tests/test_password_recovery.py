import hashlib
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from werkzeug.security import generate_password_hash, check_password_hash
from app import create_app
from app.extensions import db
from app.models import User, PasswordResetToken, utc_now
from app.password_security import issue_password_reset, allow_request, consume_reset, reset_user_for_token, trusted_reset_url


class PasswordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'a'*40,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'WTF_CSRF_ENABLED': False,
            'PORTAL_BASE_URL': 'https://help.example.com'})
        self.client = self.app.test_client()
        with self.app.app_context():
            user = User(name='Member', email='member@example.com', active=True,
                must_change_password=False, password_hash=generate_password_hash('OldPassword123!'))
            db.session.add(user); db.session.commit(); self.uid = user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove(); db.drop_all()

    def issue(self):
        with self.app.app_context(), patch('app.email_service.send_password_reset_email', return_value=True) as send:
            issue_password_reset('member@example.com')
            link = send.call_args.args[1]
            self.assertTrue(link.startswith('https://help.example.com/reset-password#token='))
            return parse_qs(urlsplit(link).fragment)['token'][0]

    def reset(self, token, password='NewPassword456!'):
        with patch('app.auth.submit_account_email'):
            return self.client.post('/reset-password', data={'reset_token': token,
                'new_password': password, 'confirm_password': password}, follow_redirects=True)

    def test_known_unknown_and_inactive_requests_have_identical_response(self):
        with self.app.app_context():
            db.session.add(User(name='Disabled', email='disabled@example.com', active=False,
                password_hash=generate_password_hash('OldPassword123!'))); db.session.commit()
        responses=[]
        with patch('app.auth.submit_account_email') as queue:
            for email in ['member@example.com', 'unknown@example.com', 'disabled@example.com']:
                c=self.app.test_client()
                responses.append(c.post('/forgot-password', data={'email':email}, follow_redirects=True).data)
            self.assertEqual(queue.call_count,3)
        self.assertEqual(responses[0],responses[1]); self.assertEqual(responses[0],responses[2])
        with self.app.app_context(), patch('app.email_service.send_password_reset_email') as mail:
            issue_password_reset('unknown@example.com'); issue_password_reset('disabled@example.com')
            mail.assert_not_called()

    def test_invalid_email_and_csrf_cannot_queue_mail(self):
        with patch('app.auth.submit_account_email') as queue:
            self.client.post('/forgot-password',data={'email':'not-an-email'})
            queue.assert_not_called()
            self.app.config['WTF_CSRF_ENABLED']=True
            self.assertEqual(self.client.post('/forgot-password',data={'email':'member@example.com'}).status_code,400)
            self.assertEqual(self.client.post('/reset-password',data={'reset_token':'a'*43}).status_code,400)
            queue.assert_not_called()

    def test_single_use_invalidates_other_tokens_and_sessions(self):
        old=self.app.test_client()
        old.post('/login',data={'email':'member@example.com','password':'OldPassword123!'})
        token=self.issue(); second=self.issue()
        with self.app.app_context():
            rows=PasswordResetToken.query.all()
            self.assertEqual(len(rows),2)
            self.assertNotIn(token,[r.token_hash for r in rows])
            self.assertEqual(len(rows[0].token_hash),64)
        result=self.reset(token)
        self.assertIn(b'Your password has been reset',result.data)
        self.assertIn('/login',old.get('/').location)
        self.assertIn(b'invalid or has expired',self.reset(token).data)
        self.assertIn(b'invalid or has expired',self.reset(second).data)
        with self.app.app_context():
            self.assertTrue(check_password_hash(db.session.get(User,self.uid).password_hash,'NewPassword456!'))
        login=self.client.post('/login',data={'email':'member@example.com','password':'NewPassword456!'})
        self.assertEqual(login.status_code,302)

    def test_expired_tampered_disabled_and_password_changed_tokens_fail(self):
        token=self.issue()
        self.assertIn(b'invalid or has expired',self.reset('x'+token[1:]).data)
        with self.app.app_context():
            record=db.session.get(PasswordResetToken,hashlib.sha256(token.encode()).hexdigest())
            record.expires_at=utc_now()-timedelta(seconds=1); db.session.commit()
        self.assertIn(b'invalid or has expired',self.reset(token).data)
        token=self.issue()
        with self.app.app_context():
            user=db.session.get(User,self.uid); user.active=False; db.session.commit()
        self.assertIn(b'invalid or has expired',self.reset(token).data)
        with self.app.app_context():
            user=db.session.get(User,self.uid); user.active=True
            user.password_hash=generate_password_hash('ChangedElsewhere123!'); db.session.commit()
        self.assertIn(b'invalid or has expired',self.reset(token).data)

    def test_failed_delivery_removes_token(self):
        with self.app.app_context(), patch('app.email_service.send_password_reset_email',return_value=False):
            issue_password_reset('member@example.com')
            self.assertEqual(PasswordResetToken.query.count(),0)

    def test_throttles_email_and_ip_without_disabling_account(self):
        with patch('app.auth.submit_account_email') as queue:
            for _ in range(5):
                self.client.post('/forgot-password',data={'email':'member@example.com'})
            self.assertEqual(queue.call_count,1)
        with self.app.app_context():
            self.assertTrue(db.session.get(User,self.uid).active)
            self.assertTrue(allow_request('test','ip',2,3600))
            self.assertTrue(allow_request('test','ip',2,3600))
            self.assertFalse(allow_request('test','ip',2,3600))
        with patch('app.auth.submit_account_email') as queue:
            for i in range(25):
                self.client.post('/forgot-password',data={'email':f'new{i}@example.com'})
            self.assertEqual(queue.call_count,15) # 5 prior requests used this IP's budget

    def test_link_uses_configured_origin_and_never_host_header(self):
        with self.app.test_request_context(headers={'Host':'attacker.example','X-Forwarded-Host':'attacker.example'}):
            self.assertTrue(trusted_reset_url('abc').startswith('https://help.example.com/'))
        with self.app.app_context():
            for base in ['http://help.example.com','https://x.example/path','https://u:p@x.example','']:
                self.app.config['PORTAL_BASE_URL']=base
                with self.assertRaises(ValueError): trusted_reset_url('abc')

    def test_get_does_not_consume_token_and_headers_prevent_leaks(self):
        token=self.issue()
        result=self.client.get('/reset-password')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers['Referrer-Policy'],'no-referrer')
        self.assertIn('no-store',result.headers['Cache-Control'])
        with self.app.app_context(): self.assertIsNotNone(reset_user_for_token(token))

    def test_short_mismatch_and_reused_password_rejected(self):
        token=self.issue()
        for password in ['short','OldPassword123!']:
            self.reset(token,password)
            with self.app.app_context(): self.assertIsNotNone(reset_user_for_token(token))
        self.client.post('/reset-password',data={'reset_token':token,'new_password':'NewPassword456!', 'confirm_password':'Different123!'})
        with self.app.app_context(): self.assertIsNotNone(reset_user_for_token(token))

    def test_stale_concurrent_reset_cannot_overwrite_changed_password(self):
        token=self.issue()
        with self.app.app_context():
            user=reset_user_for_token(token)
            old_hash=user.password_hash
            db.session.expunge(user)
            # Emulate another committed password change after token validation.
            from sqlalchemy import update
            db.session.execute(update(User).where(User.id==self.uid).values(
                password_hash=generate_password_hash('WinnerPassword123!')),
                execution_options={'synchronize_session':False})
            db.session.commit()
            self.assertEqual(user.password_hash,old_hash)
            self.assertFalse(consume_reset(token,user,generate_password_hash('LoserPassword123!')))
            self.assertTrue(check_password_hash(db.session.get(User,self.uid).password_hash,'WinnerPassword123!'))

    def test_legacy_sessions_are_rejected(self):
        from app.models import load_user
        with self.app.app_context(): self.assertIsNone(load_user(str(self.uid)))

    def test_recovery_email_requires_encrypted_smtp(self):
        from app.email_service import send_password_reset_email
        with self.app.app_context(), patch.dict(os.environ,{'SMTP_HOST':'smtp.example.com',
            'SMTP_USERNAME':'test', 'SMTP_PASSWORD':'test','SMTP_USE_TLS':'false','SMTP_USE_SSL':'false'}), patch('app.email_service._deliver') as deliver:
            self.assertFalse(send_password_reset_email('member@example.com','https://help.example.com/reset-password'))
            deliver.assert_not_called()

    def test_normal_password_change_keeps_current_session_and_revokes_others(self):
        second=self.app.test_client()
        for c in [self.client,second]:
            c.post('/login',data={'email':'member@example.com','password':'OldPassword123!'})
        token=self.issue()
        with patch('app.auth.submit_account_email') as alert:
            result=self.client.post('/account/password',data={'current_password':'OldPassword123!',
                'new_password':'ChangedPassword123!', 'confirm_password':'ChangedPassword123!'})
            self.assertEqual(result.status_code,302)
            alert.assert_called_once()
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn('/login',second.get('/').location)
        with self.app.app_context(): self.assertIsNone(reset_user_for_token(token))

    def test_admin_reset_preserves_disabled_state_and_sends_notice(self):
        with self.app.app_context():
            user=db.session.get(User,self.uid); user.active=False
            db.session.add(User(name='Admin',email='admin@example.com',role='admin',active=True,
                must_change_password=False,password_hash=generate_password_hash('AdminPassword123!')))
            db.session.commit()
        self.client.post('/login',data={'email':'admin@example.com','password':'AdminPassword123!'})
        with patch('app.password_security.submit_account_email') as alert:
            response=self.client.post(f'/admin/users/{self.uid}/reset-password',data={
                'temporary_password':'TemporaryPassword123!', 'confirm_password':'TemporaryPassword123!'})
            self.assertEqual(response.status_code,302)
            alert.assert_called_once()
        with self.app.app_context():
            user=db.session.get(User,self.uid)
            self.assertFalse(user.active)
            self.assertTrue(user.must_change_password)
