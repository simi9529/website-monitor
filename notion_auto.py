import os
from notion_client import Client

notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

def update_period():
    results = notion.databases.query(database_id=DATABASE_ID).get("results", [])

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
            print(f"⏸ {page['id']} skipped: '종료' 속성이 비어 있음")

if __name__ == "__main__":
    update_period()
