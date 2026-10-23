"""Read the login-protected board through the API used by ewhaian.com."""

from dataclasses import dataclass

import requests


BASE_URL = "https://ewhaian.com"
CATEGORY_ID = 66
BOARD_URL = f"{BASE_URL}/life/{CATEGORY_ID}"
PAGE_SIZE = 18
MAX_PAGES = 10


class EwhaianError(RuntimeError):
    """A sanitized error that is safe to include in the monitor's logs."""


@dataclass(frozen=True)
class Post:
    id: int
    title: str

    @property
    def url(self):
        return f"{BOARD_URL}/detail/{self.id}"


def _post_json(session, path, body):
    try:
        response = session.post(
            BASE_URL + path,
            json=body,
            timeout=(5, 20),
            allow_redirects=False,
        )
    except requests.RequestException:
        # Do not log a request object, credential payload, or server response.
        raise EwhaianError("이화이언 연결 실패") from None
    if response.status_code in (401, 403):
        raise EwhaianError("로그인 정보 또는 게시판 접근 권한을 확인하세요")
    if not 200 <= response.status_code < 300:
        raise EwhaianError(f"이화이언 HTTP 오류: {response.status_code}")
    try:
        result = response.json()
    except ValueError:
        raise EwhaianError("이화이언에서 JSON 응답을 받지 못했습니다") from None
    if not isinstance(result, dict):
        raise EwhaianError("이화이언 응답 형식이 변경되었습니다")
    return result


def fetch_posts(username, password, last_seen=None):
    """Log in once and read new posts, without storing credentials or tokens.

    With no checkpoint, read only the first page to establish a baseline.
    Numeric post IDs also allow a checkpoint's post to be deleted without
    treating older posts as new. Fail without advancing state if a backlog
    exceeds the bounded pagination limit.
    """
    with requests.Session() as session:
        session.headers.update({"Origin": BASE_URL, "Referer": BASE_URL + "/login"})
        login = _post_json(
            session, "/api/unauth/login", {"username": username, "password": password}
        )
        data = login.get("data")
        token = data.get("accessToken") if isinstance(data, dict) else None
        if login.get("success") is not True or not isinstance(token, str) or not token:
            raise EwhaianError("이화이언 로그인 실패: EWHA_ID와 EWHA_PW를 확인하세요")
        session.headers.update({
            "Authorization": "Bearer " + token,
            "Referer": BOARD_URL,
        })

        posts = {}
        for page in range(1, MAX_PAGES + 1):
            result = _post_json(session, "/api/board/list/v2/all", {
                "page": page,
                "recordSize": PAGE_SIZE,
                "pageSize": 10,
                "categoryIdList": [CATEGORY_ID],
                "sort": "new",
                "tradeCompleteYn": "N",
                "filterWordList": [],
            })
            rows = result.get("list")
            if result.get("success") is False or not isinstance(rows, list):
                raise EwhaianError("게시판 조회 실패: 접근 권한 또는 응답 형식을 확인하세요")
            reached_checkpoint = False
            for row in rows:
                if not isinstance(row, dict):
                    raise EwhaianError("게시글 응답 형식이 변경되었습니다")
                post_id, title = row.get("id"), row.get("title")
                if (isinstance(post_id, bool) or not str(post_id).isdigit()
                        or int(post_id) <= 0 or not isinstance(title, str) or not title.strip()):
                    raise EwhaianError("게시글 번호 또는 제목을 읽지 못했습니다")
                post_id = int(post_id)
                if last_seen is not None and post_id <= last_seen:
                    reached_checkpoint = True
                else:
                    posts[post_id] = Post(post_id, title.strip())
            if last_seen is None or reached_checkpoint or len(rows) < PAGE_SIZE:
                return sorted(posts.values(), key=lambda post: post.id)
        raise EwhaianError("새 글이 조회 한도를 초과했습니다. 상태를 유지하므로 조회 범위를 확인하세요")
