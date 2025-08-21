import os
from notion_client import Client

notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

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

        # 끝 날짜가 있을 때만 업데이트
        if end_prop:
            # 현재 "기간" 값 가져오기
            current_period = props.get("기간", {}).get("date", {})
            current_start = current_period.get("start")
            current_end = current_period.get("end")

            # 값이 다를 때만 업데이트
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
