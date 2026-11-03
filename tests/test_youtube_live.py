import contextlib
import io
import json
import unittest
from unittest.mock import Mock

from youtube_live import STATE_KEY, monitor_live


class LiveTests(unittest.TestCase):
    def test_real_modern_live_badge_detects_matching_broadcast_not_recording(self):
        from youtube_live import live_streams
        def item(video_id, title, style):
            return {'lockupViewModel': {'contentId': video_id, 'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO',
                'metadata': {'lockupMetadataViewModel': {'title': {'content': title}}},
                'contentImage': {'thumbnailViewModel': {'overlays': [{'thumbnailBadgeViewModel': {
                    'text': '라이브', 'badgeStyle': style,
                    'icon': {'sources': [{'clientResource': {'imageName': 'LIVE'}}]}
                }}]}}}}
        data = {'contents': {'items': [item('O_byZegF9TQ', '[비례배정 LIVE] 동원파츠', 'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE'),
                             item('aaaaaaaaaaa', '비례배정 LIVE 지난 방송', 'THUMBNAIL_OVERLAY_BADGE_STYLE_DEFAULT')]}}
        result = live_streams(data)
        self.assertTrue(result[0]['active'])
        self.assertFalse(result[1]['active'])

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
