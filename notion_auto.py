import os
from notion_client import Client
from datetime import datetime, timezone

# 환경 변수 설정. GitHub Actions에서 자동으로 사용됩니다.
notion = Client(auth=os.environ["NOTION_API_KEY"])
DATABASE_ID = os.environ["NOTION_DB_ID"]

def parse_iso_naive(dt_str):
    """ISO 문자열을 offset-naive UTC datetime으로 변환"""
    if not dt_str:
        return None
    try:
        # 'Z'로 끝나는 경우 (UTC)
        if dt_str.endswith("Z"):
            dt = datetime.fromisoformat(dt_str[:-1])
            return dt.replace(tzinfo=timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)
        
        # 기본 ISO 형식 처리
        dt = datetime.fromisoformat(dt_str)
        # 이미 timezone 정보가 있는 경우 → naive UTC로 변환
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as e:
        # 날짜 포맷이 예상과 다를 경우 오류 발생
        print(f"⚠ 날짜 파싱 오류 ({dt_str}): {e}")
        return None

def update_period():
    print("--- Notion 기간 자동 채우기 시작 (최근 100개만 모니터링) ---")
    
    # **핵심: 'last_edited_time'을 기준으로 내림차순(descending) 정렬하여 
    # 최근에 수정된 페이지부터 최대 100개만 가져오도록 요청합니다.**
    try:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            sorts=[
                {
                    "timestamp": "last_edited_time",
                    "direction": "descending"
                }
            ],
            # Notion API의 기본 제한에 따라 이 쿼리는 가장 최근 수정된 100개만 반환합니다.
        )
    except Exception as e:
        print(f"❌ 데이터베이스 쿼리 실패: {e}")
        return

    results = response.get("results", [])
    print(f"✅ 총 {len(results)}개 페이지 가져오기 완료. (최근 수정된 100개)")
    
    # 가져온 페이지를 순회하며 '기간' 업데이트를 시도합니다.
    for page in results:
        props = page["properties"]
        page_id_short = page["id"][:8] 

        # 1. '시작' 속성 값 추출
        start_value = props.get("시작")
        start_prop = start_value.get("date", {}).get("start") if start_value and start_value.get("date") else None

        # 2. '종료' 속성 값 추출
        end_value = props.get("종료")
        end_prop = end_value.get("date", {}).get("start") if end_value and end_value.get("date") else None

        # 3. 필수 값 확인
        if not start_prop or not end_prop:
            continue

        # 4. 현재 "기간" 값 가져오기
        current_period = props.get("기간", {}).get("date") or {}
        current_start = current_period.get("start")
        current_end = current_period.get("end")

        # 5. 값이 바뀌지 않았거나, 비어있지 않다면 건너뜀 (로그 출력 유지)
        if current_start == start_prop and current_end == end_prop:
            print(f"⏸ {page_id_short}... 건너뜀: 기간 unchanged")
            continue

        # 6. Notion 페이지 업데이트
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
            print(f"✅ {page_id_short}... 업데이트 성공: {start_prop} ~ {end_prop}")
        except Exception as e:
            # 업데이트 실패 시 오류 로그 출력 (이전 문제점 해결에 도움)
            print(f"❌ {page_id_short}... 업데이트 실패 (기간 속성 문제일 수 있음): {e}")

if __name__ == "__main__":
    update_period()
