import os
from notion_client import Client
from datetime import datetime, timezone

# 환경 변수 설정
notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

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


def update_period():
    print("--- Notion 기간 자동 채우기 시작 (최근 100개만 모니터링) ---")

    try:
        # ✅ 공식적이고 안정적인 방식
        response = notion.databases.query(
            database_id=DATABASE_ID,
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}]
        )
    except Exception as e:
        print(f"❌ 데이터베이스 쿼리 실패: {e}")
        return

    results = response.get("results", [])
    print(f"✅ 총 {len(results)}개 페이지 가져오기 완료. (최근 수정된 100개)")

    for page in results:
        props = page["properties"]
        page_id_short = page["id"][:8]

        # 시작
        start_value = props.get("시작")
        start_prop = start_value.get("date", {}).get("start") if start_value and start_value.get("date") else None

        # 종료
        end_value = props.get("종료")
        end_prop = end_value.get("date", {}).get("start") if end_value and end_value.get("date") else None

        if not start_prop or not end_prop:
            continue

        # 기간
        current_period = props.get("기간", {}).get("date") or {}
        current_start = current_period.get("start")
        current_end = current_period.get("end")

        # 변경 필요 없으면 스킵
        if current_start == start_prop and current_end == end_prop:
            print(f"⏸ {page_id_short}... 건너뜀: 기간 unchanged")
            continue

        try:
            notion.pages.update(
                page_id=page["id"],
                properties={
                    "기간": {
                        "date": {"start": start_prop, "end": end_prop}
                    }
                }
            )
            print(f"✅ {page_id_short}... 업데이트 성공: {start_prop} ~ {end_prop}")
        except Exception as e:
            print(f"❌ {page_id_short}... 업데이트 실패 (기간 속성 문제일 수 있음): {e}")


if __name__ == "__main__":
    update_period()
