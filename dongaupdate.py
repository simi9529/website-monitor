import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
import time
import re  # 유튜브 파싱을 위한 정규표현식 모듈 추가
from urllib.parse import urljoin
from requests.exceptions import ReadTimeout, RequestException

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
        "name": "공모주린이0301",
        "url": "https://www.youtube.com/@%EA%B3%B5%EB%AA%A8%EC%A3%BC%EB%A6%B0%EC%9D%B40301/posts"
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
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
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

        board_seq = href.split("board_seq=")[-1]
        title = subject_a.text.strip()
        link = urljoin(board["url"], href)

        last_seq = state.get(board["name"])

        if last_seq != board_seq:
            print(f"🆕 새 글 감지: {title}")
            body = (
                f"[{board['name']}]\n\n"
                f"번호: {num}\n"
                f"제목: {title}\n\n"
                f"링크: {link}"
            )
            send_email(f"[동아대] {board['name']} 새 글", body)
            state[board["name"]] = board_seq
        else:
            print("🔁 변화 없음")

        break  # 최신 일반글 1개만 확인

# ======================
# 유튜브 커뮤니티 체크 (신규)
# ======================
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

        # 탭 목록에서 posts 탭 컨텐츠 찾기
        tabs = yt_data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
        community_items = []

        for tab in tabs:
            tab_url = tab.get("tabRenderer", {}).get("endpoint", {}).get("commandMetadata", {}).get("webCommandMetadata", {}).get("url", "")
            if "/posts" in tab_url or "/community" in tab_url:
                community_items = tab["tabRenderer"].get("content", {}).get("sectionListRenderer", {}).get("contents", [])[0].get("itemSectionRenderer", {}).get("contents", [])
                break

        if not community_items:
            print(f"⚠️ [{board['name']}] 게시물 목록이 비어있습니다.")
            return

        for item in community_items:
            if "backstagePostThreadRenderer" in item:
                post = item["backstagePostThreadRenderer"]["post"]["backstagePostRenderer"]
                post_id = post.get("postId", "")

                # 여러 줄로 나뉜 텍스트 합치기
                runs = post.get("contentText", {}).get("runs", [])
                text_content = "".join([r.get("text", "") for r in runs]).strip()
                preview_text = text_content[:30] + "..." if len(text_content) > 30 else text_content

                post_link = f"https://www.youtube.com/post/{post_id}"
                state_key = f"youtube_{board['name']}"
                last_post_id = state.get(state_key)

                if last_post_id != post_id:
                    print(f"🆕 유튜브 새 글 감지: {preview_text}")
                    body = (
                        f"[{board['name']} 유튜브 새 커뮤니티 글]\n\n"
                        f"내용:\n{text_content}\n\n"
                        f"링크: {post_link}"
                    )
                    send_email(f"[유튜브] {board['name']} 새 글", body)
                    state[state_key] = post_id
                else:
                    print("🔁 유튜브 변화 없음")

                break  # 최신 글 1개만 확인

    except Exception as e:
        print(f"⚠️ [{board['name']}] 파싱 중 오류 발생: {e}")

# ======================
# 메인 (최후 안전망)
# ======================
def main():
    try:
        state = load_state()
        
        # 동아대 점검
        for board in DONGA_BOARDS:
            check_donga_board(board, state)
            
        # 유튜브 점검
        for yt in YOUTUBE_BOARDS:
            check_youtube_board(yt, state)
            
        save_state(state)
    except Exception as e:
        print("🔥 치명적 예외 발생 (강제 종료 방지)")
        print(e)

if __name__ == "__main__":
    main()
