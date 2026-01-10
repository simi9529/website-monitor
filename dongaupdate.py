import os
import json
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ======================
# 환경변수
# ======================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

EWHA_ID = os.environ.get("EWHA_ID")
EWHA_PW = os.environ.get("EWHA_PW")

STATE_FILE = "state.json"

# ======================
# 이화이언 제외 키워드
# ======================
EWHA_EXCLUDE_KEYWORDS = ["과외", "선생님"]

# ======================
# 동아대 게시판 설정
# ======================
DONGA_BOARDS = [
    {
        "name": "동아대 law 학사공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN056"
    },
    {
        "name": "동아대 law 수업공지",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN057"
    },
    {
        "name": "동아대 law 특강·모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059"
    }
]

# ======================
# 상태 저장
# ======================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ======================
# 이메일
# ======================
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(FROM_EMAIL, APP_PASSWORD)
        server.send_message(msg)

# ======================
# 이화이언 키워드 필터
# ======================
def ewha_excluded(title):
    return any(word in title for word in EWHA_EXCLUDE_KEYWORDS)

# ======================
# 동아대 게시판 체크
# ======================
def check_donga_board(board, state):
    print(f"🔍 [{board['name']}] 확인 중...")

    try:
        res = requests.get(board["url"], timeout=30)
        res.raise_for_status()
    except Exception as e:
        print(f"❌ 접속 실패: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("table.bdListTbl tbody tr")

    for row in rows:
        num_td = row.select_one("td.num")
        subject_a = row.select_one("td.subject a")

        if not num_td or not subject_a:
            continue

        num_text = num_td.text.strip()
        if not num_text.isdigit():  # 공지글 제외
            continue

        href = subject_a.get("href", "")
        if "board_seq=" not in href:
            continue

        board_seq = href.split("board_seq=")[-1]
        title = subject_a.text.strip()
        link = urljoin(board["url"], href)

        state_key = f"donga_{board['name']}"
        last_seq = state.get(state_key)

        if last_seq != board_seq:
            print(f"🆕 새 글: {title}")
            body = (
                f"[{board['name']}]\n\n"
                f"번호: {num_text}\n"
                f"제목: {title}\n\n"
                f"링크: {link}"
            )
            send_email(f"[동아대] {board['name']} 새 글", body)
            state[state_key] = board_seq
        else:
            print("🔁 변화 없음")

        break  # 최신 일반글 1개만 확인

# ======================
# 이화이언 알바정보 체크
# ======================
def check_ewhaian(state):
    print("🔍 [이화이언 알바정보] 확인 중...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 로그인
        page.goto("https://ewhaian.com/login", timeout=60000)
        page.fill("input[name='id']", EWHA_ID)
        page.fill("input[name='password']", EWHA_PW)
        page.click("button:has-text('로그인')")
        page.wait_for_load_state("networkidle", timeout=60000)

        # 팝업 닫기 (있으면)
        try:
            page.wait_for_selector("button:has-text('닫기')", timeout=5000)
            page.click("button:has-text('닫기')")
        except PlaywrightTimeoutError:
            pass

        # 알바정보 게시판
        page.goto("https://ewhaian.com/life/66", timeout=60000)
        page.wait_for_selector("p.listTitle.title-sm", timeout=60000)

        title_el = page.query_selector("p.listTitle.title-sm")
        title = title_el.inner_text().strip()

        link_el = title_el.evaluate_handle("el => el.closest('a')")
        link = urljoin("https://ewhaian.com", link_el.get_property("href").json_value())

        print(f"📌 최신 글: {title}")

        if ewha_excluded(title):
            print("🚫 제외 키워드 포함")
            browser.close()
            return

        last_title = state.get("ewhaian_title")

        if last_title != title:
            print("🆕 새 글 감지")
            body = (
                "[이화이언 알바정보]\n\n"
                f"제목: {title}\n\n"
                f"링크: {link}"
            )
            send_email("[이화이언] 새 알바 글", body)
            state["ewhaian_title"] = title
        else:
            print("🔁 변화 없음")

        browser.close()

# ======================
# 메인
# ======================
def main():
    state = load_state()

    # 동아대 3개
    for board in DONGA_BOARDS:
        check_donga_board(board, state)

    # 이화이언
    check_ewhaian(state)

    save_state(state)

if __name__ == "__main__":
    main()
