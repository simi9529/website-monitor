from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import unittest
from unittest.mock import MagicMock, patch

from mail_cleanup import CleanupError, MONITOR_HEADER, MONITOR_ID, cleanup_mail, is_monitor_mail, main


NOW = datetime(2026, 10, 25, 3, tzinfo=timezone.utc)
SENDER = 'monitor@example.com'
RECIPIENT = 'owner@kakao.com'


def message(subject='[동아대 Canvas] 새 알림 2개', marker=False):
    msg = EmailMessage()
    msg['From'] = SENDER
    msg['To'] = RECIPIENT
    msg['Subject'] = subject
    if marker:
        msg[MONITOR_HEADER] = MONITOR_ID
    msg.set_content('본문')
    return msg


def fetched(uid, date, msg):
    metadata = f'1 (UID {uid} INTERNALDATE "{date.strftime("%d-%b-%Y %H:%M:%S %z")}" BODY[HEADER.FIELDS] {{100}})'
    return 'OK', [(metadata.encode(), msg.as_bytes()), b')']


class CleanupTests(unittest.TestCase):
    def connection(self, mails):
        connection = MagicMock()
        connection.capabilities = (b'IMAP4rev1', b'MOVE')
        connection.select.return_value = ('OK', [b'10'])
        connection.list.return_value = ('OK', [b'(\\Sent) "/" "Sent"', b'(\\Trash) "/" "Trash"'])

        def uid(command, *args):
            if command == 'SEARCH':
                return 'OK', [' '.join(mails).encode()]
            if command == 'FETCH':
                key = args[0].decode()
                date, msg = mails[key]
                return fetched(key, date, msg)
            return 'OK', [b'done']
        connection.uid.side_effect = uid
        return connection

    def test_only_old_monitor_messages_move_regardless_of_seen_flag(self):
        other = message('친구의 메일')
        wrong_sender = message()
        wrong_sender.replace_header('From', 'someone@example.com')
        connection = self.connection({
            '10': (NOW - timedelta(hours=25), message()),
            '11': (NOW - timedelta(hours=23, minutes=59), message()),
            '12': (NOW - timedelta(days=2), other),
            '13': (NOW - timedelta(days=2), wrong_sender),
            '14': (NOW - timedelta(hours=24), message('새 형식', marker=True)),
        })
        self.assertEqual(cleanup_mail(connection, SENDER, RECIPIENT, apply=True, now=NOW), (2, 2))
        moves = [call.args for call in connection.uid.call_args_list if call.args[0] == 'MOVE']
        self.assertEqual(moves, [('MOVE', b'10', b'"Trash"'), ('MOVE', b'14', b'"Trash"')])
        search = connection.uid.call_args_list[0].args
        self.assertNotIn('SEEN', search)
        self.assertNotIn('UNSEEN', search)
        fetches = [call.args for call in connection.uid.call_args_list if call.args[0] == 'FETCH']
        self.assertTrue(all('BODY.PEEK' in call[2] for call in fetches))
        connection.expunge.assert_not_called()
        connection.close.assert_not_called()

    def test_default_preview_selects_readonly_and_never_changes_mail(self):
        connection = self.connection({'1': (NOW - timedelta(days=2), message())})
        self.assertEqual(cleanup_mail(connection, SENDER, RECIPIENT, now=NOW), (1, 0))
        connection.select.assert_called_once_with('INBOX', readonly=True)
        self.assertEqual([call.args[0] for call in connection.uid.call_args_list], ['SEARCH', 'FETCH'])

    def test_uidplus_fallback_expunge_targets_only_copied_uid(self):
        connection = self.connection({'1': (NOW - timedelta(days=2), message())})
        connection.capabilities = (b'IMAP4rev1', b'UIDPLUS')
        self.assertEqual(cleanup_mail(connection, SENDER, RECIPIENT, apply=True, now=NOW), (1, 1))
        calls = [call.args for call in connection.uid.call_args_list][2:]
        self.assertEqual(calls, [('COPY', b'1', b'"Trash"'),
                                 ('STORE', b'1', '+FLAGS.SILENT', '(\\Deleted)'), ('EXPUNGE', b'1')])
        connection.expunge.assert_not_called()

    def test_korean_trash_name_without_special_use_flag_is_supported(self):
        import base64
        name = b'&' + base64.b64encode('휴지통'.encode('utf-16be')).rstrip(b'=') + b'-'
        connection = self.connection({'1': (NOW - timedelta(days=2), message())})
        connection.list.return_value = ('OK', [b'(\\HasNoChildren) "/" "' + name + b'"'])
        self.assertEqual(cleanup_mail(connection, SENDER, RECIPIENT, apply=True, now=NOW), (1, 1))
        self.assertEqual(connection.uid.call_args.args, ('MOVE', b'1', b'"' + name + b'"'))

    def test_failed_copy_never_flags_or_expunge_original(self):
        connection = self.connection({'1': (NOW - timedelta(days=2), message())})
        connection.capabilities = (b'UIDPLUS',)
        original = connection.uid.side_effect
        connection.uid.side_effect = lambda command, *args: ('NO', [b'private error']) if command == 'COPY' else original(command, *args)
        with self.assertRaises(CleanupError):
            cleanup_mail(connection, SENDER, RECIPIENT, apply=True, now=NOW)
        self.assertNotIn('STORE', [call.args[0] for call in connection.uid.call_args_list])
        self.assertNotIn('EXPUNGE', [call.args[0] for call in connection.uid.call_args_list])

    def test_missing_trash_or_safe_move_capability_causes_no_mutation(self):
        for no_trash in (True, False):
            connection = self.connection({'1': (NOW - timedelta(days=2), message())})
            if no_trash:
                connection.list.return_value = ('OK', [b'() "/" "INBOX"'])
            else:
                connection.capabilities = (b'IMAP4rev1',)
            with self.assertRaises(CleanupError):
                cleanup_mail(connection, SENDER, RECIPIENT, apply=True, now=NOW)
            self.assertEqual([call.args[0] for call in connection.uid.call_args_list], ['SEARCH', 'FETCH'])

    def test_exact_recipient_subject_and_marker_are_required(self):
        for subject in ['Re: [동아대 Canvas] 새 알림 2개', '[동아대] 일반 메일', '[유튜브] 다른 채널 새 글']:
            self.assertFalse(is_monitor_mail(message(subject), SENDER, RECIPIENT))
        msg = message()
        msg.replace_header('To', 'other@kakao.com')
        self.assertFalse(is_monitor_mail(msg, SENDER, RECIPIENT))
        msg = message(marker=True)
        msg.replace_header(MONITOR_HEADER, 'other-monitor')
        self.assertFalse(is_monitor_mail(msg, SENDER, RECIPIENT))
        for subject in ['[동아대] 동아대 law 수업공지 새 글', '[유튜브] 공모주린이2 새 글',
                        '[이화이언] life/66 새 글 2개', '[이화이언] life/66 최신 글 — 시험 발송']:
            self.assertTrue(is_monitor_mail(message(subject), SENDER, RECIPIENT))

    @patch('mail_cleanup.imaplib.IMAP4_SSL')
    def test_missing_password_does_not_connect(self, connect):
        with patch.dict('os.environ', {'KAKAO_IMAP_PASSWORD': ''}):
            self.assertEqual(main([]), 2)
        connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
