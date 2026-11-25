import contextlib
import io
import json
import unittest
from unittest.mock import Mock

from youtube_channel_live import CHANNEL, STATE_KEY, browse, monitor_channel_live


def page(items, context=False):
    data = {'contents': {'items': items}}
    config = '<script>ytcfg.set(' + json.dumps({'INNERTUBE_CONTEXT': {'client': {'clientName': 'WEB', 'clientVersion': 'fixture'}}}) + ');</script>' if context else ''
    return Mock(status_code=200, text=config + '<script>var ytInitialData = ' + json.dumps(data) + ';</script>')


def video(id, title='실시간 경쟁률 LIVE', active=True, upcoming=False):
    value = {'videoId': id, 'title': {'simpleText': title}, 'thumbnailOverlays': [
        {'thumbnailOverlayTimeStatusRenderer': {'style': 'LIVE' if active else 'DEFAULT'}}]}
    if upcoming:
        value['upcomingEventData'] = {'startTime': '9999999999'}
    return {'playlistVideoRenderer': value}


class ChannelLiveTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.board = {'name': '공모주투자'}

    def sources(self, playlist_items):
        data = {
            CHANNEL + '/streams': page([video('aaaaaaaaaaa')]),
            CHANNEL + '/playlists': page([{'playlistRenderer': {'playlistId': 'PLabcdefghijk'}}]),
            'https://www.youtube.com/playlist?list=PLabcdefghijk': page(playlist_items),
        }
        return Mock(side_effect=lambda url, name: data[url])

    def test_streams_and_playlists_deduplicate_and_only_notify_matching_active(self):
        get = self.sources([video('aaaaaaaaaaa', active=False), video('bbbbbbbbbbb', title='실시간경쟁률 LIVE'),
                            video('ccccccccccc', active=False), video('ddddddddddd', upcoming=True),
                            video('eeeeeeeeeee', title='비례배정 LIVE')])
        state = {}; notify = Mock()
        monitor_channel_live(self.board, state, get, notify)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(state[STATE_KEY]['notified_ids'], ['aaaaaaaaaaa', 'bbbbbbbbbbb'])
        monitor_channel_live(self.board, state, get, notify)
        self.assertEqual(notify.call_count, 2)

    def test_failed_send_does_not_acknowledge_and_old_channel_state_is_preserved(self):
        get = self.sources([video('aaaaaaaaaaa')])
        state = {'youtube_live_realtime_competition': {'notified_ids': ['oldoldoldol']}}
        notify = Mock(side_effect=RuntimeError('temporary'))
        monitor_channel_live(self.board, state, get, notify)
        self.assertNotIn(STATE_KEY, state)
        self.assertIn('youtube_live_realtime_competition', state)

    def test_continuation_page_is_read_with_public_context(self):
        first = page([{'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': 'next'}}}}], context=True)
        post = Mock(return_value=Mock(status_code=200))
        post.return_value.json.return_value = {'onResponseReceivedActions': [{'appendContinuationItemsAction': {
            'continuationItems': [video('aaaaaaaaaaa')]}}]}
        pages = list(browse(CHANNEL + '/streams', 'channel', Mock(return_value=first), post))
        self.assertEqual(len(pages), 2)
        self.assertEqual(post.call_args.kwargs['json']['continuation'], 'next')

    def test_incomplete_fetch_never_advances_state(self):
        state = {}; notify = Mock()
        monitor_channel_live(self.board, state, Mock(return_value=Mock(status_code=403)), notify)
        self.assertEqual(state, {})
        notify.assert_not_called()

    def test_filter_chip_commands_are_not_pagination(self):
        first = page([video('aaaaaaaaaaa'), {'chipCloudChipRenderer': {
            'navigationEndpoint': {'continuationCommand': {'token': 'live-filter'}}}}])
        post = Mock()
        pages = list(browse(CHANNEL + '/streams', 'channel', Mock(return_value=first), post))
        self.assertEqual(len(pages), 1)
        post.assert_not_called()
