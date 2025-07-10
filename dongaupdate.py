import json

STORAGE_PATH = "storage.json"

def load_last_titles():
    if os.path.exists(STORAGE_PATH):
        with open(STORAGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_last_titles(data):
    with open(STORAGE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import schedule
import time
import os
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

sites = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056",
       "last_title": None,
        "selector": "table.bdListTbl td.subject a"
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057",
        "last_title": None,
        "selector": "table.bdListTbl td.subject a"
    },
    {
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059",
        "last_title": None,
        "selector": "table.bdListTbl td.subject a"
    }
]

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(FROM_EMAIL, APP_PASSWORD)
            server.send_message(msg)
            print(f"✅ 이메일 발송 완료: {subject}")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

def check_site(site):
    try:
        response = requests.get(site["url"])
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        post_tag = soup.select_one(site["selector"])

        if post_tag:
            title = post_tag.text.strip()
            href = post_tag.get('href', '')

            if site["last_title"] is None:
                site["last_title"] = title
                print(f"📌 [{site['name']}] 첫 감시 시작: {title}")
            elif title != site["last_title"]:
                print(f"🆕 [{site['name']}] 새 글 발견: {title}")
                link = urljoin(site["url"], href)
                body = f"새 글이 등록되었습니다!\n\n[{site['name']}]\n제목: {title}\n링크: {link}"
                send_email(f"[새 글 알림] {site['name']}", body)
                site["last_title"] = title
            else:
                print(f"🔁 [{site['name']}] 변화 없음: {title}")
        else:
            print(f"⚠️ [{site['name']}] 게시글 요소를 찾을 수 없습니다. selector를 확인하세요.")
    except Exception as e:
        print(f"❌ [{site['name']}] 오류 발생: {e}")

def check_all_sites():
    last_titles = load_last_titles()

    for site in sites:
        site_name = site["name"]
        site["last_title"] = last_titles.get(site_name)
        check_site(site)
        # 업데이트된 제목 저장
        last_titles[site_name] = site["last_title"]

    save_last_titles(last_titles)
    
def run_monitor():
    schedule.every(5).minutes.do(check_all_sites)
    print("📡 사이트 감시 시작 (5분 간격)")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # GitHub Actions에서는 딱 한 번 실행 후 종료
        check_all_sites()
    else:
        # 로컬에서 실행할 때는 감시 루프 지속
        run_monitor()
