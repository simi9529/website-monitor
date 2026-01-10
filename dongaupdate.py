import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# =====================
# 환경 변수
# =====================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
USER_ID = os.environ.get("USER_ID")
USER_PW = os.environ.get("USER_PW")

STATE_FILE = "titles.json"

# =====================
# 감시 대상 사이트
# =====================
DONGA_BOARDS = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056",
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057",
    },
    {
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059",
    }
]

EWHAIAN_URL = "https://ewhaian.com/"
EWHAIAN_LOGIN_URL = "https://ewhaian.com/login"

# =====================
# 공통 유틸
# =====================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(FROM_EMAIL, APP_PASSWORD)
        server.send_message(msg)

# =====================
# 동아대 게시판 감시
# =====================
def check_donga_board(board, state):
    res = requests.get(board["url"], timeout=20)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    rows = soup.select("table.bdListTbl tbody tr")

    latest_display_num = None
    latest_board_seq = None
    latest_title = None
    latest_link = None

    for row in rows:
        num_td = row.select_one("td.num")
        subject_a = row.select_one("td.subject a")

        if not num_td or not subject_a:
            continue

        num_text = num_td.text.strip()

        # 공지글 제외 (숫자만 통과)
        if not num_text.isdigit():
            continue

        href = subject_a.get("href", "")
        if "board_seq=" not in href:
            continue

        latest_display_num = num_text
        latest_board_seq = href.split("board_seq=")[-1]
        latest_title = subject_a.text.strip()
        latest_link = urljoin(board["url"], href)
        break

    if not latest_board_seq:
        print(f"⚠️ [{board['name']}] 일반글 미검출")
        return

    last_seq = state.get(board["name"])

    if last_seq != latest_board_seq:
        body = (
            f"[{board['name']}]\n"
            f"게시판 번호: {latest_display_num}\n"
            f"제목: {latest_title}\n"
            f"링크: {latest_link}"
        )
        send_email(f"[새 글 알림] {board['name']}", body)
        state[board["name"]] = latest_board_seq
        print(f"🆕 [{board['name']}] 새 글 ({latest_display_num})")
    else:
        print(f"🔁 [{board['name']}] 변화 없음")

# =====================
# 이화이언 로그인 + 최신글 감시
# =====================
def check_ewhaian(state):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # 로그인
            page.goto(EWHAIAN_LOGIN_URL, wait_until="networkidle")
            page.fill('input[name="username"]', USER_ID)
            page.fill('input[name="password"]', USER_PW)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=30000)

            # 메인 이동
            page.goto(EWHAIAN_URL, wait_until="networkidle")
            page.wait_for_selector("ul.contentList li.contentItem", timeout=30000)

            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()

        item = soup.select_one("ul.contentList li.contentItem")
        if not item:
            print("⚠️ [이화이언] 최신글 없음")
            return

        title_tag = item.select_one("p.listTitle")
        link_tag = item.select_one("a")

        if not title_tag or not link_tag:
            print("⚠️ [이화이언] 파싱 실패")
            return

        title = title_tag.text.strip()
        link = urljoin(EWHAIAN_URL, link_tag.get("href"))

        last_title = state.get("이화이언")

        if last_title != title:
            body = (
                "[이화이언 최신글]\n"
                f"제목: {title}\n"
                f"링크: {link}"
            )
            send_email("[새 글 알림] 이화이언", body)
            state["이화이언"] = title
            print("🆕 [이화이언] 새 글")
        else:
            print("🔁 [이화이언] 변화 없음")

    except Exception as e:
        print(f"❌ [이화이언] 로그인/크롤링 실패: {e}")

# =====================
# 메인
# =====================
def main():
    state = load_state()

    for board in DONGA_BOARDS:
        check_donga_board(board, state)

    check_ewhaian(state)

    save_state(state)

if __name__ == "__main__":
    main()
