"""Optional acknowledgement relay; never send VAPID private keys to it."""

import base64
import hashlib
import json
import secrets
import zlib
from urllib.parse import urlsplit

import requests


class CaptureTransport:
    def post(self, endpoint, **kwargs):
        self.packet = {"endpoint": endpoint, "headers": dict(kwargs["headers"]),
                       "body": base64.b64encode(kwargs["data"]).decode()}
        response = requests.Response()
        response.status_code = 201
        response._content = b""
        return response


def encode(data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > 3000:
        raw = json.dumps({"z": base64.b64encode(zlib.compress(raw.encode())).decode()})
    if len(raw.encode()) > 3000:
        raise ValueError("sync payload too large")
    return raw


def prepare(messages, subscriptions, private_key, url, api_key):
    from pywebpush import webpush
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("invalid relay URL")
    url = url.rstrip("/")
    prepared = [[] for _ in subscriptions]
    for message in messages:
        data = json.loads(message)
        if "z" in data:
            data = json.loads(zlib.decompress(base64.b64decode(data["z"])))
        devices = []
        for index, subscription in enumerate(subscriptions):
            token = secrets.token_urlsafe(32)
            transport = CaptureTransport()
            webpush(subscription_info=subscription,
                    data=json.dumps({"type": "dismiss", "tag": data["tag"]}),
                    vapid_private_key=private_key, vapid_claims={"sub": "https://simi9529.github.io"},
                    ttl=86400, headers={"Urgency": "high"}, requests_session=transport)
            devices.append({"id": hashlib.sha256(subscription["endpoint"].encode()).hexdigest(),
                            "token": token, "packet": transport.packet})
            prepared[index].append(encode({**data, "sync": {"url": url, "token": token}}))
        response = requests.post(url + "/register", json={"id": data["tag"], "devices": devices},
                                 headers={"Authorization": "Bearer " + api_key}, timeout=(5, 20), allow_redirects=False)
        if response.status_code != 204:
            raise ValueError("relay registration failed")
    return prepared
