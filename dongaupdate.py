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
# 감시 대상
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# =====================
# 공통
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
# 동아대 게시판
# =====================
def check_donga_board(board, state):
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        res = session.get(board["url"], timeout=40)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.select("table.bdListTbl tbody tr")

        for row in rows:
            num_td = row.select_one("td.num")
            subject_a = row.select_one("td.subject a")

            if not num_td or not subject_a:
                continue

            num_text = num_td.text.strip()

            # 공지 제외
            if not num_text.isdigit():
                continue

            href = subject_a.get("href", "")
            if "board_seq=" not in href:
                continue

            board_seq = href.split("board_seq=")[-1]
            title = subject_a.text.strip()
            link = urljoin(board["url"], href)

            last_seq = state.get(board["name"])
            if last_seq != board_seq:
                body = (
                    f"[{board['name']}]\n"
                    f"게시판 번호: {num_text}\n"
                    f"제목: {title}\n"
                    f"링크: {link}"
                )
                send_email(f"[새 글 알림] {board['name']}", body)
                state[board["name"]] = board_seq
                print(f"🆕 [{board['name']}] 새 글 {num_text}")
            else:
                print(f"🔁 [{board['name']}] 변화 없음")
            return

        print(f"⚠️ [{board['name']}] 일반글 없음")

    except Exception as e:
        print(f"⚠️ [{board['name']}] 접속 실패 (무시하고 계속): {e}")

# =====================
# 이화이언
# =====================
def check_ewhaian(state):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.goto(EWHAIAN_LOGIN_URL, wait_until="networkidle")
            page.fill('input[name="username"]', USER_ID)
            page.fill('input[name="password"]', USER_PW)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=30000)

            page.goto(EWHAIAN_URL, wait_until="networkidle")
            page.wait_for_selector("ul.contentList li.contentItem", timeout=30000)

            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()

        item = soup.select_one("ul.contentList li.contentItem")
        if not item:
            print("⚠️ [이화이언] 최신글 없음")
            return

        title = item.select_one("p.listTitle").text.strip()
        link = urljoin(EWHAIAN_URL, item.select_one("a").get("href"))

        last_title = state.get("이화이언")
        if last_title != title:
            body = f"[이화이언]\n제목: {title}\n링크: {link}"
            send_email("[새 글 알림] 이화이언", body)
            state["이화이언"] = title
            print("🆕 [이화이언] 새 글")
        else:
            print("🔁 [이화이언] 변화 없음")

    except Exception as e:
        print(f"⚠️ [이화이언] 실패: {e}")

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
