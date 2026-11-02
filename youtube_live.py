"""Notify once per currently live stream whose title contains 비례배정."""

import json
import re


STATE_KEY = "youtube_live_proportional_allocation"


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def text(value):
    if not isinstance(value, dict):
        return ""
    return value.get("simpleText") or value.get("content") or "".join(
        run.get("text", "") for run in value.get("runs", [])
    )


def live_streams(data):
    videos = {}
    contents = data.get("contents", {})
    tabs = contents.get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    if tabs:
        roots = []
        for entry in tabs:
            tab = entry.get("tabRenderer", {})
            url = tab.get("endpoint", {}).get("commandMetadata", {}).get("webCommandMetadata", {}).get("url", "")
            if tab.get("selected") or "/streams" in url:
                roots.append(tab.get("content", {}))
    else:
        roots = contents
    for node in walk(roots):
        candidate = node.get("videoRenderer") or node.get("gridVideoRenderer")
        modern = node.get("lockupViewModel")
        if not candidate and isinstance(modern, dict) and modern.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":
            candidate = modern
        if not isinstance(candidate, dict):
            continue
        video_id = candidate.get("videoId") or candidate.get("contentId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        title = text(candidate.get("title")) or text(candidate.get("metadata", {}).get("lockupMetadataViewModel", {}).get("title"))
        active = False
        upcoming = False
        for detail in walk(candidate):
            upcoming = upcoming or bool(detail.get("upcomingEventData"))
            overlay = detail.get("thumbnailOverlayTimeStatusRenderer", {})
            badge = detail.get("metadataBadgeRenderer", {})
            modern_badge = detail.get("thumbnailBadgeViewModel", {})
            active = active or overlay.get("style") == "LIVE" or badge.get("style") == "BADGE_STYLE_TYPE_LIVE_NOW"
            active = active or modern_badge.get("badgeStyle") == "THUMBNAIL_BADGE_STYLE_LIVE"
        # Title words such as LIVE / 실시간 are never proof of a live broadcast.
        videos[video_id] = {"id": video_id, "title": title, "active": active and not upcoming}
    if not videos:
        raise ValueError("라이브 탭의 동영상 목록을 확인하지 못했습니다")
    return list(videos.values())


def monitor_live(board, state, get, notify):
    response = get(board["url"], board["name"])
    if response is None or response.status_code != 200:
        return
    match = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", response.text)
    if not match:
        print("⚠️ [유튜브 라이브] 목록 데이터가 없어 알림을 보내지 않았습니다")
        return
    try:
        videos = live_streams(json.loads(match[1]))
    except (ValueError, TypeError, KeyError):
        print("⚠️ [유튜브 라이브] 방송 상태를 확인하지 못했습니다. 알림 기준 유지")
        return
    seen = list(state.get(STATE_KEY, {}).get("notified_ids", []))
    matches = [video for video in videos if video["active"] and "비례배정" in video["title"]]
    count = 0
    for video in matches:
        if video["id"] in seen:
            continue
        url = "https://www.youtube.com/watch?v=" + video["id"]
        try:
            notify("[라이브 방송 중] " + video["title"], video["title"] + "\n" + url,
                   push_items=[{"id": url, "title": video["title"], "body": "비례배정 라이브 방송 중",
                                "links": [{"title": video["title"], "url": url}]}])
        except Exception:
            print("⚠️ [유튜브 라이브] 전송 실패 → 다음 회차 재시도")
            return
        seen.append(video["id"])
        state[STATE_KEY] = {"notified_ids": seen[-500:]}
        count += 1
    print(f"✅ [유튜브 라이브] 동영상 {len(videos)}개 확인, 비례배정 방송 중 {len(matches)}개, 새 알림 {count}개")
