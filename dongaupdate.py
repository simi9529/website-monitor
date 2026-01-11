import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import os
import json
from urllib.parse import urljoin

# ======================
# 환경변수
# ======================
FROM_EMAIL = os.environ.get("FROM_EMAIL")
TO_EMAIL = os.environ.get("TO_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

STATE_FILE = "titles.json"

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
# 게시판 체크
# ======================
def check_donga_board(board, state):
    print(f"🔍 [{board['name']}] 확인 중...")

    res = requests.get(board["url"], timeout=30)
    res.raise_for_status()

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
# 메인
# ======================
def main():
    state = load_state()

    for board in DONGA_BOARDS:
        check_donga_board(board, state)

    save_state(state)

if __name__ == "__main__":
    main()
