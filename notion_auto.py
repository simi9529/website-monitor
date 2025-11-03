import os
from notion_client import Client
from datetime import datetime, timedelta, timezone

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
    for i, page in enumerate(pages, 1):
        props = page["properties"]
        page_id_short = page["id"][:8]

        start_prop = props.get("시작", {}).get("date", {}).get("start")
        end_prop = props.get("종료", {}).get("date", {}).get("start")
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

        current = props.get("기간", {}).get("date", {})
        current_start = current.get("start")
        current_end = current.get("end")

        if current_start == start_prop and current_end == end_prop:
            print(f"⏸ {page_id_short}... 기간 unchanged")
            continue

        try:
            notion.pages.update(
                page_id=page["id"],
                properties={
                    "기간": {"date": {"start": start_prop, "end": end_prop}}
                }
            )
            print(f"✅ {page_id_short}... 업데이트: {start_prop} ~ {end_prop}")
        except Exception as e:
            print(f"❌ {page_id_short}... 업데이트 실패: {e}")

# -------------------------------
# 지난 7일치 페이지만 가져오기
# -------------------------------
def update_recent_week():
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    filter_payload = {
        "filter": {
            "property": "시작",
            "date": {
                "after": seven_days_ago.isoformat()
            }
        }
    }

    try:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
            **filter_payload,
            page_size=100
        )
    except Exception as e:
        print(f"❌ 데이터베이스 쿼리 실패: {e}")
        return

    pages = response.get("results", [])
    print(f"📄 지난 7일치 {len(pages)}개 페이지 처리 중...")
    update_pages(pages)

# -------------------------------
# 실행
# -------------------------------
if __name__ == "__main__":
    update_recent_week()
