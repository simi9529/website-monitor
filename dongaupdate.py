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
# 사이트 설정
# =====================
login_required_sites = [
    {
        "name": "이화이언 자유게시판",
        "url": "https://ewhaian.com/",
    }
]

public_sites = [
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

# =====================
# 유틸
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

def login(session):
    url = "https://ewhaian.com/login"
    data = {"username": USER_ID, "password": USER_PW}
    res = session.post(url, data=data)
    res.raise_for_status()

# =====================
# 게시판 감시 (동아대)
# =====================
def check_donga_board(site, state):
    res = requests.get(site["url"])
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

        # ✅ 공지 제외: 숫자만
        if not num_text.isdigit():
            continue

        href = subject_a.get("href", "")
        if "board_seq=" not in href:
            continue

        latest_display_num = num_text
        latest_board_seq = href.split("board_seq=")[-1]
        latest_title = subject_a.text.strip()
        latest_link = urljoin(site["url"], href)
        break

    if not latest_board_seq:
        print(f"⚠️ [{site['name']}] 일반글 미검출")
        return

    last_seq = state.get(site["name"])

    if last_seq != latest_board_seq:
        body = (
            f"[{site['name']}]\n"
            f"게시판 번호: {latest_display_num}\n"
            f"제목: {latest_title}\n"
            f"링크: {latest_link}"
        )
        send_email(f"[새 글 알림] {site['name']}", body)
        state[site["name"]] = latest_board_seq
        print(f"🆕 [{site['name']}] 새 글 감지 ({latest_display_num})")
    else:
        print(f"🔁 [{site['name']}] 변화 없음")

# =====================
# 이화이언 (Playwright)
# =====================
def check_ewhaian(session, state):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        cookies = [
            {"name": c.name, "value": c.value, "url": "https://ewhaian.com/"}
            for c in session.cookies
        ]
        context.add_cookies(cookies)

        page = context.new_page()
        page.goto("https://ewhaian.com/", wait_until="networkidle")
        page.wait_for_selector("ul.contentList", timeout=30000)

        soup = BeautifulSoup(page.content(), "html.parser")
        browser.close()

    post = soup.select_one("ul.contentList li.contentItem a")
    if not post:
        return

    title = post.text.strip()
    href = post.get("href", "")
    link = urljoin("https://ewhaian.com/", href)

    last_title = state.get("이화이언 자유게시판")

    if last_title != title:
        body = f"[이화이언 자유게시판]\n제목: {title}\n링크: {link}"
        send_email("[새 글 알림] 이화이언 자유게시판", body)
        state["이화이언 자유게시판"] = title
        print("🆕 [이화이언] 새 글")
    else:
        print("🔁 [이화이언] 변화 없음")

# =====================
# 메인 실행
# =====================
def main():
    state = load_state()

    for site in public_sites:
        check_donga_board(site, state)

    with requests.Session() as session:
        try:
            login(session)
            check_ewhaian(session, state)
        except Exception:
            print("⚠️ 이화이언 로그인/크롤링 실패")

    save_state(state)

if __name__ == "__main__":
    main()
