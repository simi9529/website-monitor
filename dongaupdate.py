import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# 이메일 정보
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
USER_ID = os.environ.get("USER_ID")
USER_PW = os.environ.get("USER_PW")

# 상태 파일 경로
STATE_FILE = "titles.json"

# 감시할 사이트 정보
login_required_sites = [
    {
        "name": "이화이언 자유게시판",
        "url": "https://ewhaian.com/",
        "selector": "ul.contentList li.contentItem a"
    }
]

# 로그인이 필요 없는 공공 사이트
public_sites = [
    {
        # [수정됨] 학사공지만 'tr'(줄 전체)을 가져와서 번호를 찾습니다.
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056",
        "selector": "table.bdListTbl tbody tr" 
    },
    {
        # [유지] 수업공지는 기존 그대로
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057",
        "selector": "table.bdListTbl td.subject a"
    },
    {
        # [유지] 특강및 모의고사는 기존 그대로
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059",
        "selector": "table.bdListTbl td.subject a"
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
    try:
        response = session.post(login_url, data=login_data)
        response.raise_for_status()
        print("✅ 로그인 성공")
        return True
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        return False

def check_site(site, last_titles, session=None):
    soup = None

    # 1. HTML 가져오기 (이화이언 Playwright / 그 외 Requests) - 기존 로직 유지
    if session and site["name"] == "이화이언 자유게시판":
        print(f"🔍 [{site['name']}] Playwright 접속 시도")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                cookies = [{'name': c.name, 'value': c.value, 'url': site["url"]} for c in session.cookies]
                context.add_cookies(cookies)
                page = context.new_page()
                page.goto(site["url"], wait_until="networkidle")
                page.wait_for_selector("ul.contentList", timeout=30000)
                soup = BeautifulSoup(page.content(), "html.parser")
                browser.close()
        except Exception as e:
            print(f"❌ [{site['name']}] Playwright 오류: {e}")
            return
    else:
        try:
            if session:
                response = session.get(site["url"])
            else:
                response = requests.get(site["url"])
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            print(f"❌ [{site['name']}] Requests 오류: {e}")
            return

    if soup is None:
        return

    # --- [수정된 부분] 여기서 사이트별로 처리 방식을 나눕니다 ---

    # [CASE 1] 동아대 law 학사공지 (글 번호 비교 로직 적용)
    if site["name"] == "동아대 law 학사공지":
        rows = soup.select(site["selector"])
        max_id = 0
        latest_title = ""
        latest_link = site["url"]

        # 전체 행을 돌며 가장 큰 번호(최신글) 찾기
        for row in rows:
            num_td = row.select_one("td.num")
            if num_td:
                num_text = num_td.get_text(strip=True)
                # '공지'가 아니고 숫자인 경우만 체크
                if num_text.isdigit():
                    current_id = int(num_text)
                    if current_id > max_id:
                        max_id = current_id
                        # 제목과 링크 가져오기
                        subj_tag = row.select_one("td.subject a")
                        if subj_tag:
                            latest_title = subj_tag.get_text(strip=True)
                            href = subj_tag.get('href')
                            latest_link = urljoin(site["url"], href)

        # 저장된 번호와 비교 (없으면 0)
        last_saved_id = int(last_titles.get(site["name"], 0))

        if max_id > last_saved_id:
            print(f"🆕 [{site['name']}] 새 글 발견 (번호: {max_id}): {latest_title}")
            body = f"새 글이 등록되었습니다!\n\n[{site['name']}]\n번호: {max_id}\n제목: {latest_title}\n링크: {latest_link}"
            send_email(f"[새 글 알림] {site['name']}", body)
            last_titles[site["name"]] = max_id
        else:
            print(f"🔁 [{site['name']}] 변화 없음 (최신글 번호: {max_id})")


    # [CASE 2] 그 외 나머지 (기존 로직: 맨 윗글 제목 비교)
    else:
        post_tag = soup.select_one(site["selector"])
        
        if post_tag:
            title = post_tag.text.strip()
            link = urljoin(site["url"], post_tag.get('href')) if post_tag.get('href') and not post_tag.get('href').startswith('#') else site["url"]
            
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


def check_all_sites(session):
    last_titles = load_titles()

    # 1. 로그인 필요한 사이트 확인
    if session:
        for site in login_required_sites:
            check_site(site, last_titles, session)
            
    # 2. 로그인 필요 없는 사이트 확인
    for site in public_sites:
        check_site(site, last_titles)
        
    save_titles(last_titles)

if __name__ == "__main__":
    login_url = "https://ewhaian.com/login"
    login_data = {
        "username": USER_ID,
        "password": USER_PW
    }

    with requests.Session() as session:
        # 로그인 시도
        if login(session, login_url, login_data):
            # 로그인 성공 시, 로그인 필요한 사이트와 공공 사이트 모두 확인
            check_all_sites(session)
        else:
            # 로그인 실패 시, 공공 사이트만 확인 (이화이언은 제외됨)
            check_all_sites(None)
