import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin

# 이메일 정보
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

# 로그인 정보
USER_ID = os.environ.get("USER_ID")
USER_PW = os.environ.get("USER_PW")

# 상태 파일 경로
STATE_FILE = "titles.json"

# 감시할 사이트 정보
sites = [
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
     {
        "name": "이화이언 알바하자",
        "url": "https://ewhaian.com/c4/p3/4",
        "selector": ".table-tit a span"
    }
]

def load_titles():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_titles(titles):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=2)

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

def login(session, login_url, login_data):
    """주어진 세션 객체를 사용하여 로그인합니다."""
    try:
        # 로그인 요청을 보냅니다.
        response = session.post(login_url, data=login_data)
        response.raise_for_status()
        # 로그인 성공 여부를 확인하는 추가 로직을 여기에 넣을 수 있습니다.
        print("✅ 로그인 성공")
        return True
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        return False

def check_site(site, last_titles, session):
    try:
        # requests.get() 대신 session.get() 사용
        response = session.get(site["url"])
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        post_tag = soup.select_one(site["selector"])

        if post_tag:
            title = post_tag.text.strip()
            href = post_tag.get("href", "")
            link = urljoin(site["url"], href)

            last_title = last_titles.get(site["name"])

            if last_title != title:
                print(f"🆕 [{site['name']}] 새 글 발견: {title}")
                body = f"새 글이 등록되었습니다!\n\n[{site['name']}]\n제목: {title}\n링크: {link}"
                send_email(f"[새 글 알림] {site['name']}", body)
                last_titles[site["name"]] = title
            else:
                print(f"🔁 [{site['name']}] 변화 없음: {title}")
        else:
            print(f"⚠️ [{site['name']}] 게시글 요소를 찾을 수 없습니다.")
    except Exception as e:
        print(f"❌ [{site['name']}] 오류 발생: {e}")

def check_all_sites(session):
    last_titles = load_titles()
    for site in sites:
        check_site(site, last_titles, session)
    save_titles(last_titles)

if __name__ == "__main__":
    USER_ID = os.environ.get("USER_ID")
    USER_PW = os.environ.get("USER_PW")

    with requests.Session() as session:
        # TODO: 모니터링하려는 사이트의 로그인 URL 및 form 데이터의 키를 실제 값으로 수정하세요.
        login_url = "https://www.ewhaian.com/login"
        login_data = {
            "username": USER_ID,
            "password": USER_PW
        }

        if login(session, login_url, login_data):
            check_all_sites(session)
