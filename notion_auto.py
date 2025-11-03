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
    
    # 쿼리 매개변수 (정렬 방식)
    query_payload = {
        "sorts": [
            {
                "timestamp": "last_edited_time",
                "direction": "descending"
            }
        ]
    }
    
    try:
        # 🚨🚨🚨 핵심 수정: notion.databases.query 대신 클라이언트 내부의 databases.query 메서드를 직접 호출합니다. 🚨🚨🚨
        # notion_client의 내부 호출 경로를 명시적으로 지정하여
        # 'DatabasesEndpoint' 객체 오류를 우회합니다.
        
        # 'notion_client' 객체의 내부 엔드포인트에 직접 접근하는 방식 (버전 호환성을 높임)
        # 이전에 문제가 되었던 client.databases.query(DATABASE_ID, ...) 방식 대신, 
        # API 요청을 직접 생성합니다.
        
        # Notion API의 databases.query는 POST 요청입니다.
        response = notion.request(
            method="POST",
            path=f"databases/{DATABASE_ID}/query",
            body=query_payload
        )
        
    except Exception as e:
        # 오류 메시지를 명확하게 출력합니다.
        print(f"❌ 데이터베이스 쿼리 실패: '{e}'")
        
        # 만약 이 코드로도 실패한다면, 
        # notion-client 버전을 명시적으로 지정하여 설치해야 합니다.
        # (예: pip install notion-client==2.0.0)
        return

    results = response.get("results", [])
    print(f"✅ 총 {len(results)}개 페이지 가져오기 완료. (최근 수정된 100개)")
    
    # 2. 가져온 페이지를 순회하며 '기간' 업데이트를 시도합니다.
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

        # 5. 값이 바뀌지 않았다면 건너뜀
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
            print(f"❌ {page_id_short}... 업데이트 실패 (기간 속성 문제일 수 있음): {e}")

if __name__ == "__main__":
    update_period()
