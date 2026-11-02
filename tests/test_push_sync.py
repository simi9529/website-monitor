import base64
import json
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import http_ece

from push_sync import prepare


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


class SyncEncryptionTests(unittest.TestCase):
    def test_per_device_ack_tokens_and_encrypted_dismiss_packets_without_private_key_on_relay(self):
        signer = ec.generate_private_key(ec.SECP256R1())
        private = b64(signer.private_numbers().private_value.to_bytes(32, 'big'))
        receivers = [ec.generate_private_key(ec.SECP256R1()) for _ in range(2)]
        auth = b'test-auth-secret'
        subscriptions = [{'endpoint': f'https://fcm.googleapis.com/fcm/send/{i}', 'keys': {
            'p256dh': b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
            'auth': b64(auth),
        }} for i, key in enumerate(receivers)]
        message = json.dumps({'tag': 'a' * 24, 'title': 'test', 'links': [{'url': 'https://example.com'}]})
        with patch('push_sync.requests.post', return_value=Mock(status_code=204)) as register:
            prepared = prepare([message], subscriptions, private, 'https://relay.example', 'api-secret')
        first, second = [json.loads(messages[0]) for messages in prepared]
        self.assertNotEqual(first['sync']['token'], second['sync']['token'])
        devices = register.call_args.kwargs['json']['devices']
        self.assertNotIn(private, json.dumps(register.call_args.kwargs['json']))
        for device, receiver in zip(devices, receivers):
            packet = device['packet']
            decoded = json.loads(http_ece.decrypt(base64.b64decode(packet['body']), private_key=receiver,
                                                 auth_secret=auth, version='aes128gcm'))
            self.assertEqual(decoded, {'type': 'dismiss', 'tag': 'a' * 24})

    def test_failed_registration_is_reported(self):
        with self.assertRaises(ValueError):
            prepare([], [], '', 'http://insecure.example', '')
