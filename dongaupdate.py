import json
import os
import smtplib
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright
from datetime import datetime

STATE_FILE = "titles.json"

# ======================
# 공통 유틸
# ======================
def normalize(text: str) -> str:
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

    page.goto(url)
    page.wait_for_selector("tbody tr")

    latest = page.query_selector("tbody tr")
    title = latest.query_selector("a").inner_text()
    title = normalize(title)

    # --- state 구조 확보 ---
    donga = state.setdefault("dongA", {})
    saved_titles = donga.setdefault(category_name, [])

    # --- 중복 검사 ---
    if title in saved_titles:
        print(f"⏩ [{category_name}] 이미 알림 보낸 글")
        return

    # --- 새 글 ---
    print(f"🆕 새 글 감지: {title}")

    link = latest.query_selector("a").get_attribute("href")
    if not link.startswith("http"):
        link = "https://law.donga.ac.kr" + link

    body
