import os
import json
import smtplib
from email.mime.text import MIMEText
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# =====================
# 환경 변수
# =====================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

EWHAIAN_ID = os.environ.get("USER_ID")
EWHAIAN_PW = os.environ.get("USER_PW")

STATE_FILE = "ewhaian_state.json"

BASE_URL = "https://ewhaian.com"
LOGIN_URL = "https://ewhaian.com/login"

# =====================
# 상태 관리
# =====================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# =====================
# 메일
# =====================
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(FROM_EMAIL, APP_PASSWORD)
        server.send_message(msg)

# =====================
# 이화이언 체크
# =====================
def check_ewhaian(state):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 1️⃣ 로그인 페이지
        page.goto(LOGIN_URL, wait_until="networkidle")

        # 2️⃣ 입력창 대기
        page.wait_for_selector("input#id", timeout=30000)
        page.wait_for_selector("input#password", timeout=30000)

        # 3️⃣ 로그인 입력
        page.fill("input#id", EWHAIAN_ID)
        page.fill("input#password", EWHAIAN_PW)

        # 4️⃣ 로그인 클릭
        page.click('button:has-text("로그인")')

        # 5️⃣ 로그인 완료 대기
        page.wait_for_load_state("networkidle", timeout=30000)

        # 6️⃣ 메인 페이지
        page.goto(BASE_URL, wait_until="networkidle")

        # 7️⃣ 최신글 로딩 대기
        page.wait_for_selector("ul.contentList li.contentItem", timeout=30000)

        soup = BeautifulSoup(page.content(), "html.parser")
        browser.close()

    # 8️⃣ 최신글 추출
    item = soup.select_one("ul.contentList li.contentItem")
    if not item:
        print("⚠️ [이화이언] 최신글을 찾지 못함")
        return

    title = item.select_one("p.listTitle").text.strip()
    link = urljoin(BASE_URL, item.select_one("a")["href"])

    last_title = state.get("latest_title")

    if last_title != title:
        send_email(
            "[이화이언 새 글 알림]",
            f"제목: {title}\n\n링크: {link}"
        )
        state["latest_title"] = title
        print("🆕 [이화이언] 새 글 감지")
    else:
        print("🔁 [이화이언] 변화 없음")

# =====================
# 메인
# =====================
def main():
    state = load_state()
    check_ewhaian(state)
    save_state(state)

if __name__ == "__main__":
    main()
