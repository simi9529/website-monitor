"""Move only this monitor's Kakao inbox mail older than 24 hours to Trash.

Default execution is a read-only preview. Never use mailbox-wide EXPUNGE or
CLOSE: those could permanently remove mail deleted by another email client.
"""

import argparse
import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import imaplib
import os
import re
import ssl


MONITOR_HEADER = "X-Website-Monitor"
MONITOR_ID = "simi9529/website-monitor"
MAX_CANDIDATES = 1000


class CleanupError(RuntimeError):
    """An error that contains no credentials or mailbox content."""


def _address(value):
    addresses = getaddresses([value or ""])
    if (len(addresses) != 1 or not addresses[0][1]
            or not re.fullmatch(r"[^\s<>\"\\@]+@[^\s<>\"\\@]+", addresses[0][1])):
        raise CleanupError("FROM_EMAIL 또는 TO_EMAIL 주소 설정을 확인하세요")
    return addresses[0][1].lower()


def _addresses(message, field):
    return [address.lower() for _, address in getaddresses(message.get_all(field, []))]


def is_monitor_mail(message, sender, recipient):
    if _addresses(message, "From") != [sender] or _addresses(message, "To") != [recipient]:
        return False
    markers = message.get_all(MONITOR_HEADER, [])
    if markers:
        return len(markers) == 1 and str(markers[0]) == MONITOR_ID
    # Match the exact old subject formats so mail sent before the marker was
    # introduced can also be cleaned up. Forwarded/replied mail is excluded.
    subject = str(message.get("Subject", ""))
    if subject in {
        "[동아대 Canvas] 공지·대화 확인 — 시험 발송",
        "[이화이언] life/66 최신 글 — 시험 발송",
        *{f"[동아대] 동아대 law {name} 새 글"
          for name in ("학사공지", "수업공지", "특강및 모의고사")},
        *{f"[유튜브] {name} 새 글" for name in ("공모주린이", "공모주린이2", "공모주투자의법칙")},
    }:
        return True
    return bool(re.fullmatch(
        r"(?:\[동아대 Canvas\] 새 알림|\[이화이언\] life/66 새 글) [1-9][0-9]*개", subject
    ))


def _ok(result):
    status, data = result
    if status != "OK":
        raise CleanupError("카카오메일 IMAP 명령이 실패했습니다. 메일 원본을 확인하세요")
    return data


def _trash_folder(connection):
    candidates = []
    korean_name = b"&" + base64.b64encode("휴지통".encode("utf-16be")).rstrip(b"=").replace(b"/", b",") + b"-"
    for row in _ok(connection.list()):
        if not isinstance(row, bytes):
            continue
        match = re.fullmatch(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(.+)', row)
        if not match or b"\\noselect" in match[1].lower().split():
            continue
        if b"\\trash" in match[1].lower().split():
            # Preserve the server's quoting and modified UTF-7 mailbox name.
            return match[2]
        name = match[2].strip(b'"')
        if name.lower() == b"trash" or name in (korean_name, "휴지통".encode()):
            candidates.append(match[2])
    if len(candidates) == 1:
        return candidates[0]
    raise CleanupError("서버의 휴지통 폴더를 확인하지 못했습니다. 메일을 이동하지 않았습니다")


def _fetch_candidate(connection, uid, cutoff, sender, recipient):
    data = _ok(connection.uid(
        "FETCH", uid,
        "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT X-WEBSITE-MONITOR)])",
    ))
    for row in data:
        if not isinstance(row, tuple) or len(row) != 2:
            continue
        metadata, headers = row
        date = re.search(rb'INTERNALDATE "([^"]+)"', metadata)
        fetched_uid = re.search(rb'\bUID ([0-9]+)\b', metadata)
        if not date or not fetched_uid or fetched_uid[1] != uid:
            raise CleanupError("메일 수신 시각 또는 UID를 확인하지 못했습니다")
        try:
            received = parsedate_to_datetime(date[1].decode("ascii"))
        except (ValueError, TypeError, UnicodeError):
            raise CleanupError("메일 수신 시각 형식을 확인하지 못했습니다") from None
        if received.tzinfo is None or received > cutoff:
            return False
        message = BytesParser(policy=policy.default).parsebytes(headers)
        return is_monitor_mail(message, sender, recipient)
    # A mail removed concurrently by another client needs no further action.
    return False


def cleanup_mail(connection, sender, recipient, apply=False, now=None):
    sender, recipient = _address(sender), _address(recipient)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=24)
    _ok(connection.select("INBOX", readonly=not apply))
    # IMAP BEFORE only compares calendar dates; inspect INTERNALDATE below for
    # the exact 24-hour cutoff. Include timezone boundary days in the search.
    before = (cutoff + timedelta(days=2)).strftime("%d-%b-%Y")
    result = _ok(connection.uid("SEARCH", None, "FROM", '"' + sender + '"', "BEFORE", before))
    uids = result[0].split() if result and result[0] else []
    if len(uids) > MAX_CANDIDATES:
        raise CleanupError("조회 대상이 1000통을 초과했습니다. 대상 범위를 확인해야 합니다")
    if any(not re.fullmatch(rb"[1-9][0-9]*", uid) for uid in uids):
        raise CleanupError("메일 UID 형식을 확인하지 못했습니다")
    candidates = [uid for uid in uids if _fetch_candidate(connection, uid, cutoff, sender, recipient)]
    if not apply or not candidates:
        return len(candidates), 0
    capabilities = {value.upper() for value in connection.capabilities}
    if b"MOVE" not in capabilities and b"UIDPLUS" not in capabilities:
        raise CleanupError("안전한 이동에 필요한 MOVE / UIDPLUS가 없습니다. 이동하지 않았습니다")
    trash = _trash_folder(connection)
    moved = 0
    for uid in candidates:
        if b"MOVE" in capabilities:
            _ok(connection.uid("MOVE", uid, trash))
        else:
            _ok(connection.uid("COPY", uid, trash))
            _ok(connection.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)"))
            # UID EXPUNGE removes only the specific message copied to Trash.
            _ok(connection.uid("EXPUNGE", uid))
        moved += 1
    return len(candidates), moved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="대상 메일을 실제로 휴지통으로 이동")
    args = parser.parse_args(argv)
    password = os.environ.get("KAKAO_IMAP_PASSWORD")
    if not password:
        print("카카오메일 정리 미실행: KAKAO_IMAP_PASSWORD가 필요합니다")
        return 2
    connection = None
    try:
        recipient = _address(os.environ.get("TO_EMAIL"))
        sender = _address(os.environ.get("FROM_EMAIL"))
        if recipient.split("@", 1)[1] != "kakao.com":
            raise CleanupError("TO_EMAIL이 카카오메일 주소가 아닙니다")
        username = os.environ.get("KAKAO_IMAP_ID") or recipient.split("@", 1)[0]
        connection = imaplib.IMAP4_SSL("imap.kakao.com", 993, ssl_context=ssl.create_default_context(), timeout=20)
        connection.login(username, password)
        connection.capabilities = tuple(b" ".join(_ok(connection.capability())).upper().split())
        eligible, moved = cleanup_mail(connection, sender, recipient, apply=args.apply)
        print(f"✅ 카카오메일 정리: 24시간 지난 모니터링 메일 {eligible}통, 휴지통 이동 {moved}통"
              + ("" if args.apply else " (미리보기: 변경 없음)"))
        return 0
    except CleanupError as error:
        print(f"카카오메일 정리 중단: {error}")
    except Exception as error:
        print(f"카카오메일 정리 실패: {type(error).__name__} (계정·메일 내용은 출력하지 않습니다)")
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
