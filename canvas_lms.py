"""Read-only Canvas notifications using an already authenticated SSO session.

Authentication is deliberately separate: the school's SSO flow must be verified
before this reader can be enabled in the scheduled monitor.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin, urlsplit

import requests


BASE_URL = "https://canvas.donga.ac.kr"
STATE_KEY = "canvas_lms"
MAX_PAGES = 20


class CanvasError(RuntimeError):
    """Sanitized error safe to include in the monitor logs."""


def _id(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise CanvasError("Canvas 항목 번호를 읽지 못했습니다")
    return str(int(value))


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise CanvasError("Canvas 알림 시각을 읽지 못했습니다") from None


@dataclass(frozen=True)
class Notification:
    kind: str
    title: str
    url: str
    created_at: datetime


class CanvasClient:
    def __init__(self, session):
        self.session = session

    def _url(self, path, api_only=True):
        url = urljoin(BASE_URL + "/", path)
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "canvas.donga.ac.kr"
                or parts.port not in (None, 443) or parts.username or parts.password
                or (api_only and not parts.path.startswith("/api/v1/"))):
            raise CanvasError("Canvas 응답의 링크가 허용된 주소가 아닙니다")
        return url

    def _get(self, path, params=None):
        try:
            response = self.session.get(
                self._url(path), params=params, timeout=(5, 20),
                allow_redirects=False, headers={"Accept": "application/json"},
            )
        except requests.RequestException:
            raise CanvasError("Canvas 연결 실패") from None
        if response.status_code in (401, 403) or 300 <= response.status_code < 400:
            raise CanvasError("Canvas 로그인 세션 또는 접근 권한을 확인하세요")
        if response.status_code != 200:
            raise CanvasError(f"Canvas 조회 HTTP 오류: {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise CanvasError("Canvas JSON 응답을 읽지 못했습니다") from None
        return data, response.links.get("next", {}).get("url")

    def _list(self, path, params=None):
        visited = set()
        for _ in range(MAX_PAGES):
            url = self._url(path)
            if url in visited:
                raise CanvasError("Canvas 페이지 링크가 반복됩니다. 상태를 유지합니다")
            visited.add(url)
            data, next_url = self._get(url, params)
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise CanvasError("Canvas 목록 응답 형식이 변경되었습니다")
            yield from data
            if not next_url:
                return
            path, params = self._url(next_url), None
        raise CanvasError("Canvas 조회 한도를 초과했습니다. 상태를 유지합니다")

    def poll_announcements(self, previous=None, now=None):
        now = now or datetime.now(timezone.utc)
        start = (_time(previous["checked_at"]) - timedelta(minutes=5)
                 if previous else now - timedelta(days=180))
        seen = set(previous.get("seen_ids", [])) if previous else set()
        next_seen = set(seen)
        events = []
        courses = self._list("/api/v1/courses", {
            "enrollment_type": "student", "enrollment_state": "active",
            "state[]": "available", "per_page": 100,
        })
        for course in courses:
            course_id = _id(course.get("id"))
            params = {
                "context_codes[]": "course_" + course_id,
                "start_date": start.isoformat(), "end_date": now.isoformat(),
                "active_only": "true", "per_page": 100,
            }
            for row in self._list("/api/v1/announcements", params):
                if row.get("published") is False:
                    continue
                post_id = _id(row.get("id"))
                key = f"{course_id}:{post_id}"
                title = row.get("title")
                if not isinstance(title, str) or not title.strip():
                    raise CanvasError("Canvas 공지 제목을 읽지 못했습니다")
                # Donga's Canvas returns some legacy announcements with a
                # null posted_at but a valid created_at.
                date = _time(row.get("posted_at") or row.get("delayed_post_at") or row.get("created_at"))
                if date > now:
                    continue
                next_seen.add(key)
                if previous is not None and key not in seen:
                    link = f"/courses/{course_id}/discussion_topics/{post_id}"
                    events.append(Notification(
                        "공지사항", f"{course.get('name', course_id)}: {title.strip()}",
                        self._url(row.get("html_url") or link, api_only=False), date,
                    ))
        return events, {"seen_ids": sorted(next_seen), "checked_at": now.isoformat()}

    def poll_messages(self, previous=None, now=None):
        now = now or datetime.now(timezone.utc)
        user, _ = self._get("/api/v1/users/self/profile")
        if not isinstance(user, dict):
            raise CanvasError("Canvas 사용자 응답 형식이 변경되었습니다")
        user_id = _id(user.get("id"))
        old_marks = previous.get("conversations", {}) if previous else {}
        marks = dict(old_marks)
        events = []
        for row in self._list("/api/v1/conversations", {"per_page": 100}):
            conversation_id = _id(row.get("id"))
            signature = [row.get("last_message_at"), row.get("message_count")]
            old = old_marks.get(conversation_id)
            if old and old.get("signature") == signature:
                continue
            detail, _ = self._get(
                f"/api/v1/conversations/{conversation_id}", {"auto_mark_as_read": "false"}
            )
            if not isinstance(detail, dict) or not isinstance(detail.get("messages"), list):
                raise CanvasError("Canvas 대화 응답 형식이 변경되었습니다")
            latest_id = int(old["last_message_id"]) if old else 0
            for message in detail["messages"]:
                if not isinstance(message, dict):
                    raise CanvasError("Canvas 메시지 응답 형식이 변경되었습니다")
                message_id = int(_id(message.get("id")))
                latest_id = max(latest_id, message_id)
                author_id = _id(message.get("author_id"))
                date = _time(message.get("created_at"))
                is_new = (message_id > int(old["last_message_id"]) if old
                          else previous is not None and date >= _time(previous["checked_at"]))
                if previous is not None and is_new and author_id != user_id:
                    query = urlencode({"message": message_id})
                    events.append(Notification(
                        "대화메시지", row.get("subject") or "제목 없는 대화",
                        self._url(f"/conversations/{conversation_id}?{query}", api_only=False), date,
                    ))
            marks[conversation_id] = {"signature": signature, "last_message_id": latest_id}
        return events, {"conversations": marks, "checked_at": now.isoformat()}


def notification_body(events):
    return "[동아대 Canvas 새 알림]\n\n" + "\n\n".join(
        f"{index}. [{event.kind}] {event.title}\n{event.url}"
        for index, event in enumerate(events, 1)
    )


def monitor_canvas(client, state, send_email):
    """Poll both areas independently and acknowledge only after a whole digest."""
    previous = state.get(STATE_KEY, {})
    next_state = dict(previous)
    events = []
    for name, poll in [("announcements", client.poll_announcements),
                       ("messages", client.poll_messages)]:
        try:
            updates, checkpoint = poll(previous.get(name))
        except CanvasError as error:
            print(f"⚠️ [Canvas {name}] {error}")
            continue
        events.extend(updates)
        next_state[name] = checkpoint
    events.sort(key=lambda event: (event.created_at, event.url))
    if events:
        try:
            send_email(f"[동아대 Canvas] 새 알림 {len(events)}개", notification_body(events))
        except Exception:
            print("⚠️ [Canvas] 발송 실패 → 모든 미발송 알림은 다음 회차에 재시도")
            return False
    if next_state:
        state[STATE_KEY] = next_state
    print(f"✅ [Canvas] 확인 완료: 새 알림 {len(events)}개")
    return True
