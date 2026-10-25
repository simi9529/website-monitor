"""Encrypted Web Push delivery; browser subscription secrets stay in Actions."""

import base64
import hashlib
import json
import os
import re
import zlib
from urllib.parse import urlsplit


PAGE_URL = "https://simi9529.github.io/website-monitor/"
MAX_PAYLOAD_BYTES = 3000


class PushError(RuntimeError):
    """Safe error text without endpoint tokens, payloads, or private keys."""


def channels():
    mode = os.environ.get("NOTIFICATION_CHANNELS", "auto").strip().lower() or "auto"
    if mode == "auto":
        return ["push"] if all(os.environ.get(key) for key in (
            "VAPID_PRIVATE_KEY", "WEB_PUSH_SUBSCRIPTIONS")) else ["email"]
    result = list(dict.fromkeys(part.strip() for part in mode.split(",")))
    if not result or any(part not in ("email", "push") for part in result):
        raise PushError("NOTIFICATION_CHANNELS는 auto, email, push, email,push 중 하나여야 합니다")
    return result


def required_variables():
    required = []
    if "email" in channels():
        required.extend(("FROM_EMAIL", "TO_EMAIL", "APP_PASSWORD"))
    if "push" in channels():
        required.extend(("VAPID_PRIVATE_KEY", "WEB_PUSH_SUBSCRIPTIONS"))
    return required


def _web_url(value):
    try:
        parts = urlsplit(value)
        return bool(parts.scheme in ("https", "http") and parts.hostname
                    and not parts.username and not parts.password
                    and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


def payloads(subject, body, items=None):
    """One post is one notification, including all of that post's links."""
    links = []
    label = subject
    for line in body.splitlines():
        found = False
        for match in re.finditer(r'https?://[^\s<>"\u0027]+', line):
            url = match.group().rstrip(".,;!。，")
            if _web_url(url) and all(item["url"] != url for item in links):
                if len(url.encode()) > 2200:
                    raise PushError("푸시 링크가 너무 깁니다. 알림 기준은 유지됩니다")
                links.append({"title": label[:120], "url": url})
                found = True
        if line.strip() and not found:
            label = line.strip()
    if not links:
        links = [{"title": subject[:120], "url": PAGE_URL}]
    if items is None:
        items = [{"title": subject, "body": body[:200], "links": links}]
    result = []
    for item in items:
        post_links = item.get("links", [])
        if not post_links or any(not _web_url(link.get("url", "")) for link in post_links):
            raise PushError("게시글 알림의 링크 형식을 확인하세요")
        data = {"title": item["title"][:120], "body": item.get("body", subject)[:250], "links": post_links}
        identity = item.get("id") or json.dumps(data, sort_keys=True)
        data["tag"] = hashlib.sha256(identity.encode()).hexdigest()[:24]
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
            encoded = json.dumps({"z": base64.b64encode(zlib.compress(encoded.encode())).decode()})
        if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
            raise PushError("게시글 1개의 푸시 크기 한도를 초과했습니다. 글을 나누거나 링크를 누락하지 않고 기준을 유지합니다")
        result.append(encoded)
    return result


def _subscriptions(raw):
    try:
        values = json.loads(raw)
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list) or not 1 <= len(values) <= 10:
            raise ValueError
        for value in values:
            parts = urlsplit(value["endpoint"])
            if (parts.scheme != "https" or parts.hostname not in {
                "fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com",
                "web.push.apple.com",
            } or parts.port not in (None, 443) or parts.username or parts.password):
                raise ValueError
            for key, length in (("p256dh", 65), ("auth", 16)):
                decoded = base64.urlsafe_b64decode(value["keys"][key] + "===")
                if len(decoded) != length:
                    raise ValueError
        return values
    except (ValueError, TypeError, KeyError):
        raise PushError("WEB_PUSH_SUBSCRIPTIONS 형식을 확인하세요. 폰 구독 페이지에서 다시 복사하세요") from None


def send_push(subject, body, items=None):
    missing = [name for name in ("VAPID_PRIVATE_KEY", "WEB_PUSH_SUBSCRIPTIONS") if not os.environ.get(name)]
    if missing:
        raise PushError("크롬 푸시 설정 누락: " + ", ".join(missing))
    subscriptions = _subscriptions(os.environ["WEB_PUSH_SUBSCRIPTIONS"])
    messages = payloads(subject, body, items=items)
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        raise PushError("푸시 발송 의존성을 설치하세요: pip install -r requirements.txt") from None
    for subscription in subscriptions:
        for message in messages:
            try:
                webpush(
                    subscription_info=subscription, data=message,
                    vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": "https://simi9529.github.io"}, ttl=86400,
                    headers={"Urgency": "normal"}, timeout=20,
                )
            except WebPushException as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status in (404, 410):
                    raise PushError("폰의 푸시 구독이 만료됐습니다. 구독 페이지에서 다시 등록하세요") from None
                raise PushError(f"푸시 서비스 전송 실패 (HTTP {status or '연결 오류'})") from None
            except Exception:
                raise PushError("푸시 발송 실패: 비밀키와 구독 설정을 확인하세요") from None
    print(f"✅ 크롬 푸시 서비스 전송 완료: 기기 {len(subscriptions)}개, 알림 {len(messages)}개")


_state = None


def bind_delivery_state(state):
    global _state
    _state = state


def dispatch(subject, body, email_sender, push_items=None):
    """Remember partial delivery without storing private titles/bodies in Git."""
    state = _state if _state is not None else {}
    key = hashlib.sha256((subject + "\0" + body + json.dumps(push_items, sort_keys=True)).encode()).hexdigest()
    receipts = state.get("notification_delivery", {})
    delivered = list(receipts.get(key, []))
    failed = False
    for channel in channels():
        if channel in delivered:
            continue
        try:
            if channel == "email":
                email_sender(subject, body)
            else:
                send_push(subject, body, items=push_items)
        except PushError as error:
            print(f"⚠️ {error}")
            failed = True
        except Exception:
            print(f"⚠️ {channel} 알림 전송 실패 → 다음 회차 재시도")
            failed = True
        else:
            delivered.append(channel)
    if failed:
        receipts[key] = delivered
        state["notification_delivery"] = dict(list(receipts.items())[-500:])
        raise PushError("일부 알림 전송 실패. 게시글 확인 기준을 유지합니다")
    receipts.pop(key, None)
    if not receipts:
        state.pop("notification_delivery", None)


def test_push():
    try:
        url = os.environ.get("TEST_PUSH_URL") or PAGE_URL
        if not _web_url(url):
            raise PushError("시험 알림 주소는 올바른 HTTP/HTTPS 링크여야 합니다")
        title = "크롬 알림 연결 확인" if url == PAGE_URL else "링크 이동 시험"
        send_push(title, "알림을 누르면 아래 주소로 이동합니다.\n" + url)
        return 0
    except PushError as error:
        print(str(error))
        return 1
