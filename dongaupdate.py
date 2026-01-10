import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# =====================
# 환경 변수
# =====================
FROM_EMAIL = os.environ["FROM_EMAIL"]
TO_EMAIL = os.environ["TO_EMAIL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]

EWHAIAN_ID = os.environ["USER_ID"]
EWHAIAN_PW = os.environ["USER_PW"]

STATE_FILE = "ewhaian_state.json"

LOGIN_URL = "https://ewhaian.com/login"
BOARD_URL = "https://ewhaian.com/life/66"

# =====================
# 상태 저장
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
# 🔥 팝업 닫기 (핵심)
# =====================
def close_popup(page):
    popup_selectors = [
        'button:has-text("닫기")',
        'button:has-text("오늘")',
        'button[aria-label="close"]',
        'svg[role="img"]',
    ]

    for _ in range(5):
        for sel in popup_selectors:
            try:
                page.click(sel, timeout=2000, force=True)
                page.wait_for_timeout(500)
                print("✅ 팝업 닫음")
                return
            except:
                pass
        time.sleep(1)

    print("⚠️ 팝업 못 찾았지만 진행")

# =====================
# 이화이언 체크
# =====================
def check_ewhaian(state):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 로그인
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.fill("#id", EWHAIAN_ID)
        page.fill("#password", EWHAIAN_PW)
        page.click('button:has-text("로그인")')

        # 로그인 완료 대기
        page.wait_for_timeout(3000)

        # 🔥 팝업 반드시 닫기
        close_popup(page)

        # 게시판 이동
        page.goto(BOARD_URL, wait_until="domcontentloaded")

        # 🔥 React 렌더 대기 (DOM 폴링)
        for _ in range(30):
            html = page.content()
            if "listTitle" in html:
                break
            time.sleep(1)
        else:
            browser.close()
            raise RuntimeError("게시글 렌더 실패")

        soup = BeautifulSoup(page.content(), "html.parser")
        browser.close()

    # 최신글 추출
    first = soup.select_one("a[href*='/detail/'] p.listTitle")
    if not first:
        print("❌ 최신글 못 찾음")
        return

    title = first.get_text(strip=True)
    link = urljoin("https://ewhaian.com", first.find_parent("a")["href"])

    print(f"📌 최신글: {title}")

    last = state.get("ewhaian")
    if last != title:
        send_email(
            "[이화이언] 새 글 알림",
            f"{title}\n\n{link}"
        )
        state["ewhaian"] = title
        save_state(state)
        print("📧 메일 발송")
    else:
        print("변경 없음")

# =====================
# main
# =====================
def main():
    state = load_state()
    check_ewhaian(state)

if __name__ == "__main__":
    main()
