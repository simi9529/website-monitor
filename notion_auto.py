import os
from notion_client import Client
from datetime import timedelta
from dateutil.parser import isoparse  # pip install python-dateutil

notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

def parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        return isoparse(dt_str)  # offset-aware datetime 반환
    except Exception:
        return None

def update_period():
    results = notion.databases.query(database_id=DATABASE_ID).get("results", [])
    print(f"총 {len(results)}개 페이지 처리")

    for page in results:
        props = page["properties"]

        # 시작 날짜
        start_prop = None
        start_value = props.get("시작")
        if start_value and start_value.get("date"):
            start_prop = start_value["date"].get("start")

        # 종료 날짜
        end_prop = None
        end_value = props.get("종료")
        if end_value and end_value.get("date"):
            end_prop = end_value["date"].get("start")

        if end_prop:
            start_dt = parse_iso(start_prop)
            end_dt = parse_iso(end_prop)

            # 종료가 시작보다 같거나 빠르면 하루 뒤로 보정
            if start_dt and end_dt and end_dt <= start_dt:
                end_dt += timedelta(days=1)
                end_prop = end_dt.isoformat()

            current_period = props.get("기간", {}).get("date") or {}
            current_start = current_period.get("start")
            current_end = current_period.get("end")

            if current_start != start_prop or current_end != end_prop:
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
            else:
                print(f"⏸ {page['id']} skipped: 기간 unchanged")
        else:
            print(f"⏸ {page['id']} skipped: '종료' 속성이 비어 있음")

if __name__ == "__main__":
    update_period()
