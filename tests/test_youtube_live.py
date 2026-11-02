import contextlib
import io
import json
import unittest
from unittest.mock import Mock

from youtube_live import STATE_KEY, monitor_live


class LiveTests(unittest.TestCase):
    def run_check(self, state, notify, entries):
        data = {'contents': {'items': [{'videoRenderer': item} for item in entries]}}
        response = Mock(status_code=200, text='<script>var ytInitialData = '+json.dumps(data)+';</script>')
        with contextlib.redirect_stdout(io.StringIO()):
            monitor_live({'name': 'channel', 'url': 'https://www.youtube.com/channel/streams'}, state, Mock(return_value=response), notify)

    def video(self, name, title, live=False, upcoming=False):
        item = {'videoId': name, 'title': {'simpleText': title}, 'thumbnailOverlays': [
            {'thumbnailOverlayTimeStatusRenderer': {'style': 'LIVE' if live else 'DEFAULT'}}]}
        if upcoming:
            item['upcomingEventData'] = {'startTime': '9999999999'}
        return item

    def test_only_matching_current_live_alerts_once(self):
        entries = [self.video('aaaaaaaaaaa', '비례배정 안내', True),
                   self.video('bbbbbbbbbbb', '비례배정 LIVE 지난 방송'),
                   self.video('ccccccccccc', '비례배정 예정', True, True),
                   self.video('ddddddddddd', '다른 방송', True)]
        state = {}; notify = Mock()
        self.run_check(state, notify, entries)
        notify.assert_called_once()
        self.assertIn('watch?v=aaaaaaaaaaa', notify.call_args.args[1])
        self.run_check(state, notify, entries)
        notify.assert_called_once()

    def test_upcoming_can_later_become_live_and_failed_send_retries(self):
        state = {}; notify = Mock()
        self.run_check(state, notify, [self.video('aaaaaaaaaaa', '비례배정', True, True)])
        notify.assert_not_called()
        notify.side_effect = RuntimeError('temporary')
        self.run_check(state, notify, [self.video('aaaaaaaaaaa', '비례배정', True)])
        self.assertNotIn(STATE_KEY, state)
        notify.side_effect = None
        self.run_check(state, notify, [self.video('aaaaaaaaaaa', '비례배정', True)])
        self.assertEqual(state[STATE_KEY]['notified_ids'], ['aaaaaaaaaaa'])
