import requests
from bs4 import BeautifulSoup
import smtplib
import ssl
from email.mime.text import MIMEText
import os
import json
import time
import re  # 유튜브 파싱을 위한 정규표현식 모듈 추가
from urllib.parse import parse_qs, urljoin, urlsplit
from requests.exceptions import ReadTimeout, RequestException
from ewhaian import EwhaianError, fetch_posts
from canvas_lms import CanvasClient, CanvasError, STATE_KEY as CANVAS_STATE_KEY, monitor_canvas, notification_body, notification_items
from canvas_sso import sso_session
from datetime import datetime, timedelta, timezone
from web_push import bind_delivery_state, dispatch, required_variables, test_push

# ======================
# 환경변수
# ======================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

STATE_FILE = "titles.json"

# 유튜브에서 봇으로 인식하지 않도록 헤더를 조금 더 보강했습니다
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

# ======================
# 동아대 게시판
# ======================
DONGA_BOARDS = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056"
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057"
    },
    {
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059"
    }
]

# ======================
# 유튜브 모니터링
# ======================
YOUTUBE_BOARDS = [
    {
        "name": "공모주린이",
        "url": "https://www.youtube.com/@%EA%B3%B5%EB%AA%A8%EC%A3%BC%EB%A6%B0%EC%9D%B4_0301/posts"
    },
     {
        "name": "공모주린이2",
        "url": "https://www.youtube.com/@%EA%B3%B5%EB%AA%A8%EC%A3%BC%EB%A6%B0%EC%9D%B42/posts"
    },
    {
        "name": "공모주투자의법칙",
        "url": "https://www.youtube.com/@%EA%B3%B5%EB%AA%A8%EC%A3%BC%ED%88%AC%EC%9E%90%EC%9D%98%EB%B2%95%EC%B9%99/posts"
    }
]

# ======================
# 상태
# ======================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ======================
# 이메일
# ======================
def send_email(subject, body, *, push_items=None):
    dispatch(subject, body, _send_smtp_email, push_items=push_items)


def _send_smtp_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, timeout=20, context=ssl.create_default_context()
    ) as server:
        server.login(FROM_EMAIL, APP_PASSWORD)
        server.send_message(msg)

# ======================
# 안전 요청 함수 (핵심)
# ======================
def safe_get(url, name, retries=3):
    for attempt in range(1, retries + 1):
        try:
            return requests.get(
                url,
                headers=HEADERS,
                timeout=(5, 20)  # 30초보다 안정적인 타임아웃
            )
        except ReadTimeout:
            print(f"⏳ [{name}] 응답 지연 ({attempt}/{retries})")
        except RequestException as e:
            print(f"⚠️ [{name}] 요청 오류 ({attempt}/{retries}): {e}")

        time.sleep(2)

    print(f"🚫 [{name}] 최종 실패 → 이번 회차 스킵")
    return None

# ======================
# 동아대 게시판 체크
# ======================
def check_donga_board(board, state):
    print(f"🔍 [{board['name']}] 확인 중...")

    res = safe_get(board["url"], board["name"])
    if res is None or res.status_code != 200:
        return

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("table.bdListTbl tbody tr")
    posts = {}
    for row in rows:
        num_td = row.select_one("td.num")
        subject_a = row.select_one("td.subject a")

        if not num_td or not subject_a:
            continue

        num = num_td.text.strip()

        # 공지 제외
        if not num.isdigit():
            continue

        href = subject_a.get("href", "")
        if "board_seq=" not in href:
            continue

        board_seq = parse_qs(urlsplit(href).query).get("board_seq", [""])[0]
        if not board_seq.isdigit():
            continue
        title = subject_a.text.strip()
        link = urljoin(board["url"], href)
        posts[int(board_seq)] = (num, title, link)
    last_seq = state.get(board["name"])
    if not posts:
        return
    pending = ([max(posts)] if last_seq is None else
               [seq for seq in sorted(posts) if seq > int(last_seq)])
    for seq in pending:
        num, title, link = posts[seq]
        body = f"[{board['name']}]\n\n번호: {num}\n제목: {title}\n\n링크: {link}"
        send_email(f"[동아대] {board['name']} 새 글", body,
                   push_items=[{"id": link, "title": title, "body": board['name'],
                                "links": [{"title": title, "url": link}]}])
        state[board["name"]] = str(seq)
    if not pending:
        print("🔁 변화 없음")

# ======================
# 유튜브 커뮤니티 체크 (신규)
# ======================
def youtube_posts(data):
    """Read posts from the selected posts tab, including modern rich grids."""
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    posts = {}

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("backstagePostRenderer", "postRenderer") and isinstance(child, dict) and child.get("postId"):
                    posts.setdefault(child["postId"], child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for tab in tabs:
        tab = tab.get("tabRenderer", {})
        url = tab.get("endpoint", {}).get("commandMetadata", {}).get("webCommandMetadata", {}).get("url", "")
        if "/posts" in url or "/community" in url or tab.get("selected"):
            walk(tab.get("content", {}))
    return list(posts.values())


def check_youtube_board(board, state):
    print(f"🔍 [{board['name']}] 유튜브 확인 중...")

    res = safe_get(board["url"], board["name"])
    if res is None or res.status_code != 200:
        return

    # 정규식으로 ytInitialData JSON 객체 추출
    match = re.search(r"var ytInitialData = (\{.*?\});</script>", res.text)
    if not match:
        print(f"⚠️ [{board['name']}] 데이터를 찾을 수 없습니다. (유튜브 차단 또는 구조 변경)")
        return

    try:
        yt_data = json.loads(match.group(1))

        posts = youtube_posts(yt_data)
        if not posts:
            print(f"⚠️ [{board['name']}] 게시물 목록이 비어있습니다.")
            return

        state_key = f"youtube_{board['name']}"
        last_post_id = state.get(state_key)
        if last_post_id is None:
            state[state_key] = posts[0]['postId']
            print(f"✅ [{board['name']}] 최초 확인 완료 → 다음 새 글부터 알림")
            return
        pending = []
        found_previous = False
        for post in posts:
            if post['postId'] == last_post_id:
                found_previous = True
                break
            pending.append(post)
        if last_post_id is not None and not found_previous:
            print(f"⚠️ [{board['name']}] 현재 목록에서 이전 글을 찾지 못했습니다 → 기준 유지")
            return
        for post in reversed(pending):
            post_id = post['postId']

            # 여러 줄로 나뉜 텍스트 합치기
            runs = post.get("contentText", {}).get("runs", [])
            text_content = "".join([r.get("text", "") for r in runs]).strip()
            preview_text = text_content[:30] + "..." if len(text_content) > 30 else text_content

            post_link = f"https://www.youtube.com/post/{post_id}"
            body = (f"[{board['name']} 유튜브 새 커뮤니티 글]\n\n"
                    f"내용:\n{text_content}\n\n링크: {post_link}")
            send_email(f"[유튜브] {board['name']} 새 글", body)
            state[state_key] = post_id
    except Exception as e:
        print(f"⚠️ [{board['name']}] 파싱 중 오류 발생: {e}")

# ======================
# 이화이언 로그인 게시판
# ======================
EWHA_STATE_KEY = "ewhaian_life_66"


def send_ewhaian_digest(posts, test=False):
    posts = [post for post in posts if "과외" not in post.title]
    if not posts:
        return
    entries = "\n\n".join(
        f"{index}. {post.title}\n{post.url}"
        for index, post in enumerate(posts, start=1)
    )
    subject = (
        "[이화이언] life/66 최신 글 — 시험 발송"
        if test else f"[이화이언] life/66 새 글 {len(posts)}개"
    )
    send_email(subject, f"[이화이언 life/66]\n\n게시글 {len(posts)}개\n\n{entries}",
               push_items=[{"id": post.url, "title": post.title, "body": "이화이언 life/66",
                            "links": [{"title": post.title, "url": post.url}]} for post in posts])


def check_ewhaian_board(state):
    username = os.environ.get("EWHA_ID")
    password = os.environ.get("EWHA_PW")
    if not username or not password:
        print("⏭ [이화이언] EWHA_ID 또는 EWHA_PW 미설정 → 스킵")
        return

    previous = state.get(EWHA_STATE_KEY)
    last_seen = int(previous) if str(previous).isdigit() else None
    try:
        posts = fetch_posts(username, password, last_seen)
    except EwhaianError as error:
        print(f"⚠️ [이화이언] {error}")
        return

    if not posts:
        print("🔁 [이화이언] 새 글 없음")
        return
    if last_seen is None:
        # Start with the current newest post; do not email historical posts.
        state[EWHA_STATE_KEY] = str(posts[-1].id)
        print("✅ [이화이언] 최초 확인 완료 → 다음 새 글부터 알림")
        return

    eligible = [post for post in posts if "과외" not in post.title]
    try:
        if eligible:
            send_ewhaian_digest(eligible)
    except Exception:
        # Retry the whole digest without losing any unsent post links.
        print("⚠️ [이화이언] 알림 발송 실패 → 모든 미발송 글을 다음 회차에 재시도")
        return
    state[EWHA_STATE_KEY] = str(posts[-1].id)
    print(f"✅ [이화이언] 알림 {len(eligible)}개, 제목에 과외 포함 {len(posts) - len(eligible)}개 제외")


def send_latest_ewhaian():
    """Send one real test message and initialize a missing local checkpoint."""
    required = ["EWHA_ID", "EWHA_PW"] + required_variables()
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print("시험 발송 불가: 실행 환경에 없는 변수: " + ", ".join(missing))
        return 2
    try:
        state = load_state()
        bind_delivery_state(state)
        posts = fetch_posts(os.environ["EWHA_ID"], os.environ["EWHA_PW"])
        if not posts:
            print("시험 발송 불가: 최신 게시글을 찾지 못했습니다")
            return 1
        latest = posts[-1]
        send_ewhaian_digest([latest], test=True)
    except EwhaianError as error:
        print(f"시험 발송 실패: {error}")
        return 1
    except Exception as error:
        print(f"시험 발송 실패: {type(error).__name__} (인증 정보는 출력하지 않습니다)")
        return 1
    print("✅ 실제 로그인 후 최신 글 링크를 포함한 시험 알림을 전송했습니다")
    # Do not skip previously unnotified posts if a monitor is already running.
    if not str(state.get(EWHA_STATE_KEY)).isdigit():
        state[EWHA_STATE_KEY] = str(latest.id)
        try:
            save_state(state)
        except Exception:
            print("⚠️ 메일은 전달됐지만 모니터링 시작 기준을 저장하지 못했습니다")
            return 1
    return 0


# ======================
# 동아대 Canvas: 공지사항 + 대화메시지
# ======================
def check_canvas_board(state):
    username, password = os.environ.get("CANVAS_ID"), os.environ.get("CANVAS_PW")
    if not username or not password:
        print("⏭ [Canvas] CANVAS_ID 또는 CANVAS_PW 미설정 → 스킵")
        return
    try:
        with sso_session(username, password) as session:
            monitor_canvas(CanvasClient(session), state, send_email)
    except CanvasError as error:
        print(f"⚠️ [Canvas] {error}")


def send_latest_canvas():
    required = ["CANVAS_ID", "CANVAS_PW"] + required_variables()
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print("Canvas 시험 발송 불가: 실행 환경에 없는 변수: " + ", ".join(missing))
        return 2
    try:
        state = load_state()
        bind_delivery_state(state)
        now = datetime.now(timezone.utc)
        with sso_session(os.environ["CANVAS_ID"], os.environ["CANVAS_PW"]) as session:
            client = CanvasClient(session)
            notices, notice_state = client.poll_announcements({
                "seen_ids": [], "checked_at": (now - timedelta(days=180)).isoformat(),
            }, now=now)
            messages, message_state = client.poll_messages({
                "conversations": {}, "checked_at": "1970-01-01T00:00:00+00:00",
            }, now=now)
        samples = [max(events, key=lambda event: (event.created_at, event.url))
                   for events in (notices, messages) if events]
        if not samples:
            print("✅ Canvas 로그인과 두 영역 조회 성공. 시험 알림에 담을 항목이 없어 발송하지 않았습니다")
            return 0
        send_email("[동아대 Canvas] 공지·대화 확인 — 시험 발송", notification_body(samples),
                   push_items=notification_items(samples))
    except CanvasError as error:
        print(f"Canvas 시험 발송 실패: {error}")
        return 1
    except Exception as error:
        print(f"Canvas 시험 발송 실패: {type(error).__name__} (인증 정보는 출력하지 않습니다)")
        return 1
    print("✅ Canvas 최신 항목 시험 알림을 전송했습니다")
    # Preserve established checkpoints so testing never discards pending alerts.
    baseline = state.setdefault(CANVAS_STATE_KEY, {})
    baseline.setdefault("announcements", notice_state)
    baseline.setdefault("messages", message_state)
    try:
        save_state(state)
    except Exception:
        print("⚠️ Canvas 알림은 전달됐지만 시작 기준을 저장하지 못했습니다")
        return 1
    return 0


# ======================
# 메인 (최후 안전망)
# ======================
def main():
    try:
        state = load_state()
        bind_delivery_state(state)
        
        # 동아대 점검
        for board in DONGA_BOARDS:
            try:
                check_donga_board(board, state)
            except Exception:
                print(f"⚠️ [{board['name']}] 확인 실패 → 다음 사이트 계속")
            
        # 유튜브 점검
        for yt in YOUTUBE_BOARDS:
            try:
                check_youtube_board(yt, state)
            except Exception:
                print(f"⚠️ [{yt['name']}] 확인 실패 → 다음 사이트 계속")

        # 로그인 실패가 기존 모니터링에 영향을 주지 않도록 분리
        try:
            check_ewhaian_board(state)
        except Exception:
            print("⚠️ [이화이언] 확인 실패 → 기존 사이트 상태는 저장")

        try:
            check_canvas_board(state)
        except Exception:
            print("⚠️ [Canvas] 확인 실패 → 기존 사이트 상태는 저장")
            
        save_state(state)
    except Exception as e:
        print("🔥 치명적 예외 발생 (강제 종료 방지)")
        print(e)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--send-latest-ewhaian", action="store_true",
        help="실제 계정으로 로그인해 최신 글 링크를 담은 시험 메일 1통을 발송",
    )
    mode.add_argument(
        "--test-canvas", action="store_true",
        help="학교 통합 로그인 후 Canvas의 최신 공지·수신 메시지 링크를 시험 메일로 발송",
    )
    mode.add_argument("--test-push", action="store_true", help="사이트 로그인 없이 크롬 연결 시험 알림 발송")
    args = parser.parse_args()
    if args.test_push:
        raise SystemExit(test_push())
    if args.send_latest_ewhaian:
        raise SystemExit(send_latest_ewhaian())
    if args.test_canvas:
        raise SystemExit(send_latest_canvas())
    main()
