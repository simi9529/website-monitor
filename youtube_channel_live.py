"""Monitor a second channel's streams and playlist video titles independently."""

import json
import re

import requests

from youtube_live import live_streams, walk


STATE_KEY = "youtube_live_UCRrRALymR3fxeU5f7GkLuVA"
CHANNEL = "https://www.youtube.com/channel/UCRrRALymR3fxeU5f7GkLuVA"
MAX_PAGES = 10
MAX_PLAYLISTS = 50


def initial(html):
    match = re.search(r"(?:var\s+)?ytInitialData\s*=\s*", html)
    if not match:
        raise ValueError("public listing missing")
    return json.JSONDecoder().raw_decode(html[match.end():])[0]


def selected(data):
    contents = data.get("contents", {})
    tabs = contents.get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    return [item["tabRenderer"].get("content", {}) for item in tabs
            if item.get("tabRenderer", {}).get("selected")] if tabs else contents


def browse(url, name, get, post):
    response = get(url, name)
    if response is None or response.status_code != 200:
        raise ValueError("listing unavailable")
    data = initial(response.text)
    yield {"contents": {"items": selected(data)}}
    context = None
    for match in re.finditer(r"ytcfg\.set\(\s*", response.text):
        try:
            config = json.JSONDecoder().raw_decode(response.text[match.end():])[0]
            context = config.get("INNERTUBE_CONTEXT") or context
        except (ValueError, AttributeError):
            continue
    visited = set()
    for _ in range(MAX_PAGES):
        tokens = [node["continuationCommand"].get("token") for node in walk(selected(data) if "contents" in data else data)
                  if isinstance(node.get("continuationCommand"), dict)]
        tokens = list(dict.fromkeys(token for token in tokens if token and token not in visited))
        if not tokens:
            return
        if not context or len(tokens) != 1:
            raise ValueError("pagination context unavailable")
        token = tokens[0]
        visited.add(token)
        result = post("https://www.youtube.com/youtubei/v1/browse",
                      json={"context": context, "continuation": token}, timeout=(5, 20),
                      allow_redirects=False, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
        if result.status_code != 200:
            raise ValueError("pagination unavailable")
        data = result.json()
        yield {"contents": {"items": data}}
    raise ValueError("pagination limit exceeded")


def playlists(data):
    result = set()
    for node in walk(data.get("contents", {})):
        item = node.get("playlistRenderer") or node.get("gridPlaylistRenderer")
        modern = node.get("lockupViewModel")
        if not item and isinstance(modern, dict) and modern.get("contentType") == "LOCKUP_CONTENT_TYPE_PLAYLIST":
            item = modern
        if isinstance(item, dict):
            value = item.get("playlistId") or item.get("contentId", "")
            if re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value):
                result.add(value)
    return result


def monitor_channel_live(board, state, get, notify, post=requests.post):
    videos = {}
    playlist_ids = set()
    phase = "라이브 목록"
    try:
        for page in browse(CHANNEL + "/streams", board["name"], get, post):
            videos.update((video["id"], video) for video in live_streams(page, allow_empty=True))
        phase = "재생목록 목록"
        for page in browse(CHANNEL + "/playlists", board["name"], get, post):
            playlist_ids.update(playlists(page))
        if len(playlist_ids) > MAX_PLAYLISTS:
            raise ValueError("too many playlists")
        for playlist_id in sorted(playlist_ids):
            phase = "재생목록 영상"
            for page in browse("https://www.youtube.com/playlist?list=" + playlist_id, board["name"], get, post):
                for video in live_streams(page, allow_empty=True):
                    old = videos.get(video["id"])
                    if old and old["active"]:
                        continue
                    videos[video["id"]] = video
        if not videos:
            raise ValueError("no video metadata")
    except (ValueError, TypeError, KeyError, requests.RequestException) as error:
        reason = str(error) if type(error) is ValueError else type(error).__name__
        print(f"⚠️ [공모주투자] {phase} 조회 불완전 ({reason}) → 기준 유지, 다음 회차 재시도")
        return
    notified = list(state.get(STATE_KEY, {}).get("notified_ids", []))
    count = 0
    for video in videos.values():
        if "실시간경쟁률" not in re.sub(r"\s+", "", video["title"]) or video["id"] in notified:
            continue
        if not video["active"]:
            continue
        url = "https://www.youtube.com/watch?v=" + video["id"]
        try:
            notify("[공모주투자] " + video["title"], video["title"] + "\n" + url,
                   push_items=[{"id": url, "title": video["title"], "body": "공모주투자 · 실시간 경쟁률",
                                "links": [{"title": video["title"], "url": url}]}])
        except Exception:
            print("⚠️ [공모주투자] 알림 전송 실패 → 다음 회차 재시도")
            return
        notified.append(video["id"])
        state[STATE_KEY] = {"notified_ids": notified[-500:]}
        count += 1
    print(f"✅ [공모주투자] 재생목록 {len(playlist_ids)}개, 영상 {len(videos)}개 확인, 새 알림 {count}개")
