import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import dongaupdate


class PublicNotificationsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.get = self.stack.enter_context(patch('dongaupdate.safe_get'))
        self.send = self.stack.enter_context(patch('dongaupdate.send_email'))

    def test_two_donga_posts_each_trigger_one_notification(self):
        self.get.return_value = Mock(status_code=200, text='<table class="bdListTbl"><tbody>' + ''.join(
            f'<tr><td class="num">{i}</td><td class="subject"><a href="?board_seq={i}&amp;mCode=test">글{i}</a></td></tr>'
            for i in [102, 101, 100]) + '</tbody></table>')
        board = dongaupdate.DONGA_BOARDS[0]
        state = {board['name']: '100'}
        dongaupdate.check_donga_board(board, state)
        self.assertEqual(self.send.call_count, 2)
        self.assertIn('board_seq=101', self.send.call_args_list[0].args[1])
        self.assertIn('board_seq=102', self.send.call_args_list[1].args[1])
        self.assertTrue(all(len(call.kwargs['push_items']) == 1 for call in self.send.call_args_list))
        self.assertEqual(state[board['name']], '102')

    def test_two_youtube_posts_each_trigger_one_notification(self):
        items = [{'backstagePostThreadRenderer': {'post': {'backstagePostRenderer': {
            'postId': str(i), 'contentText': {'runs': [{'text': f'새 글{i}'}]}
        }}}} for i in [102, 101, 100]]
        data = {'contents': {'twoColumnBrowseResultsRenderer': {'tabs': [{'tabRenderer': {
            'endpoint': {'commandMetadata': {'webCommandMetadata': {'url': '/channel/posts'}}},
            'content': {'sectionListRenderer': {'contents': [{'itemSectionRenderer': {'contents': items}}]}}
        }}]}}}
        self.get.return_value = Mock(status_code=200, text='<script>var ytInitialData = ' + json.dumps(data) + ';</script>')
        board = dongaupdate.YOUTUBE_BOARDS[0]
        key = 'youtube_' + board['name']
        state = {key: '100'}
        dongaupdate.check_youtube_board(board, state)
        self.assertEqual(self.send.call_count, 2)
        self.assertIn('/post/101', self.send.call_args_list[0].args[1])
        self.assertIn('/post/102', self.send.call_args_list[1].args[1])
        self.assertEqual(state[key], '102')

    def test_donga_partial_failure_does_not_skip_second_post(self):
        self.get.return_value = Mock(status_code=200, text='<table class="bdListTbl"><tbody>' + ''.join(
            f'<tr><td class="num">{i}</td><td class="subject"><a href="?board_seq={i}">글</a></td></tr>'
            for i in [102, 101, 100]) + '</tbody></table>')
        self.send.side_effect = [None, RuntimeError('temporary')]
        board = dongaupdate.DONGA_BOARDS[0]
        state = {board['name']: '100'}
        with self.assertRaises(RuntimeError):
            dongaupdate.check_donga_board(board, state)
        self.assertEqual(state[board['name']], '101')

    def test_new_youtube_channel_baseline_reads_modern_grid_without_old_notifications(self):
        posts = [{'postRenderer': {'postId': 'latest', 'contentText': {'runs': [{'text': '최신 글'}]}}},
                 {'postRenderer': {'postId': 'older', 'contentText': {'runs': []}}}]
        data = {'contents': {'twoColumnBrowseResultsRenderer': {'tabs': [{'tabRenderer': {
            'selected': True, 'content': {'richGridRenderer': {'contents': [
                {'richItemRenderer': {'content': post}} for post in posts
            ]}}
        }}]}}}
        self.get.return_value = Mock(status_code=200, text='<script>var ytInitialData = ' + json.dumps(data) + ';</script>')
        board = next(board for board in dongaupdate.YOUTUBE_BOARDS if board['name'] == '공모주투자의법칙')
        state = {}
        dongaupdate.check_youtube_board(board, state)
        self.assertEqual(state['youtube_공모주투자의법칙'], 'latest')
        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
