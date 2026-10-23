import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

import requests

import dongaupdate
import ewhaian


def response(payload, status=200):
    result = MagicMock(status_code=status)
    result.json.return_value = payload
    return result


def rows(*ids):
    return [{"id": post_id, "title": f"게시글 {post_id}"} for post_id in ids]


class FetchPostsTests(unittest.TestCase):
    def setUp(self):
        self.factory = patch("ewhaian.requests.Session")
        self.session = self.factory.start().return_value.__enter__.return_value
        self.session.headers = {}
        self.addCleanup(self.factory.stop)
        self.login = response({"success": True, "data": {"accessToken": "fixture-token"}})

    def test_login_and_board_request_match_site_api(self):
        self.session.post.side_effect = [self.login, response({"list": rows(103, 102, 101)})]
        posts = ewhaian.fetch_posts("fixture-user", "fixture-password", 101)
        self.assertEqual([post.id for post in posts], [102, 103])
        self.assertEqual(posts[0].url, "https://ewhaian.com/life/66/detail/102")
        login, listing = self.session.post.call_args_list
        self.assertEqual(login.args[0], "https://ewhaian.com/api/unauth/login")
        self.assertEqual(login.kwargs["json"], {
            "username": "fixture-user", "password": "fixture-password"
        })
        self.assertEqual(listing.kwargs["json"]["categoryIdList"], [66])
        self.assertEqual(listing.kwargs["json"]["sort"], "new")
        self.assertEqual(listing.kwargs["timeout"], (5, 20))
        self.assertFalse(login.kwargs["allow_redirects"])
        self.assertFalse(listing.kwargs["allow_redirects"])
        self.assertEqual(self.session.headers["Authorization"], "Bearer fixture-token")

    def test_first_run_reads_only_one_page(self):
        self.session.post.side_effect = [self.login, response({"list": rows(*range(30, 12, -1))})]
        posts = ewhaian.fetch_posts("fixture-user", "fixture-password")
        self.assertEqual(posts[-1].id, 30)
        self.assertEqual(self.session.post.call_count, 2)

    def test_paginates_and_deduplicates_posts(self):
        self.session.post.side_effect = [
            self.login,
            response({"list": rows(*range(40, 22, -1))}),
            response({"list": rows(23, 22, 21, 20)}),
        ]
        posts = ewhaian.fetch_posts("fixture-user", "fixture-password", 21)
        self.assertEqual([post.id for post in posts], list(range(22, 41)))
        self.assertEqual(self.session.post.call_args.kwargs["json"]["page"], 2)

    def test_deleted_checkpoint_does_not_resend_older_posts(self):
        self.session.post.side_effect = [self.login, response({"list": rows(105, 103, 101)})]
        posts = ewhaian.fetch_posts("fixture-user", "fixture-password", 104)
        self.assertEqual([post.id for post in posts], [105])

    def test_large_backlog_fails_without_claiming_complete_results(self):
        self.session.post.side_effect = [
            self.login, response({"list": rows(*range(40, 22, -1))})
        ]
        with patch.object(ewhaian, "MAX_PAGES", 1):
            with self.assertRaises(ewhaian.EwhaianError):
                ewhaian.fetch_posts("fixture-user", "fixture-password", 1)

    def test_rejected_login_does_not_query_board_or_leak_response(self):
        self.session.post.return_value = response({
            "success": False, "description": "private server response fixture"
        })
        with self.assertRaises(ewhaian.EwhaianError) as error:
            ewhaian.fetch_posts("fixture-user", "fixture-password")
        self.assertNotIn("private server response", str(error.exception))
        self.assertEqual(self.session.post.call_count, 1)

    def test_http_failure_invalid_json_and_schema_are_reported(self):
        invalid_json = response(None)
        invalid_json.json.side_effect = ValueError("raw response fixture")
        for bad in [response({}, 403), response({}, 307), invalid_json,
                    response({"success": False}), response({"list": rows(0)}),
                    response({"list": [{"id": 1, "title": None}]})]:
            with self.subTest(response=bad):
                self.session.post.side_effect = [self.login, bad]
                with self.assertRaises(ewhaian.EwhaianError):
                    ewhaian.fetch_posts("fixture-user", "fixture-password", 1)

    def test_connection_error_is_sanitized(self):
        self.session.post.side_effect = requests.ConnectionError("private request fixture")
        with self.assertRaises(ewhaian.EwhaianError) as error:
            ewhaian.fetch_posts("fixture-user", "fixture-password")
        self.assertNotIn("private request fixture", str(error.exception))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"EWHA_ID": "fixture-user", "EWHA_PW": "fixture-password"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fetcher = patch("dongaupdate.fetch_posts")
        self.fetch = self.fetcher.start()
        self.addCleanup(self.fetcher.stop)
        self.mailer = patch("dongaupdate.send_email")
        self.mail = self.mailer.start()
        self.addCleanup(self.mailer.stop)
        self.output = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.output)
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        self.key = dongaupdate.EWHA_STATE_KEY

    def test_first_run_records_baseline_without_emailing_old_posts(self):
        state = {"unrelated": "preserved"}
        self.fetch.return_value = [ewhaian.Post(101, "old"), ewhaian.Post(102, "latest")]
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(state, {"unrelated": "preserved", self.key: "102"})
        self.mail.assert_not_called()

    def test_new_posts_send_links_in_order_and_advance_checkpoint(self):
        state = {self.key: "100"}
        self.fetch.return_value = [ewhaian.Post(101, "first"), ewhaian.Post(102, "second")]
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(self.mail.call_count, 1)
        subject, body = self.mail.call_args.args
        self.assertIn("2개", subject)
        self.assertIn("1. first\nhttps://ewhaian.com/life/66/detail/101", body)
        self.assertIn("2. second\nhttps://ewhaian.com/life/66/detail/102", body)
        self.assertEqual(state[self.key], "102")
        self.fetch.return_value = []
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(self.mail.call_count, 1)
        self.fetch.assert_called_with("fixture-user", "fixture-password", 102)

    def test_email_failure_preserves_all_unnotified_posts_for_retry(self):
        state = {self.key: "100"}
        self.fetch.return_value = [ewhaian.Post(101, "first"), ewhaian.Post(102, "second")]
        self.mail.side_effect = RuntimeError("private SMTP fixture")
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(state[self.key], "100")
        self.assertNotIn("private SMTP fixture", self.output.getvalue())
        self.mail.side_effect = None
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(state[self.key], "102")
        self.assertIn("/detail/101", self.mail.call_args.args[1])
        self.assertIn("/detail/102", self.mail.call_args.args[1])

    def test_latest_test_email_initializes_checkpoint_only_after_smtp_success(self):
        self.fetch.return_value = [ewhaian.Post(101, "older"), ewhaian.Post(102, "latest")]
        with patch.dict("os.environ", {"FROM_EMAIL": "", "TO_EMAIL": "", "APP_PASSWORD": ""}):
            self.assertEqual(dongaupdate.send_latest_ewhaian(), 2)
            self.fetch.assert_not_called()
        self.mail.assert_not_called()
        with patch.dict("os.environ", {
            "FROM_EMAIL": "sender@example.test", "TO_EMAIL": "recipient@example.test",
            "APP_PASSWORD": "fixture-password",
        }), patch.object(dongaupdate, "load_state", return_value={}), \
             patch.object(dongaupdate, "save_state") as save:
            self.assertEqual(dongaupdate.send_latest_ewhaian(), 0)
            subject, body = self.mail.call_args.args
            self.assertIn("시험", subject)
            self.assertIn("/detail/102", body)
            self.assertNotIn("/detail/101", body)
            save.assert_called_once_with({self.key: "102"})

    def test_latest_test_email_does_not_overwrite_existing_checkpoint(self):
        self.fetch.return_value = [ewhaian.Post(102, "latest")]
        with patch.dict("os.environ", {
            "FROM_EMAIL": "sender@example.test", "TO_EMAIL": "recipient@example.test",
            "APP_PASSWORD": "fixture-password",
        }), patch.object(dongaupdate, "load_state", return_value={self.key: "100"}), \
             patch.object(dongaupdate, "save_state") as save:
            self.assertEqual(dongaupdate.send_latest_ewhaian(), 0)
            save.assert_not_called()

    def test_latest_test_email_failure_does_not_save_checkpoint(self):
        self.fetch.return_value = [ewhaian.Post(102, "latest")]
        self.mail.side_effect = RuntimeError("private SMTP fixture")
        with patch.dict("os.environ", {
            "FROM_EMAIL": "sender@example.test", "TO_EMAIL": "recipient@example.test",
            "APP_PASSWORD": "fixture-password",
        }), patch.object(dongaupdate, "load_state", return_value={}), \
             patch.object(dongaupdate, "save_state") as save:
            self.assertEqual(dongaupdate.send_latest_ewhaian(), 1)
            save.assert_not_called()
        self.assertNotIn("private SMTP fixture", self.output.getvalue())

    def test_missing_credentials_skip_without_network_access(self):
        with patch.dict("os.environ", {"EWHA_PW": ""}):
            state = {self.key: "100"}
            dongaupdate.check_ewhaian_board(state)
        self.fetch.assert_not_called()
        self.mail.assert_not_called()
        self.assertEqual(state[self.key], "100")

    def test_login_failure_preserves_state(self):
        state = {self.key: "100"}
        self.fetch.side_effect = ewhaian.EwhaianError("로그인 실패")
        dongaupdate.check_ewhaian_board(state)
        self.assertEqual(state[self.key], "100")
        self.mail.assert_not_called()

    def test_other_site_failure_does_not_prevent_ewha_or_state_save(self):
        with patch.object(dongaupdate, "load_state", return_value={}), \
             patch.object(dongaupdate, "save_state") as save, \
             patch.object(dongaupdate, "check_donga_board", side_effect=RuntimeError), \
             patch.object(dongaupdate, "check_youtube_board") as youtube:
            self.fetch.return_value = [ewhaian.Post(102, "latest")]
            dongaupdate.main()
        youtube.assert_called()
        self.fetch.assert_called_once()
        save.assert_called_once_with({self.key: "102"})


if __name__ == "__main__":
    unittest.main()
