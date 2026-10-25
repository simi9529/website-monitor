import base64
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import zlib
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import http_ece
import requests

import web_push


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


class WebPushTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch.dict('os.environ', {}, clear=True))
        web_push.bind_delivery_state({})
        self.receiver = ec.generate_private_key(ec.SECP256R1())
        self.signer = ec.generate_private_key(ec.SECP256R1())
        self.auth = b'test-auth-secret'
        self.subscription = {
            'endpoint': 'https://fcm.googleapis.com/fcm/send/test-endpoint',
            'keys': {'p256dh': b64(self.receiver.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)), 'auth': b64(self.auth)},
        }
        self.config = {
            'VAPID_PRIVATE_KEY': b64(self.signer.private_numbers().private_value.to_bytes(32, 'big')),
            'WEB_PUSH_SUBSCRIPTIONS': json.dumps(self.subscription),
        }

    def test_auto_keeps_email_until_both_push_secrets_exist(self):
        self.assertEqual(web_push.channels(), ['email'])
        with patch.dict('os.environ', {'VAPID_PRIVATE_KEY': self.config['VAPID_PRIVATE_KEY']}):
            self.assertEqual(web_push.channels(), ['email'])
        with patch.dict('os.environ', self.config):
            self.assertEqual(web_push.channels(), ['push'])
            self.assertNotIn('APP_PASSWORD', web_push.required_variables())
        with patch.dict('os.environ', {'NOTIFICATION_CHANNELS': 'wrong'}):
            with self.assertRaises(web_push.PushError):
                web_push.channels()

    def test_two_posts_make_two_notifications_with_all_links_kept_per_post(self):
        urls = ['https://example.com/' + str(i) + '?' + 'a' * 170 for i in range(40)]
        body = '\n\n'.join(f'{i}. 새 글\n{url}' for i, url in enumerate(urls))
        items = [{'id': str(i), 'title': f'글 {i}', 'links': [{'url': url, 'title': '첨부 링크'} for url in urls[i * 20:(i + 1) * 20]]}
                 for i in range(2)]
        result = web_push.payloads('새 글 2개', body, items=items)
        self.assertEqual(len(result), 2)
        decoded = []
        for raw in result:
            data = json.loads(raw)
            decoded.append(json.loads(zlib.decompress(base64.b64decode(data['z']))) if 'z' in data else data)
        self.assertTrue(all(len(payload['links']) == 20 for payload in decoded))
        self.assertEqual(len({payload['tag'] for payload in decoded}), 2)
        actual = [item['url'] for payload in decoded for item in payload['links']]
        self.assertEqual(actual, urls)
        self.assertTrue(all(len(payload.encode()) <= web_push.MAX_PAYLOAD_BYTES for payload in result))
        self.assertEqual(web_push.payloads('새 글 2개', body, items=items), result)

    def test_real_encryption_and_vapid_signature_with_mocked_transport(self):
        response = requests.Response()
        response.status_code = 201
        response._content = b''
        with patch.dict('os.environ', self.config), patch('pywebpush.requests.post', return_value=response) as post:
            web_push.send_push('새 알림', '첫 글\nhttps://example.com/1\n둘째 글\nhttps://example.com/2')
        self.assertEqual(post.call_count, 1)
        urls = []
        for call in post.call_args_list:
            ciphertext = call.kwargs['data']
            self.assertIsInstance(ciphertext, bytes)
            self.assertNotIn(b'https://example.com', ciphertext)
            plaintext = http_ece.decrypt(ciphertext, private_key=self.receiver, auth_secret=self.auth, version='aes128gcm')
            payload = json.loads(plaintext)
            self.assertEqual(len(payload['links']), 2)
            urls.extend(link['url'] for link in payload['links'])
        self.assertEqual(urls, ['https://example.com/1', 'https://example.com/2'])
        self.assertTrue(any(key.lower() == 'authorization' for key in post.call_args.kwargs['headers']))

    def test_rejects_untrusted_push_endpoint_before_network_access(self):
        for endpoint in ['http://fcm.googleapis.com/test', 'https://evil.example/push', 'https://fcm.googleapis.com:444/test']:
            bad = deepcopy(self.subscription)
            bad['endpoint'] = endpoint
            with patch.dict('os.environ', {**self.config, 'WEB_PUSH_SUBSCRIPTIONS': json.dumps(bad)}), \
                    patch('pywebpush.requests.post') as post:
                with self.assertRaises(web_push.PushError):
                    web_push.send_push('title', 'body')
                post.assert_not_called()

    def test_two_canvas_posts_emit_two_pushes_and_keep_each_posts_links_together(self):
        from canvas_lms import Notification, monitor_canvas
        import dongaupdate
        now = datetime.now(timezone.utc)
        first = Notification('대화메시지', '첫 글', 'https://canvas.donga.ac.kr/conversations/1', now,
                             ('https://example.com/a', 'https://example.com/b'))
        second = Notification('공지사항', '둘째 글', 'https://canvas.donga.ac.kr/courses/1/discussion_topics/2', now)
        client = Mock()
        client.poll_announcements.return_value = ([second], {'seen_ids': ['1:2']})
        client.poll_messages.return_value = ([first], {'conversations': {}})
        response = requests.Response()
        response.status_code = 201
        response._content = b''
        state = {}
        web_push.bind_delivery_state(state)
        with patch.dict('os.environ', self.config), patch('pywebpush.requests.post', return_value=response) as post, \
                patch('dongaupdate._send_smtp_email') as email:
            self.assertTrue(monitor_canvas(client, state, dongaupdate.send_email))
            email.assert_not_called()
        self.assertEqual(post.call_count, 2)
        decoded = [json.loads(http_ece.decrypt(call.kwargs['data'], private_key=self.receiver,
                                             auth_secret=self.auth, version='aes128gcm'))
                   for call in post.call_args_list]
        grouped = {payload['title']: [link['url'] for link in payload['links']] for payload in decoded}
        self.assertEqual(grouped['[대화메시지] 첫 글'], ['https://example.com/a', 'https://example.com/b'])
        self.assertEqual(grouped['[공지사항] 둘째 글'], [second.url])

    def test_expired_subscription_reports_no_private_response_or_endpoint(self):
        from pywebpush import WebPushException
        response = requests.Response()
        response.status_code = 410
        response._content = b'private server text'
        with patch.dict('os.environ', self.config), \
                patch('pywebpush.webpush', side_effect=WebPushException('private endpoint', response=response)):
            with self.assertRaises(web_push.PushError) as error:
                web_push.send_push('private title', 'body')
        self.assertIn('만료', str(error.exception))
        self.assertNotIn('private', str(error.exception))

    def test_partial_delivery_retries_only_failed_channel_after_state_reload(self):
        state = {}
        web_push.bind_delivery_state(state)
        email = Mock()
        with patch.dict('os.environ', {'NOTIFICATION_CHANNELS': 'email,push'}), \
                patch('web_push.send_push', side_effect=web_push.PushError('temporary')):
            with self.assertRaises(web_push.PushError):
                web_push.dispatch('private title', 'private body', email)
        serialized = json.dumps(state)
        self.assertNotIn('private', serialized)
        web_push.bind_delivery_state(json.loads(serialized))
        with patch.dict('os.environ', {'NOTIFICATION_CHANNELS': 'email,push'}), patch('web_push.send_push') as push:
            web_push.dispatch('private title', 'private body', email)
            push.assert_called_once()
        email.assert_called_once()


if __name__ == '__main__':
    unittest.main()
