import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import schedule
import time

# 감시할 사이트 리스트 (URL과 사이트 이름 포함)
sites = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056",
        "last_title": None,
        "selector": "div.tbl_board tbody tr td.subject a"
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057",
        "last_title": None,
        "selector": "css선택자_예: div.post-title a"
    },
    {
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059",
        "last_title": None,
        "selector": "css선택자_예: div.post-title a"
    }
]

FROM_EMAIL = "simi9529@gmail.com"
TO_EMAIL = "simi9529@kakao.com"
APP_PASSWORD = "trbjspzyzvvoedqw"

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = simi9529@gmail.com
    msg["To"] = simi9529@kakao.com

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(simi9529@gmail.com,trbjspzyzvvoedqw)
        server.send_message(msg)
        print(f"✅ 이메일 발송 완료: {subject}")

def check_site(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    post_tag = soup.select_one(site["selector"])

    if post_tag:
        title = post_tag.text.strip()
        href = post_tag.get('href', '')

        if site["last_title"] is None:
            site["last_title"] = title
            print(f"{site['name']} 첫 감시 시작: {title}")
        elif title != site["last_title"]:
            print(f"🆕 [{site['name']}] 새 글 발견: {title}")
            link = href if href.startswith("http") else site["url"] + href
            body = f"새 글이 등록되었습니다!\n\n[{site['name']}]\n제목: {title}\n링크: {link}"
            send_email(f"[새 글 알림] {site['name']}", body)
            site["last_title"] = title
        else:
            print(f"🔁 [{site['name']}] 변화 없음: {title}")
    else:
        print(f"⚠️ [{site['name']}] 게시글 요소를 찾을 수 없습니다.")

def check_all_sites():
    for site in sites:
        check_site(site)

# 1분마다 실행
schedule.every(1).minutes.do(check_all_sites)

print("📡 여러 사이트 감시 시작 (1분 간격)")
while True:
    schedule.run_pending()
    time.sleep(1)