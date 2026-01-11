import os
import json
import smtplib
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
# 제외 키워드
# ======================
EXCLUDE_KEYWORDS = ["과외", "선생님"]

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
# 키워드 필터
# ======================
def is_excluded(title: str) -> bool:
    return any(word in title for word in EXCLUDE_KEYWORDS)

# ======================
# 이화이언 체크
# ======================
def check_ewhaian(state):
    print("🔍 이화이언 확인 중...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 1️⃣ 로그인 페이지
        page.goto("https://ewhaian.com/login", timeout=60000)

        page.fill("input[name='id']", EWHA_ID)
        page.fill("input[name='password']", EWHA_PW)
        page.click("button:has-text('로그인')")

        # 2️⃣ 로그인 완료 대기
        page.wait_for_load_state("networkidle", timeout=60000)

        # 3️⃣ 팝업 닫기 (있으면 닫고, 없으면 패스)
        try:
            page.wait_for_selector("button:has-text('닫기')", timeout=5000)
            page.click("button:has-text('닫기')")
            print("🧹 팝업 닫기 완료")
        except PlaywrightTimeoutError:
            pass

        # 4️⃣ 알바정보 게시판 이동
        page.goto("https://ewhaian.com/life/66", timeout=60000)

        # 5️⃣ 일반글 제목 대기 (공지 제외)
        page.wait_for_selector("p.listTitle.title-sm", timeout=60000)

        # 6️⃣ 최신 일반글 1개 추출
        title_el = page.query_selector("p.listTitle.title-sm")
        title = title_el.inner_text().strip()

        link_el = title_el.evaluate_handle(
            "el => el.closest('a')"
        )
        link = urljoin("https://ewhaian.com", link_el.get_property("href").json_value())

        print(f"📌 최신 글: {title}")

        # 7️⃣ 키워드 제외
        if is_excluded(title):
            print(f"🚫 제외 키워드 포함 → 알림 안 함")
            browser.close()
            return

        # 8️⃣ 상태 비교
        last_title = state.get("ewhaian_title")

        if last_title != title:
            print("🆕 새 글 감지 → 메일 발송")

            body = (
                f"[이화이언 알바정보]\n\n"
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
    check_ewhaian(state)
    save_state(state)

if __name__ == "__main__":
    main()
