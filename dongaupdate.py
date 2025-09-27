import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin
# --- [추가] Playwright 임포트 ---
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
# 로그인이 필요한 사이트 (이화이언의 selector는 Playwright 사용을 고려하여 변경)
login_required_sites = [
    {
        "name": "이화이언 자유게시판",
        "url": "https://ewhaian.com/life/66",
        # CSR 해결 후 가장 확실한 선택자
        "selector": "ul.boardList li.boardItem a"
    }
]

# 로그인이 필요 없는 공공 사이트
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
        response = session.post(login_url, data=login_data)
        response.raise_for_status()
        print("✅ 로그인 성공")
        return True
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        return False

# --- [수정] check_site 함수: 이화이언은 Playwright 사용하도록 분기 ---
def check_site(site, last_titles, session=None):
    """
    사이트를 확인합니다. 이화이언은 Playwright를 사용하며, 나머지 사이트는 requests를 사용합니다.
    """
    soup = None

    # 이화이언 사이트이며, 로그인 세션이 있는 경우 Playwright를 사용하여 CSR 문제를 해결합니다.
    if session and site["name"] == "이화이언 자유게시판":
        print(f"🔍 [{site['name']}] Playwright로 로그인 세션 유지 후 접속 시도")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                
                # 1. requests 세션의 쿠키를 Playwright로 옮겨서 로그인 상태를 유지
                cookies = [
                    {'name': c.name, 'value': c.value, 'url': site["url"]} 
                    for c in session.cookies
                ]
                context.add_cookies(cookies)

                page = context.new_page()
                page.goto(site["url"], wait_until="networkidle")
                
                # 2. 게시글 목록이 로딩될 때까지 기다립니다.
                page.wait_for_selector("ul.boardList", timeout=30000)
                # 3. 렌더링된 HTML을 가져옵니다.
                soup = BeautifulSoup(page.content(), "html.parser")
                browser.close()

        except Exception as e:
            print(f"❌ [{site['name']}] Playwright 크롤링 오류: {e}")
            
            
    # 그 외 모든 사이트 (requests 기반)
    else:
        try:
            if session:
                response = session.get(site["url"])
            else:
                response = requests.get(site["url"])
                
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
        except Exception as e:
            print(f"❌ [{site['name']}] requests 접속 오류: {e}")
            return

    # --- 게시글 추출 및 비교 로직 ---
    if soup is None:
        print(f"⚠️ [{site['name']}] HTML 내용을 가져오지 못했습니다.")
        return
        
    post_tag = soup.select_one(site["selector"])
    
    if post_tag:
        title = post_tag.text.strip()
        
        # href가 없을 경우를 대비하여 urljoin 대신 기본 URL을 사용
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
