import os
from notion_client import Client
from datetime import datetime, timezone, timedelta

# 🔑 환경 변수에서 Notion API 키와 DB ID 가져오기
notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

# -------------------------------
# 날짜 파싱 함수
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

# -------------------------------
# 페이지 목록 업데이트
# -------------------------------
def update_pages(pages):
    for page in pages:
        props = page.get("properties", {})
        page_id_short = page.get("id", "")[:8]

        start_value = props.get("시작")
        start_prop = start_value.get("date", {}).get("start") if start_value and start_value.get("date") else None

        end_value = props.get("종료")
        end_prop = end_value.get("date", {}).get("start") if end_value and end_value.get("date") else None

        # 종료가 비어있으면 건너뜀
        if not start_prop or not end_prop:
            print(f"⏸ {page_id_short}... '시작' 또는 '종료' 비어 있음, 건너뜀")
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

        # 현재 '기간' 값 안전하게 가져오기
        current_date = props.get("기간", {}).get("date")
        current_start = current_date.get("start") if current_date else None
        current_end = current_date.get("end") if current_date else None

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
# 최근 1,000개(또는 그 이상) 자동 처리
# -------------------------------
def update_recent_1000():
    all_pages = []
    has_more = True
    next_cursor = None
    target_count = 1000  # 목표 개수 설정

    try:
        print(f"📄 데이터를 가져오는 중...")
        
        while has_more and len(all_pages) < target_count:
            # 쿼리 실행
            response = notion.databases.query(
                database_id=DATABASE_ID,
                sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
                page_size=100,  # 한 번에 가져오는 최대치는 100
                start_cursor=next_cursor  # 다음 데이터의 시작점 지정
            )
            
            pages = response.get("results", [])
            all_pages.extend(pages)
            
            # 다음 페이지가 있는지 확인
            has_more = response.get("has_more")
            next_cursor = response.get("next_cursor")
            
            print(f"✅ 현재까지 {len(all_pages)}개 수집 완료...")

        # 수집된 페이지들 처리
        # 만약 정확히 1000개만 하고 싶다면 슬라이싱 사용
        pages_to_update = all_pages[:target_count]
        print(f"🚀 총 {len(pages_to_update)}개 페이지 수정 시작!")
        update_pages(pages_to_update)

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

# -------------------------------
# 실행
# -------------------------------
if __name__ == "__main__":
    update_recent_1000()
