import os
import json
import smtplib
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ======================
# 환경변수
# ======================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

EWHA_ID = os.environ.get("EWHA_ID")
EWHA_PW = os.environ.get("EWHA_PW")

STATE_FILE = "ewha_state.json"

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
# 이화이언 체크
# ======================
def check_ewhaian(state):
    print("🔍 이화이언 알바정보 확인 중...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1️⃣ 로그인 페이지
        page.goto("https://ewhaian.com/login", timeout=60000)

        # 로그인 입력
        page.fill("input[name='id']", EWHA_ID)
        page.fill("input[name='password']", EWHA_PW)

        # 로그인 버튼 클릭
        page.click("button:has-text('로그인')")

        # 2️⃣ 로그인 완료 대기 (mypage or 메인)
        page.wait_for_load_state("networkidle", timeout=60000)

        # 3️⃣ 팝업 닫기 (있으면 닫고, 없으면 그냥 통과)
        try:
            page.wait_for_selector("button:has-text('닫기')", timeout=5000)
            page.click("button:has-text('닫기')")
            print("✅ 팝업 닫기 성공")
        except PlaywrightTimeoutError:
            print("ℹ️ 팝업 없음 (또는 자동 무시)")

        # 4️⃣ 알바정보 게시판 이동
        page.goto("https://ewhaian.com/life/66", timeout=60000)

        # 5️⃣ 게시글 로딩 대기 (가장 안정적인 기준)
        page.wait_for_selector("a[href*='/detail/']", timeout=60000)

        # 6️⃣ 게시글 수집
        items = page.query_selector_all("a[href*='/detail/']")

        latest_title = None
        latest_link = None

        for item in items:
            title_el = item.query_selector("p.listTitle")
            if not title_el:
                continue

            title = title_el.inner_text().strip()

            # ❌ 공지/정책 제외
            if "정책" in title or "공지" in title:
                continue

            # ❌ 제외 키워드
            if "과외" in title or "선생님" in title:
                continue

            latest_title = title
            latest_link = "https://ewhaian.com" + item.get_attribute("href")
            break

        if not latest_title:
            print("⚠️ 조건에 맞는 일반글 없음")
            browser.close()
            return

        last_title = state.get("ewha_alba")

        if last_title != latest_title:
            body = (
                "[이화이언 알바정보 새 글]\n\n"
                f"제목: {latest_title}\n\n"
                f"링크: {latest_link}"
            )
            send_email("[이화이언] 알바정보 새 글", body)
            state["ewha_alba"] = latest_title
            print(f"🆕 새 글 감지: {latest_title}")
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
