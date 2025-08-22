import os
from notion_client import Client
from datetime import datetime, timedelta

notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

def parse_iso_naive(dt_str):
    """ISO 문자열을 offset-naive datetime으로 변환"""
    if not dt_str:
        return None
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1]
    return datetime.fromisoformat(dt_str)

def update_period():
    results = notion.databases.query(database_id=DATABASE_ID).get("results", [])
    print(f"총 {len(results)}개 페이지 처리")

    for page in results:
        props = page["properties"]

        # 시작
        start_value = props.get("시작")
        start_prop = start_value["date"]["start"] if start_value and start_value.get("date") else None

        # 종료
        end_value = props.get("종료")
        end_prop = end_value["date"]["start"] if end_value and end_value.get("date") else None

        if not start_prop or not end_prop:
            print(f"⏸ {page['id']} skipped: '시작' 또는 '종료' 속성이 비어 있음")
            continue

        start_dt = parse_iso_naive(start_prop)
        end_dt = parse_iso_naive(end_prop)

        # 종료가 시작보다 같거나 빠르면 하루 뒤로 보정
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(days=1)
            end_prop = end_dt.isoformat()

        # 현재 "기간" 값 가져오기
        current_period = props.get("기간", {}).get("date") or {}
        current_start = current_period.get("start")
        current_end = current_period.get("end")

        # 값이 바뀌었을 때만 업데이트
        if current_start != start_prop or current_end != end_prop:
            try:
                notion.pages.update(
                    page_id=page["id"],
                    properties={
                        "기간": {
                            "date": {
                                "start": start_prop,
                                "end": end_prop
                            }
                        }
                    }
                )
                print(f"✅ {page['id']} updated: {start_prop} ~ {end_prop}")
            except Exception as e:
                print(f"⚠ {page['id']} update failed:", e)
        else:
            print(f"⏸ {page['id']} skipped: 기간 unchanged")

if __name__ == "__main__":
    update_period()
