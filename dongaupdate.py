import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
import time
from urllib.parse import urljoin
from requests.exceptions import ReadTimeout, RequestException

# ======================
# 환경변수
# ======================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

STATE_FILE = "titles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# ======================
# 동아대 게시판
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
        "name": "동아대 law 특강및 모의고사",
        "url": "https://law.donga.ac.kr/law/CMS/Board/Board.do?mCode=MN059"
    }
]

# ======================
# 상태
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
# 안전 요청 함수 (핵심)
# ======================
def safe_get(url, name, retries=3):
    for attempt in range(1, retries + 1):
        try:
            return requests.get(
                url,
                headers=HEADERS,
                timeout=(5, 20)  # ⬅️ 30초보다 이게 더 안정적
            )
        except ReadTimeout:
            print(f"⏳ [{name}] 응답 지연 ({attempt}/{retries})")
        except RequestException as e:
            print(f"⚠️ [{name}] 요청 오류 ({attempt}/{retries}): {e}")

        time.sleep(2)

    print(f"🚫 [{name}] 최종 실패 → 이번 회차 스킵")
    return None

# ======================
# 게시판 체크
# ======================
def check_donga_board(board, state):
    print(f"🔍 [{board['name']}] 확인 중...")

    res = safe_get(board["url"], board["name"])
    if res is None or res.status_code != 200:
        return  # ❗ 여기서 끝 → 절대 죽지 않음

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("table.bdListTbl tbody tr")

    for row in rows:
        num_td = row.select_one("td.num")
        subject_a = row.select_one("td.subject a")

        if not num_td or not subject_a:
            continue

        num = num_td.text.strip()

        # 공지 제외
        if not num.isdigit():
            continue

        href = subject_a.get("href", "")
        if "board_seq=" not in href:
            continue

        board_seq = href.split("board_seq=")[-1]
        title = subject_a.text.strip()
        link = urljoin(board["url"], href)

        last_seq = state.get(board["name"])

        if last_seq != board_seq:
            print(f"🆕 새 글 감지: {title}")
            body = (
                f"[{board['name']}]\n\n"
                f"번호: {num}\n"
                f"제목: {title}\n\n"
                f"링크: {link}"
            )
            send_email(f"[동아대] {board['name']} 새 글", body)
            state[board["name"]] = board_seq
        else:
            print("🔁 변화 없음")

        break  # 최신 일반글 1개만

# ======================
# 메인 (최후 안전망)
# ======================
def main():
    try:
        state = load_state()
        for board in DONGA_BOARDS:
            check_donga_board(board, state)
        save_state(state)
    except Exception as e:
        print("🔥 치명적 예외 발생 (강제 종료 방지)")
        print(e)

if __name__ == "__main__":
    main()
