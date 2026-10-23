import contextlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import MagicMock, patch

import requests

from canvas_lms import CanvasClient, CanvasError, Notification, STATE_KEY, monitor_canvas, message_links, notification_body


NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
BEFORE = "2026-10-23T11:00:00+00:00"


def response(data, next_url=None, status=200):
    result = MagicMock(status_code=status)
    result.json.return_value = data
    result.links = {"next": {"url": next_url}} if next_url else {}
    return result


def announcement(post_id):
    return {"id": post_id, "title": f"공지 {post_id}", "posted_at": "2026-10-23T11:30:00Z"}


def conversation(count=1):
    return {"id": 20, "subject": "강의 질문", "last_message_at": "2026-10-23T11:30:00Z", "message_count": count}


def message(message_id, author=2):
    return {"id": message_id, "author_id": author, "created_at": "2026-10-23T11:30:00Z"}


class CanvasClientTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = CanvasClient(self.session)

    def test_message_body_links_replace_conversation_url_in_email(self):
        self.session.get.side_effect = [
            response({'id': 1}), response([conversation()]),
            response({'messages': [{**message(101), 'body':
                '<a href="https://lecture.example/watch?a=1&amp;b=2">강의</a> '
                'https://lecture.example/material.pdf'}]})
        ]
        events, _ = self.client.poll_messages({'checked_at': BEFORE, 'conversations': {}}, now=NOW)
        body = notification_body(events)
        self.assertIn('https://lecture.example/watch?a=1&b=2', body)
        self.assertIn('https://lecture.example/material.pdf', body)
        self.assertNotIn('/conversations/20', body)
        self.session.put.assert_not_called()

    def test_message_links_are_deduplicated_and_only_web_links_are_included(self):
        self.assertEqual(message_links(
            '<a href="javascript:alert(1)">실행</a><a href="mailto:a@example.com">메일</a>'
            '<a href="https://example.com/a">링크</a> https://example.com/a '
            '(https://example.com/lesson_(1)). <a href="/courses/1">수업</a>'
        ), ('https://example.com/a', 'https://example.com/lesson_(1)',
            'https://canvas.donga.ac.kr/courses/1'))

    def test_message_without_links_keeps_conversation_link(self):
        for body in [None, '', '링크 없는 메시지']:
            self.assertEqual(message_links(body), ())
        event = Notification('대화메시지', '질문', 'https://canvas.donga.ac.kr/conversations/20', NOW)
        self.assertIn(event.url, notification_body([event]))

    def test_announcement_baseline_then_both_new_posts(self):
        self.session.get.side_effect = [
            response([{"id": 1, "name": "강의"}]), response([announcement(10)])
        ]
        events, baseline = self.client.poll_announcements(now=NOW)
        self.assertEqual(events, [])
        self.assertEqual(baseline["seen_ids"], ["1:10"])
        self.session.get.side_effect = [
            response([{"id": 1, "name": "강의"}]),
            response([announcement(12), announcement(11), announcement(10)])
        ]
        events, updated = self.client.poll_announcements(baseline, now=NOW)
        self.assertEqual(len(events), 2)
        self.assertEqual({event.url for event in events}, {
            "https://canvas.donga.ac.kr/courses/1/discussion_topics/11",
            "https://canvas.donga.ac.kr/courses/1/discussion_topics/12",
        })
        self.assertEqual(updated["seen_ids"], ["1:10", "1:11", "1:12"])

    def test_all_course_pages_are_read_and_next_link_must_stay_on_canvas(self):
        next_page = "https://canvas.donga.ac.kr/api/v1/courses?page=2"
        self.session.get.side_effect = [response([{"id": 1}], next_page), response([{"id": 2}])]
        self.assertEqual([row["id"] for row in self.client._list("/api/v1/courses")], [1, 2])
        self.session.get.side_effect = [response([], "https://other.example/api/v1/courses")]
        with self.assertRaises(CanvasError):
            list(self.client._list("/api/v1/courses"))
        self.assertEqual(self.session.get.call_args.args[0], "https://canvas.donga.ac.kr/api/v1/courses")

    def test_donga_legacy_timestamp_and_unpublished_or_future_announcements(self):
        legacy = {**announcement(11), "posted_at": None, "created_at": "2026-10-23T11:30:00Z", "published": True}
        draft = {**announcement(12), "posted_at": None, "published": False}
        future = {**announcement(13), "posted_at": "2026-10-24T11:30:00Z"}
        self.session.get.side_effect = [response([{"id": 1}]), response([legacy, draft, future])]
        events, state = self.client.poll_announcements({"checked_at": BEFORE, "seen_ids": []}, now=NOW)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].url.endswith('/discussion_topics/11'))
        self.assertEqual(state['seen_ids'], ['1:11'])

    def test_looping_pagination_fails_instead_of_acknowledging_partial_data(self):
        self.session.get.side_effect = None
        self.session.get.return_value = response([], "https://canvas.donga.ac.kr/api/v1/courses")
        with self.assertRaises(CanvasError):
            list(self.client._list("/api/v1/courses"))

    def test_old_conversation_can_receive_two_new_messages_without_marking_read(self):
        previous = {"checked_at": BEFORE, "conversations": {
            "20": {"signature": [BEFORE, 1], "last_message_id": 100}
        }}
        self.session.get.side_effect = [
            response({"id": 1}), response([conversation(4)]),
            response({"messages": [message(103, author=1), message(102), message(101), message(100)]})
        ]
        events, updated = self.client.poll_messages(previous, now=NOW)
        self.assertEqual(len(events), 2)
        self.assertEqual({event.url for event in events}, {
            "https://canvas.donga.ac.kr/conversations/20?message=101",
            "https://canvas.donga.ac.kr/conversations/20?message=102",
        })
        self.assertEqual(updated["conversations"]["20"]["last_message_id"], 103)
        self.assertEqual(self.session.get.call_args.kwargs["params"], {"auto_mark_as_read": "false"})
        self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])
        self.session.post.assert_not_called()
        self.session.put.assert_not_called()
        self.session.delete.assert_not_called()

    def test_message_baseline_does_not_notify_historical_messages(self):
        self.session.get.side_effect = [
            response({"id": 1}), response([conversation()]), response({"messages": [message(100)]})
        ]
        events, baseline = self.client.poll_messages(now=NOW)
        self.assertEqual(events, [])
        self.assertEqual(baseline["conversations"]["20"]["last_message_id"], 100)

    def test_unchanged_conversation_is_not_opened_again(self):
        row = conversation()
        previous = {"checked_at": BEFORE, "conversations": {
            "20": {"signature": [row["last_message_at"], row["message_count"]], "last_message_id": 100}
        }}
        self.session.get.side_effect = [response({"id": 1}), response([row])]
        events, _ = self.client.poll_messages(previous, now=NOW)
        self.assertEqual(events, [])
        self.assertEqual(self.session.get.call_count, 2)

    def test_new_conversation_after_baseline_includes_new_received_message(self):
        self.session.get.side_effect = [
            response({"id": 1}), response([conversation()]), response({"messages": [message(100)]})
        ]
        events, _ = self.client.poll_messages({"checked_at": BEFORE, "conversations": {}}, now=NOW)
        self.assertEqual(len(events), 1)

    def test_auth_network_and_schema_failures_are_sanitized(self):
        for bad in [response({}, status=401), response({}, status=302), response({"invalid": "private fixture"})]:
            self.session.get.side_effect = None
            self.session.get.return_value = bad
            with self.assertRaises(CanvasError) as error:
                list(self.client._list("/api/v1/courses"))
            self.assertNotIn("private fixture", str(error.exception))
        self.session.get.side_effect = requests.ConnectionError("private request fixture")
        with self.assertRaises(CanvasError) as error:
            self.client._get("/api/v1/courses")
        self.assertNotIn("private request fixture", str(error.exception))


class CanvasMonitorTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.mail = MagicMock()
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        self.notice = Notification("공지사항", "공지", "https://canvas.donga.ac.kr/courses/1/discussion_topics/1", NOW)
        self.reply = Notification("대화메시지", "새 답장", "https://canvas.donga.ac.kr/conversations/2?message=3", NOW)

    def test_either_area_or_both_areas_trigger_one_digest_containing_all_links(self):
        for notices, messages in [([self.notice], []), ([], [self.reply]), ([self.notice], [self.reply])]:
            with self.subTest(notices=len(notices), messages=len(messages)):
                self.mail.reset_mock()
                self.client.poll_announcements.return_value = (notices, {"seen_ids": ["1:1"]})
                self.client.poll_messages.return_value = (messages, {"conversations": {}})
                state = {}
                self.assertTrue(monitor_canvas(self.client, state, self.mail))
                self.mail.assert_called_once()
                body = self.mail.call_args.args[1]
                for event in notices + messages:
                    self.assertIn(event.url, body)
                self.assertIn(STATE_KEY, state)

    def test_one_failed_area_does_not_prevent_other_notifications(self):
        self.client.poll_announcements.side_effect = CanvasError("공지 조회 실패")
        self.client.poll_messages.return_value = ([self.reply], {"conversations": {}})
        state = {STATE_KEY: {"announcements": {"checked_at": BEFORE}}}
        self.assertTrue(monitor_canvas(self.client, state, self.mail))
        self.mail.assert_called_once()
        self.assertEqual(state[STATE_KEY]["announcements"], {"checked_at": BEFORE})

    def test_email_failure_does_not_acknowledge_either_area(self):
        self.client.poll_announcements.return_value = ([self.notice], {"seen_ids": ["1:1"]})
        self.client.poll_messages.return_value = ([self.reply], {"conversations": {}})
        self.mail.side_effect = RuntimeError("private SMTP fixture")
        state = {STATE_KEY: {"announcements": {"checked_at": BEFORE}}}
        before = deepcopy(state)
        self.assertFalse(monitor_canvas(self.client, state, self.mail))
        self.assertEqual(state, before)

    def test_baseline_or_unchanged_items_do_not_send_email(self):
        self.client.poll_announcements.return_value = ([], {"seen_ids": []})
        self.client.poll_messages.return_value = ([], {"conversations": {}})
        self.assertTrue(monitor_canvas(self.client, {}, self.mail))
        self.mail.assert_not_called()


class CanvasIntegrationTests(unittest.TestCase):
    def setUp(self):
        import dongaupdate
        self.app = dongaupdate
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.dict("os.environ", dict.fromkeys([
            "CANVAS_ID", "CANVAS_PW", "FROM_EMAIL", "TO_EMAIL", "APP_PASSWORD"
        ], "fixture-only")))
        self.login = self.stack.enter_context(patch("dongaupdate.sso_session"))
        self.factory = self.stack.enter_context(patch("dongaupdate.CanvasClient"))
        self.mail = self.stack.enter_context(patch("dongaupdate.send_email"))
        self.save = self.stack.enter_context(patch("dongaupdate.save_state"))
        self.load = self.stack.enter_context(patch("dongaupdate.load_state", return_value={}))

    def test_missing_canvas_password_skips_login(self):
        with patch.dict("os.environ", {"CANVAS_PW": ""}):
            self.app.check_canvas_board({})
            self.assertEqual(self.app.send_latest_canvas(), 2)
        self.login.assert_not_called()
        self.mail.assert_not_called()

    def test_test_digest_contains_latest_item_from_each_area(self):
        old = Notification("공지사항", "이전 공지", "https://canvas.donga.ac.kr/old", NOW - timedelta(days=1))
        notice = Notification("공지사항", "최신 공지", "https://canvas.donga.ac.kr/notice", NOW)
        message = Notification("대화메시지", "최신 대화", "https://canvas.donga.ac.kr/message", NOW)
        client = self.factory.return_value
        client.poll_announcements.return_value = ([old, notice], {"seen_ids": ["1:1"]})
        client.poll_messages.return_value = ([message], {"conversations": {}})
        self.assertEqual(self.app.send_latest_canvas(), 0)
        subject, body = self.mail.call_args.args
        self.assertIn("시험 발송", subject)
        self.assertIn(notice.url, body)
        self.assertIn(message.url, body)
        self.assertNotIn(old.url, body)
        self.save.assert_called_once_with({STATE_KEY: {
            "announcements": {"seen_ids": ["1:1"]}, "messages": {"conversations": {}}
        }})

    def test_test_email_failure_does_not_save_or_advance_state(self):
        notice = Notification("공지사항", "공지", "https://canvas.donga.ac.kr/notice", NOW)
        client = self.factory.return_value
        client.poll_announcements.return_value = ([notice], {"seen_ids": ["1:1"]})
        client.poll_messages.return_value = ([], {"conversations": {}})
        self.mail.side_effect = RuntimeError("private fixture")
        self.assertEqual(self.app.send_latest_canvas(), 1)
        self.save.assert_not_called()


class LoginDiagnosticsTests(unittest.TestCase):
    def test_only_authorized_school_duplicate_login_confirmation_is_accepted(self):
        from canvas_sso import _handle_dialog
        for allowed, host, kind, message, accept in [
            (True, 'login.donga.ac.kr', 'confirm', '이전 로그인을 끊고 강제로 로그인하시겠습니까?', True),
            (False, 'login.donga.ac.kr', 'confirm', '이전 로그인을 끊고 강제로 로그인하시겠습니까?', False),
            (True, 'other.example', 'confirm', '이전 로그인을 끊고 강제로 로그인하시겠습니까?', False),
            (True, 'login.donga.ac.kr', 'confirm', '추가 인증 동의', False),
            (True, 'login.donga.ac.kr', 'alert', '이전 로그인을 끊고 강제로 로그인하시겠습니까?', False),
            (True, 'login.donga.ac.kr', 'confirm', 'Do you want to terminate the previous login and force a login?', True),
        ]:
            with self.subTest(allowed=allowed, host=host, kind=kind, message=message):
                page = MagicMock(url='https://' + host + '/login')
                dialog = MagicMock(type=kind, message=message)
                _handle_dialog(page, dialog, allowed)
                self.assertEqual(dialog.accept.call_count, int(accept))
                self.assertEqual(dialog.dismiss.call_count, int(not accept))

    def test_known_school_error_is_reported_without_server_message(self):
        from canvas_sso import _login_error
        page = MagicMock()
        page.evaluate.return_value = '9002'
        self.assertIn('중복 로그인', _login_error(page))
        page.evaluate.return_value = 'private server text'
        self.assertIsNone(_login_error(page))


if __name__ == "__main__":
    unittest.main()
