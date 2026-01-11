import json
import os
import smtplib
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright
from datetime import datetime

STATE_FILE = "titles.json"

# ======================
# 유틸
# ======================
def normalize(text):
    return " ".join(text.split()).strip()

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = os.environ["FROM_EMAIL"]
    msg["To"] = os.environ["TO_EMAIL"]

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["FROM_EMAIL"], os.environ["APP_PASSWORD"])
        server.send_message(msg)

# ======================
# 동아대 게시판 체크
# ======================
def check_donga_category(page, state, category_name, url):
    print(f"🔍 [동아대 law {category_name}] 확인 중...")

    page.goto(url, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=60000)

    # ✅ table이 뜰 때까지 기다림
    page.wait_for_selector("table tbody tr", timeout=60000)

    rows = page.query_selector_all("table tbody tr")
    if not rows:
        print(f"⚠️ [{category_name}] 게시글 없음")
        return

    latest = rows[0]
    a_tag = latest.query_selector("a")
    title = normalize(a_tag.inner_text())

    donga = state.setdefault("dongA", {})
    sent_titles = donga.setdefault(category_name, [])

    if title in sent_titles:
        print(f"⏩ [{category_name}] 이미 알림 보낸 글")
        return

    link = a_tag.get_attribute("href")
    if not link.startswith("http"):
        link = "https://law.donga.ac.kr" + link

    print(f"🆕 새 글 감지: {title}")

    body = f"""[동아대학교 법학전문대학원 - {category_name}]

제목: {title}

링크:
{link}

확인 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

    send_email(f"[동아대 law {category_name}] 새 공지", body)

    # 🔐 즉시 저장 (중복 방지 핵심)
    sent_titles.insert(0, title)
    donga[category_name] = sent_titles[:20]
    save_state(state)

# ======================
# main
# ======================
def main():
    state = load_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        check_donga_category(
            page, state, "학사공지",
            "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN077"
        )

        check_donga_category(
            page, state, "수업공지",
            "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN078"
        )

        check_donga_category(
            page, state, "특강·모의고사",
            "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN079"
        )

        browser.close()

if __name__ == "__main__":
    main()
