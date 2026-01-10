import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

FROM_EMAIL = os.environ["FROM_EMAIL"]
TO_EMAIL = os.environ["TO_EMAIL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]

EWHAIAN_ID = os.environ["USER_ID"]
EWHAIAN_PW = os.environ["USER_PW"]

STATE_FILE = "ewhaian_state.json"

LOGIN_URL = "https://ewhaian.com/login"
BOARD_URL = "https://ewhaian.com/life/66"


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


def close_popup(page):
    selectors = [
        'button:has-text("닫기")',
        'button:has-text("오늘")',
        'button[aria-label="close"]',
    ]

    for _ in range(5):
        for sel in selectors:
            try:
                page.click(sel, timeout=2000, force=True)
                page.wait_for_timeout(500)
                return
            except:
                pass
        time.sleep(1)


def check_ewhaian(state):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.fill("#id", EWHAIAN_ID)
        page.fill("#password", EWHAIAN_PW)
        page.click('button:has-text("로그인")')
        page.wait_for_timeout(3000)

        close_popup(page)

        page.goto(BOARD_URL, wait_until="domcontentloaded")

        for _ in range(30):
            if "title-sm" in page.content():
                break
            time.sleep(1)

        soup = BeautifulSoup(page.content(), "html.parser")
        browser.close()

    # 🔥 공지 제외 + 일반글만
    item = soup.select_one("a[href*='/detail/'] p.listTitle.title-sm")
    if not item:
        print("❌ 일반 게시글 없음")
        return

    title = item.get_text(strip=True)
    link = urljoin("https://ewhaian.com", item.find_parent("a")["href"])

    print(f"📌 일반 최신글: {title}")

    last = state.get("ewhaian")
    if last != title:
        send_email(
            "[이화이언 알바정보] 새 글",
            f"{title}\n\n{link}"
        )
        state["ewhaian"] = title
        save_state(state)
        print("📧 메일 발송")
    else:
        print("변경 없음")


def main():
    state = load_state()
    check_ewhaian(state)


if __name__ == "__main__":
    main()
