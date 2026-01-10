import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# =====================
# 이메일 / 로그인 정보
# =====================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
USER_ID = os.environ.get("USER_ID")
USER_PW = os.environ.get("USER_PW")

# 상태 저장 파일
STATE_FILE = "titles.json"

# =====================
# 사이트 설정
# =====================
login_required_sites = [
    {
        "name": "이화이언 자유게시판",
        "url": "https://ewhaian.com/",
        "selector": "ul.contentList li.contentItem a"
    }
]

public_sites = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056",
        "selector": "table.bdListTbl td.subject a"
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057",
        "selector": "table.bdListTbl td.subject a"
    },
    {
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059",
        "selector": "table.bdListTbl td.subject a"
    }
]

# =====================
# 유틸 함수
# =====================
def load_titles():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_titles(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(FROM_EMAIL, APP_PASSWORD)
            server.send_message(msg)
            print(f"✅ 이메일 발송: {subject}")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

def login(session, url, data):
    try:
        res = session.post(url, data=data)
        res.raise_for_status()
        print("✅ 로그인 성공")
        return True
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        return False

# =====================
# 핵심 감시 함수
# =====================
def check_site(site, last_state, session=None):
    soup = None

    # --- 이화이언 (Playwright) ---
    if session and site["name"] == "이화이언 자유게시판":
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()

                cookies = [
                    {"name": c.name, "value": c.value, "url": site["url"]}
                    for c in session.cookies
                ]
                context.add_cookies(cookies)

                page = context.new_page()
                page.goto(site["url"], wait_until="networkidle")
                page.wait_for_selector("ul.contentList", timeout=30000)

                soup = BeautifulSoup(page.content(), "html.parser")
                browser.close()

        except Exception as e:
            print(f"❌ [{site['name']}] Playwright 오류: {e}")
            return

    # --- 일반 사이트 (requests) ---
    else:
        try:
            res = session.get(site["url"]) if session else requests.get(site["url"])
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            print(f"❌ [{site['name']}] 접속 오류: {e}")
            return

    if soup is None:
        return

    # =====================
    # 게시글 번호(board_seq) 기준 감지
    # =====================
    post_tags = soup.select(site["selector"])

    latest_post_id = None
    latest_title = None
    latest_link = None

    for tag in post_tags:
        href = tag.get("href", "")
        if "board_seq=" in href:
            latest_post_id = href.split("board_seq=")[-1]
            latest_title = tag.text.strip()
            latest_link = urljoin(site["url"], href)
            break   # ✅ 첫 번째 일반글만 사용

    if not latest_post_id:
        print(f"⚠️ [{site['name']}] board_seq 미검출")
        return

    last_id = last_state.get(site["name"])

    if last_id != latest_post_id:
        print(f"🆕 [{site['name']}] 새 글 감지")
        body = (
            f"새 글이 등록되었습니다.\n\n"
            f"[{site['name']}]\n"
            f"제목: {latest_title}\n"
            f"글 번호: {latest_post_id}\n"
            f"링크: {latest_link}"
        )
        send_email(f"[새 글 알림] {site['name']}", body)
        last_state[site["name"]] = latest_post_id
    else:
        print(f"🔁 [{site['name']}] 변화 없음 ({latest_post_id})")

# =====================
# 전체 실행
# =====================
def check_all_sites(session):
    last_state = load_titles()

    if session:
        for site in login_required_sites:
            check_site(site, last_state, session)

    for site in public_sites:
        check_site(site, last_state)

    save_titles(last_state)

if __name__ == "__main__":
    login_url = "https://ewhaian.com/login"
    login_data = {
        "username": USER_ID,
        "password": USER_PW
    }

    with requests.Session() as session:
        if login(session, login_url, login_data):
            check_all_sites(session)
        else:
            check_all_sites(None)
