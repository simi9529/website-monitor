import os
from notion_client import Client
from datetime import datetime, timezone

# 🔑 환경 변수에서 Notion API 키와 DB ID 가져오기
notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

# -------------------------------
# 날짜 파싱 및 기간 업데이트 함수
# -------------------------------
def parse_iso_naive(dt_str):
    """ISO 문자열을 offset-naive UTC datetime으로 변환"""
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt = datetime.fromisoformat(dt_str[:-1])
            return dt.replace(tzinfo=timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as e:
        print(f"⚠ 날짜 파싱 오류 ({dt_str}): {e}")
        return None

def update_pages(pages):
    """페이지 목록을 받아 '기간' 필드 업데이트"""
    for page in pages:
        props = page.get("properties", {})
        page_id_short = page.get("id", "")[:8]

        # 안전하게 start / end 가져오기
        start_value = props.get("시작")
        start_prop = start_value.get("date", {}).get("start") if start_value and start_value.get("date") else None

        end_value = props.get("종료")
        end_prop = end_value.get("date", {}).get("start") if end_value and end_value.get("date") else None

        if not start_prop or not end_prop:
            print(f"⏸ {page_id_short}... '시작' 또는 '종료' 비어 있음")
            continue

        start_dt = parse_iso_naive(start_prop)
        end_dt = parse_iso_naive(end_prop)
        if not start_dt or not end_dt:
            print(f"⚠ {page_id_short}... 날짜 파싱 실패")
            continue

        # 종료가 시작보다 빠르면 하루 보정
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(days=1)
            end_prop = end_dt.isoformat()

        # 현재 '기간' 값
        current = props.get("기간", {}).get("date", {})
        current_start = current.get("start")
        current_end = current.get("end")

        if current_start == start_prop and current_end == end_prop:
            print(f"⏸ {page_id_short}... 기간 unchanged")
            continue

        # 업데이트 시도
        try:
            notion.pages.update(
                page_id=page.get("id"),
                properties={
                    "기간": {"date": {"start": start_prop, "end": end_prop}}
                }
            )
            print(f"✅ {page_id_short}... 업데이트: {start_prop} ~ {end_prop}")
        except Exception as e:
            print(f"❌ {page_id_short}... 업데이트 실패: {e}")

# -------------------------------
# 특정 날짜 페이지 전체 처리 (페이지네이션)
# -------------------------------
def update_specific_day(target_date_str="2025-10-24"):
    """
    target_date_str: 'YYYY-MM-DD' 형식
    """
    start_of_day = f"{target_date_str}T00:00:00.000Z"
    end_of_day = f"{target_date_str}T23:59:59.999Z"

    filter_payload = {
        "filter": {
            "property": "시작",
            "date": {
                "on_or_after": start_of_day,
                "on_or_before": end_of_day
            }
        }
    }

    all_pages = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
            **filter_payload,
            page_size=100,
            start_cursor=start_cursor
        )

        pages = response.get("results", [])
        all_pages.extend(pages)

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    print(f"📄 {target_date_str} 날짜의 {len(all_pages)}개 페이지 처리 중...")
    update_pages(all_pages)

# -------------------------------
# 실행
# -------------------------------
if __name__ == "__main__":
    # 원하는 날짜 지정
    update_specific_day("2025-10-24")
