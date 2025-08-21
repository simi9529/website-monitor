import os
from notion_client import Client

# Notion 클라이언트 초기화
notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

def update_period():
    # 데이터베이스 쿼리
    results = notion.databases.query(database_id=DATABASE_ID).get("results", [])

    for page in results:
        props = page["properties"]
        start_prop = props.get("시작", {}).get("date", {}).get("start")
        end_prop = props.get("종료", {}).get("date", {}).get("start")

        # 종료 날짜가 있을 때만 업데이트
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
            print(f"⏸ {page['id']} skipped: '끝' 속성이 비어 있음")

if __name__ == "__main__":
    update_period()
