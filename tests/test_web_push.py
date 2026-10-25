import base64
import contextlib
from copy import deepcopy
import io
import json
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

    def test_all_links_survive_large_digest_split_and_stable_tags(self):
        urls = ['https://example.com/' + str(i) + '?' + 'a' * 170 for i in range(40)]
        body = '\n\n'.join(f'{i}. 새 글\n{url}' for i, url in enumerate(urls))
        result = web_push.payloads('새 글 40개', body)
        self.assertEqual(len(result), 40)
        self.assertTrue(all(len(json.loads(payload)['links']) == 1 for payload in result))
        self.assertEqual(len({json.loads(payload)['tag'] for payload in result}), 40)
        actual = [item['url'] for payload in result for item in json.loads(payload)['links']]
        self.assertEqual(actual, urls)
        self.assertTrue(all(len(payload.encode()) <= web_push.MAX_PAYLOAD_BYTES for payload in result))
        self.assertEqual(web_push.payloads('새 글 40개', body), result)

    def test_real_encryption_and_vapid_signature_with_mocked_transport(self):
        response = requests.Response()
        response.status_code = 201
        response._content = b''
        with patch.dict('os.environ', self.config), patch('pywebpush.requests.post', return_value=response) as post:
            web_push.send_push('새 알림', '첫 글\nhttps://example.com/1\n둘째 글\nhttps://example.com/2')
        self.assertEqual(post.call_count, 2)
        urls = []
        for call in post.call_args_list:
            ciphertext = call.kwargs['data']
            self.assertIsInstance(ciphertext, bytes)
            self.assertNotIn(b'https://example.com', ciphertext)
            plaintext = http_ece.decrypt(ciphertext, private_key=self.receiver, auth_secret=self.auth, version='aes128gcm')
            payload = json.loads(plaintext)
            self.assertEqual(len(payload['links']), 1)
            urls.append(payload['links'][0]['url'])
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
